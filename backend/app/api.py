"""REST API (4.2 / Table 12 plus supporting endpoints)."""
from __future__ import annotations

import csv
import io
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ai, config
from .database import SessionLocal, get_db
from .evaluation import run_evaluation
from .models import (
    Alert, AuditLog, Baseline, CaseNote, Detection, Event, EvaluationRun, Honeytoken, ParseError, RiskPoint,
    RuleConfig, Subject, User, utcnow,
)
from .pipeline import current_risk, dataset_end, ingest_records, load_config, reprocess_users
from .security import (
    ROLES, audit, create_token, get_current_user, hash_password, require_admin, require_staff, verify_password,
)

router = APIRouter(prefix="/api")

# --------------------------------------------------------------------------- helpers
_login_failures: dict[str, list[float]] = defaultdict(list)
LOCK_AFTER, LOCK_WINDOW = 5, 15 * 60


def _iso(dt):
    return dt.isoformat() if dt else None


def _alert_dict(a: Alert, dept: str | None = None, notes: list | None = None) -> dict:
    out = {
        "id": a.id, "user_id": a.user_id, "department": dept, "start_time": _iso(a.start_time),
        "last_time": _iso(a.last_time), "peak_score": a.peak_score, "category": a.category,
        "status": a.status, "breakdown": a.breakdown, "narrative": a.narrative,
        "narrative_status": a.narrative_status,
        "narrative_disclaimer": ai.DISCLAIMER if a.narrative else None,
    }
    if notes is not None:
        out["notes"] = [{"id": n.id, "author": n.author, "note": n.note, "created_at": _iso(n.created_at)} for n in notes]
    return out


def _auto_explain(alert_ids: list[int]) -> None:
    """Background task: request narratives for High/Critical alerts (never blocks or alters scores)."""
    db = SessionLocal()
    try:
        for aid in alert_ids:
            a = db.get(Alert, aid)
            if a and a.category in ("High", "Critical") and a.narrative_status == "none":
                ai.explain_alert(db, a)
    finally:
        db.close()


def _after_ingest(res: dict, db: Session, bg: BackgroundTasks) -> dict:
    if res["accepted"]:
        reprocess_users(db, res["affected_users"])
        if ai.ai_configured():
            ids = [a.id for a in db.scalars(select(Alert).where(
                Alert.user_id.in_(res["affected_users"]), Alert.narrative_status == "none",
                Alert.category.in_(["High", "Critical"])))]
            if ids:
                bg.add_task(_auto_explain, ids)
    return res


# --------------------------------------------------------------------------- auth
class AccountIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=72)
    role: str


@router.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    now = time.time()
    key = form.username.lower()
    recent = [t for t in _login_failures[key] if now - t < LOCK_WINDOW]
    _login_failures[key] = recent
    if len(recent) >= LOCK_AFTER:
        raise HTTPException(429, "Too many failed attempts. Try again later.")
    user = db.scalar(select(User).where(User.username == form.username))
    if not user or not verify_password(form.password, user.password_hash):
        _login_failures[key].append(now)
        audit(db, form.username, "login_failed")
        db.commit()
        raise HTTPException(401, "Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    _login_failures.pop(key, None)
    audit(db, user, "login")
    db.commit()
    return {"access_token": create_token(user), "token_type": "bearer", "role": user.role, "username": user.username}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}


@router.post("/auth/accounts", status_code=201)
def create_account(body: AccountIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "username already exists")
    db.add(User(username=body.username, password_hash=hash_password(body.password), role=body.role))
    audit(db, admin, "create_account", body.username, {"role": body.role})
    db.commit()
    return {"username": body.username, "role": body.role}


# --------------------------------------------------------------------------- telemetry ingestion (3.1)
@router.post("/events")
def post_events(bg: BackgroundTasks, payload: Any = Body(...), db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    """Accepts one event object, a JSON array, or {"events": [...]}."""
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        records = payload["events"]
    elif isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = [payload]
    else:
        raise HTTPException(422, {"message": "Body must be an event object or an array of events", "errors": []})
    if not records:
        raise HTTPException(422, {"message": "No events supplied", "errors": []})
    if len(records) > config.MAX_BATCH_RECORDS:
        raise HTTPException(413, f"Batch exceeds {config.MAX_BATCH_RECORDS} records")
    res = ingest_records(db, records, "api")
    audit(db, admin, "ingest_events", "api", {"accepted": res["accepted"], "rejected": res["rejected"]})
    db.commit()
    if res["accepted"] == 0:
        raise HTTPException(422, {"message": "All records failed validation", "errors": res["errors"]})
    return _after_ingest(res, db, bg)


@router.post("/events/import")
async def import_events(bg: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db),
                        admin: User = Depends(require_admin)):
    raw = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, {"message": "File must be UTF-8 encoded CSV or JSON", "errors": []})
    name = (file.filename or "").lower()
    try:
        if name.endswith(".json") or text.lstrip().startswith(("[", "{")):
            data = json.loads(text)
            records = data["events"] if isinstance(data, dict) and "events" in data else data
            if not isinstance(records, list):
                raise ValueError("JSON must be an array of events or {\"events\": [...]}")
        else:
            records = list(csv.DictReader(io.StringIO(text)))
    except (ValueError, KeyError, csv.Error) as exc:
        raise HTTPException(422, {"message": f"Could not parse file: {exc}", "errors": []})
    if not records:
        raise HTTPException(422, {"message": "File contains no records", "errors": []})
    if len(records) > config.MAX_BATCH_RECORDS:
        raise HTTPException(413, f"File exceeds {config.MAX_BATCH_RECORDS} records")
    res = ingest_records(db, records, "import")
    audit(db, admin, "import_events", file.filename or "", {"accepted": res["accepted"], "rejected": res["rejected"]})
    db.commit()
    if res["accepted"] == 0:
        raise HTTPException(422, {"message": "All records failed validation", "errors": res["errors"]})
    return _after_ingest(res, db, bg)


@router.get("/parse-errors")
def parse_errors(limit: int = Query(100, le=500), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.scalars(select(ParseError).order_by(ParseError.id.desc()).limit(limit)).all()
    return [{"id": r.id, "created_at": _iso(r.created_at), "source": r.source, "row": r.row_ref,
             "errors": r.errors, "raw": r.raw} for r in rows]


# --------------------------------------------------------------------------- users / risk
@router.get("/users")
def list_users(department: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    """Ranked list of users by current risk score and category (REQ-09-01)."""
    cfg = load_config(db)
    risk = current_risk(db, cfg)
    open_alerts = dict(db.execute(select(Alert.user_id, func.count()).where(Alert.status != "closed").group_by(Alert.user_id)).all())
    out = []
    for s in db.scalars(select(Subject)):
        if department and s.department != department:
            continue
        r = risk.get(s.user_id)
        out.append({
            "user_id": s.user_id, "department": s.department, "baseline_status": s.baseline_status,
            "event_count": s.event_count, "risk_score": r["score"] if r else 0.0,
            "risk_category": r["category"] if r else "Low", "risk_as_of": _iso(r["as_of"]) if r else None,
            "open_alerts": open_alerts.get(s.user_id, 0),
        })
    out.sort(key=lambda x: (-x["risk_score"], x["user_id"]))
    return out


@router.get("/users/{user_id}/risk")
def user_risk(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    sub = db.get(Subject, user_id)
    if not sub:
        raise HTTPException(404, "Unknown user")
    cfg = load_config(db)
    r = current_risk(db, cfg).get(user_id)
    base = db.get(Baseline, user_id)
    alerts = db.scalars(select(Alert).where(Alert.user_id == user_id).order_by(Alert.start_time.desc())).all()
    audit(db, user, "view_user_risk", user_id)
    db.commit()
    return {
        "user_id": user_id, "department": sub.department, "baseline_status": sub.baseline_status,
        "risk_score": r["score"] if r else 0.0, "risk_category": r["category"] if r else "Low",
        "as_of": _iso(r["as_of"]) if r else None, "breakdown": r["breakdown"] if r else [],
        "baseline": ({"status": base.status, "window_start": _iso(base.window_start),
                      "window_end": _iso(base.window_end), "event_count": base.event_count, **(base.stats or {})}
                     if base else None),
        "alerts": [_alert_dict(a, sub.department) for a in alerts],
        "note": "Risk scores are investigative leads only and are not proof of malicious intent.",
    }


@router.get("/users/{user_id}/timeline")
def user_timeline(user_id: str, start: datetime | None = None, end: datetime | None = None,
                  limit: int = Query(500, le=5000), db: Session = Depends(get_db), user: User = Depends(require_staff)):
    """Evidence-based timeline: indicators with weights, newest first (REQ-09-02)."""
    if not db.get(Subject, user_id):
        raise HTTPException(404, "Unknown user")
    q = select(Detection).where(Detection.user_id == user_id)
    if start:
        q = q.where(Detection.time >= start)
    if end:
        q = q.where(Detection.time <= end)
    dets = db.scalars(q.order_by(Detection.time.desc()).limit(limit)).all()
    ev_ids = [d.event_id for d in dets if d.event_id]
    events = {e.id: e for e in db.scalars(select(Event).where(Event.id.in_(ev_ids)))} if ev_ids else {}
    return [{
        "time": _iso(d.time), "source": d.source, "category": d.category, "indicator": d.name, "weight": d.weight,
        "detail": d.detail,
        "event": ({"event_type": e.event_type, "resource": e.resource, "device_id": e.device_id,
                   "result": e.result, "volume_mb": e.volume_mb} if (e := events.get(d.event_id)) else None),
    } for d in dets]


@router.get("/users/{user_id}/activity")
def user_activity(user_id: str, days: int = Query(30, le=120), db: Session = Depends(get_db),
                  user: User = Depends(require_staff)):
    """Daily file-access count and download volume vs the user's baseline (for charts)."""
    if not db.get(Subject, user_id):
        raise HTTPException(404, "Unknown user")
    end = dataset_end(db)
    since = end - timedelta(days=days)
    rows = db.execute(select(Event.timestamp, Event.event_type, Event.volume_mb).where(
        Event.user_id == user_id, Event.timestamp >= since)).all()
    agg: dict = defaultdict(lambda: {"access": 0, "download_mb": 0.0})
    for ts, et, vol in rows:
        if et == "file_access":
            agg[ts.date().isoformat()]["access"] += 1
        elif et == "download":
            agg[ts.date().isoformat()]["download_mb"] += vol or 0.0
    base = db.get(Baseline, user_id)
    return {"days": [{"date": d, **{k: round(v, 1) for k, v in x.items()}} for d, x in sorted(agg.items())],
            "baseline": base.stats if base else None}


# --------------------------------------------------------------------------- alerts & cases
@router.get("/alerts")
def list_alerts(status: str | None = None, category: str | None = None, department: str | None = None,
                user_id: str | None = None, limit: int = Query(200, le=1000), db: Session = Depends(get_db),
                user: User = Depends(require_staff)):
    q = select(Alert, Subject.department).join(Subject, Subject.user_id == Alert.user_id)
    if status:
        q = q.where(Alert.status == status)
    if category:
        q = q.where(Alert.category == category)
    if department:
        q = q.where(Subject.department == department)
    if user_id:
        q = q.where(Alert.user_id == user_id)
    rows = db.execute(q.order_by(Alert.peak_score.desc(), Alert.start_time.desc()).limit(limit)).all()
    return [_alert_dict(a, d) for a, d in rows]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    sub = db.get(Subject, a.user_id)
    notes = db.scalars(select(CaseNote).where(CaseNote.alert_id == a.id).order_by(CaseNote.id)).all()
    audit(db, user, "view_alert", str(a.id), {"score": a.peak_score})  # REQ-10-01: reviewing the score
    db.commit()
    return _alert_dict(a, sub.department if sub else None, notes)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(open|under_investigation|closed)$")


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


@router.patch("/alerts/{alert_id}")
def update_alert(alert_id: int, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    old, a.status, a.updated_at = a.status, body.status, utcnow()
    audit(db, user, "change_case_status", str(a.id), {"from": old, "to": body.status})
    db.commit()
    return _alert_dict(a)


@router.post("/alerts/{alert_id}/notes", status_code=201)
def add_note(alert_id: int, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    if not db.get(Alert, alert_id):
        raise HTTPException(404, "Alert not found")
    n = CaseNote(alert_id=alert_id, author=user.username, note=body.note.strip())
    db.add(n)
    audit(db, user, "add_investigation_note", str(alert_id), {"length": len(body.note)})
    db.commit()
    return {"id": n.id, "author": n.author, "note": n.note, "created_at": _iso(n.created_at)}


@router.post("/alerts/{alert_id}/explain")
def explain(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    ok = ai.explain_alert(db, a)
    audit(db, user, "request_ai_explanation", str(a.id), {"ok": ok})
    db.commit()
    return {**_alert_dict(a), "ai_available": ok}


# --------------------------------------------------------------------------- dashboard & reports
@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    cfg = load_config(db)
    risk = current_risk(db, cfg)
    subjects = db.scalars(select(Subject)).all()
    dept_of = {s.user_id: s.department for s in subjects}
    dist = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    dept: dict = defaultdict(lambda: {"users": 0, "avg_risk": 0.0, "max_risk": 0.0, "open": 0,
                                       "under_investigation": 0, "closed": 0})
    for s in subjects:
        r = risk.get(s.user_id)
        score = r["score"] if r else 0.0
        dist[r["category"] if r else "Low"] += 1
        d = dept[s.department]
        d["users"] += 1
        d["avg_risk"] += score
        d["max_risk"] = max(d["max_risk"], score)
    for d in dept.values():
        d["avg_risk"] = round(d["avg_risk"] / d["users"], 1) if d["users"] else 0.0
    alerts = db.scalars(select(Alert)).all()
    by_status = {"open": 0, "under_investigation": 0, "closed": 0}
    trend: dict = defaultdict(lambda: defaultdict(int))
    by_cat = {"Medium": 0, "High": 0, "Critical": 0}
    for a in alerts:
        by_status[a.status] = by_status.get(a.status, 0) + 1
        dept[dept_of.get(a.user_id, "Unknown")][a.status] += 1
        trend[a.start_time.date().isoformat()][dept_of.get(a.user_id, "Unknown")] += 1
        by_cat[a.category] = by_cat.get(a.category, 0) + 1
    top = sorted(((u, r) for u, r in risk.items()), key=lambda x: -x[1]["score"])[:10]
    return {
        "as_of": _iso(dataset_end(db)),
        "totals": {"users": len(subjects), "events": db.scalar(select(func.count()).select_from(Event)),
                   "alerts": len(alerts), "honeytokens_active": db.scalar(
                       select(func.count()).select_from(Honeytoken).where(Honeytoken.active.is_(True))),
                   "baselines_established": sum(1 for s in subjects if s.baseline_status == "established")},
        "risk_distribution": dist, "alerts_by_status": by_status, "alerts_by_category": by_cat,
        "departments": {k: v for k, v in sorted(dept.items())},
        "alert_trend": [{"date": d, "departments": dict(v), "total": sum(v.values())} for d, v in sorted(trend.items())],
        "top_risky_users": [{"user_id": u, "department": dept_of.get(u), "score": r["score"], "category": r["category"]}
                            for u, r in top],
        "ai_configured": ai.ai_configured(),
    }


@router.get("/reports/risk")
def risk_report(start: datetime | None = None, end: datetime | None = None, department: str | None = None,
                format: str = Query("json", pattern="^(json|csv)$"), db: Session = Depends(get_db),
                user: User = Depends(require_staff)):
    """Structured report of coverage and risk findings for a period/department (REQ-09-05)."""
    subs = {s.user_id: s for s in db.scalars(select(Subject))}
    q = select(Alert)
    if start:
        q = q.where(Alert.start_time >= start)
    if end:
        q = q.where(Alert.start_time <= end)
    alerts = [a for a in db.scalars(q.order_by(Alert.peak_score.desc()))
              if not department or subs.get(a.user_id) and subs[a.user_id].department == department]
    eq = select(func.count()).select_from(Event)
    if start:
        eq = eq.where(Event.timestamp >= start)
    if end:
        eq = eq.where(Event.timestamp <= end)
    if department:
        eq = eq.where(Event.department == department)
    rows = [{
        "alert_id": a.id, "user_id": a.user_id, "department": subs[a.user_id].department if a.user_id in subs else "",
        "start_time": _iso(a.start_time), "peak_score": a.peak_score, "category": a.category, "status": a.status,
        "indicators": "; ".join(f"{b['name']}({b['weight']:g})" for b in a.breakdown or []),
    } for a in alerts]
    audit(db, user, "generate_report", department or "all", {"format": format, "alerts": len(rows)})
    db.commit()
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["alert_id"])
        w.writeheader()
        w.writerows(rows)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=insiderguard_risk_report.csv"})
    cats: dict = defaultdict(int)
    for r in rows:
        cats[r["category"]] += 1
    return {
        "generated_at": _iso(utcnow()), "filters": {"start": _iso(start), "end": _iso(end), "department": department},
        "coverage": {"events_analysed": db.scalar(eq), "users_monitored": len([s for s in subs.values()
                     if not department or s.department == department]),
                     "baselines_established": len([s for s in subs.values() if s.baseline_status == "established"
                                                   and (not department or s.department == department)])},
        "alerts_by_category": dict(cats), "alerts": rows,
        "disclaimer": "Risk scores are investigative leads only and are not proof of malicious intent.",
    }


# --------------------------------------------------------------------------- honeytokens (3.6)
class HoneytokenIn(BaseModel):
    resource: str = Field(min_length=3, max_length=512)
    description: str | None = Field(default=None, max_length=256)


@router.get("/honeytokens")
def list_honeytokens(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return [{"id": h.id, "resource": h.resource, "description": h.description, "active": h.active,
             "created_by": h.created_by, "created_at": _iso(h.created_at), "revoked_at": _iso(h.revoked_at)}
            for h in db.scalars(select(Honeytoken).order_by(Honeytoken.id))]


@router.post("/honeytokens", status_code=201)
def create_honeytoken(body: HoneytokenIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    resource = body.resource.strip()
    existing = db.scalar(select(Honeytoken).where(Honeytoken.resource == resource))
    if existing and existing.active:
        raise HTTPException(409, "Honeytoken already registered")
    if existing:  # re-activate a revoked decoy
        existing.active, existing.revoked_at, h = True, None, existing
    else:
        h = Honeytoken(resource=resource, description=body.description, created_by=admin.username)
        db.add(h)
    audit(db, admin, "create_honeytoken", resource)
    db.commit()
    _rescore_resource(db, resource)
    return {"id": h.id, "resource": h.resource, "active": True}


@router.delete("/honeytokens/{token_id}")
def revoke_honeytoken(token_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    h = db.get(Honeytoken, token_id)
    if not h:
        raise HTTPException(404, "Honeytoken not found")
    h.active, h.revoked_at = False, utcnow()
    audit(db, admin, "revoke_honeytoken", h.resource)
    db.commit()
    _rescore_resource(db, h.resource)
    return {"id": h.id, "resource": h.resource, "active": False}


def _rescore_resource(db: Session, resource: str) -> None:
    users = [r[0] for r in db.execute(select(Event.user_id).where(Event.resource == resource).distinct())]
    if users:
        reprocess_users(db, users)


# --------------------------------------------------------------------------- rules (3.4)
class RulesIn(BaseModel):
    values: dict[str, float]


@router.get("/rules")
def get_rules(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return [{"key": r.key, "value": r.value, "default": config.DEFAULT_RULES[r.key][0],
             "description": r.description, "updated_by": r.updated_by, "updated_at": _iso(r.updated_at)}
            for r in db.scalars(select(RuleConfig).order_by(RuleConfig.key)) if r.key in config.DEFAULT_RULES]


@router.put("/rules")
def update_rules(body: RulesIn, background: BackgroundTasks, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    unknown = [k for k in body.values if k not in config.DEFAULT_RULES]
    if unknown:
        raise HTTPException(422, f"Unknown rule keys: {unknown}")
    bad = [k for k, v in body.values.items() if v != v or v < 0 or v > 1_000_000]
    if bad:
        raise HTTPException(422, f"Values must be between 0 and 1,000,000: {bad}")
    changes = {}
    for key, val in body.values.items():
        row = db.get(RuleConfig, key)
        if row.value != val:
            changes[key] = {"from": row.value, "to": val}
            row.value, row.updated_by, row.updated_at = val, admin.username, utcnow()
    audit(db, admin, "modify_rules", "rule_config", changes)
    db.commit()
    if changes:
        reprocess_users(db)  # thresholds changed -> rescore everyone (REQ-07-04)
    return {"changed": changes}


# --------------------------------------------------------------------------- evaluation & audit (3.10)
@router.get("/evaluation/results")
def evaluation_results(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    run = db.scalar(select(EvaluationRun).order_by(EvaluationRun.id.desc()))
    if not run:
        raise HTTPException(404, "No evaluation has been run yet")
    return {"run_id": run.id, "run_by": run.run_by, **run.results}


@router.post("/evaluation/run")
def evaluation_run(threshold: float | None = Query(None, ge=1, le=100), db: Session = Depends(get_db),
                   user: User = Depends(require_staff)):
    result = run_evaluation(db, run_by=user.username, threshold=threshold)
    if "error" in result:
        raise HTTPException(409, result["error"])
    audit(db, user, "run_evaluation", "labelled_dataset", {"threshold": result["alert_threshold"]})
    db.commit()
    return result


@router.get("/audit")
def audit_log(limit: int = Query(200, le=1000), actor: str | None = None, db: Session = Depends(get_db),
              admin: User = Depends(require_admin)):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if actor:
        q = q.where(AuditLog.actor == actor)
    return [{"id": a.id, "timestamp": _iso(a.timestamp), "actor": a.actor, "role": a.role, "action": a.action,
             "target": a.target, "detail": a.detail} for a in db.scalars(q)]


@router.post("/admin/recompute")
def recompute(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    res = reprocess_users(db)
    audit(db, admin, "recompute_all", "all", res)
    db.commit()
    return res
