"""REST API (4.2 / Table 12 plus supporting endpoints)."""
from __future__ import annotations

import csv
import io
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import ai, cases, config, mitre, resolutions
from .database import SessionLocal, get_db
from .evaluation import run_evaluation
from .models import (
    Alert, AuditLog, Baseline, CaseNote, Detection, Event, EvaluationRun, Honeytoken, ParseError, RiskPoint,
    AlertAssignment, CaseEvent, Escalation, RuleConfig, Subject, User, utcnow,
)
from .pipeline import current_risk, dataset_end, ingest_records, load_config, reprocess_users
from .reports import router as reports_router
from .employees import router as employees_router
from .user_overview import router as user_overview_router
from .escalations import router as escalations_router
from .security import (
    ROLES, audit, create_token, get_current_user, hash_password, require_admin, require_analyst, require_staff, verify_password,
)

router = APIRouter(prefix="/api")
router.include_router(reports_router)
router.include_router(employees_router)
router.include_router(user_overview_router)
router.include_router(escalations_router)

# --------------------------------------------------------------------------- helpers
_login_failures: dict[str, list[float]] = defaultdict(list)
LOCK_AFTER, LOCK_WINDOW = 5, 15 * 60


def _iso(dt):
    return dt.isoformat() if dt else None


def _alert_dict(a: Alert, dept: str | None = None, notes: list | None = None,
                assignment: AlertAssignment | None = None, detection_state: str | None = None, resolution=None) -> dict:
    out = {
        "id": a.id, "user_id": a.user_id, "department": dept, "start_time": _iso(a.start_time),
        "last_time": _iso(a.last_time), "peak_score": a.peak_score, "category": a.category,
        "status": a.status, "breakdown": mitre.enrich_breakdown(a.breakdown), "narrative": a.narrative,
        "attack": mitre.attack_summary(a.breakdown),
        "narrative_status": a.narrative_status,
        "narrative_disclaimer": ai.DISCLAIMER if a.narrative else None,
        "owner": assignment.owner if assignment else None,
        "assigned_at": _iso(assignment.assigned_at) if assignment else None,
        "detection_state": detection_state,
        "resolution": resolutions.as_dict(resolution) if a.status == "closed" else None,
        "outcome": resolution.outcome if a.status == "closed" and resolution else None,
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
    password: str
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
    return {"username": user.username, "role": user.role, "created_at": _iso(user.created_at)}


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(body: ChangePasswordIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    key = f"pw:{user.username.lower()}"
    now = time.time()
    recent = [attempt for attempt in _login_failures[key] if now - attempt < LOCK_WINDOW]
    _login_failures[key] = recent
    if len(recent) >= LOCK_AFTER:
        raise HTTPException(429, "Too many failed attempts. Try again later.")
    if not verify_password(body.current_password, user.password_hash):
        _login_failures[key].append(now)
        audit(db, user, "change_password_failed", user.username)
        db.commit()
        raise HTTPException(400, "Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(422, "New password must differ from the current password")
    user.password_hash = hash_password(body.new_password, user.username)
    audit(db, user, "change_password", user.username)
    db.commit()
    _login_failures.pop(key, None)
    return {"access_token": create_token(user), "token_type": "bearer"}


@router.get("/auth/accounts")
def list_accounts(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    counts = dict(db.execute(select(AlertAssignment.owner, func.count()).join(Alert, Alert.id == AlertAssignment.alert_id)
                            .where(Alert.status != "closed").group_by(AlertAssignment.owner)).all())
    return [{"id": user.id, "username": user.username, "role": user.role, "created_at": _iso(user.created_at),
             **({"open_cases": counts.get(user.username, 0)} if user.role == "analyst" else {})}
            for user in db.scalars(select(User).order_by(User.created_at, User.id))]


@router.post("/auth/accounts", status_code=201)
def create_account(body: AccountIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    if db.scalar(select(User).where(func.lower(User.username) == body.username.lower())):
        raise HTTPException(409, "username already exists")
    db.add(User(username=body.username, password_hash=hash_password(body.password, body.username), role=body.role))
    audit(db, admin, "create_account", body.username, {"role": body.role})
    db.commit()
    return {"username": body.username, "role": body.role}


class ResetPasswordIn(BaseModel):
    new_password: str


@router.delete("/auth/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    admins = list(db.scalars(select(User).where(User.role == "admin").with_for_update()))
    target = db.get(User, account_id)
    if target is None:
        raise HTTPException(404, "Account not found")
    if target.role == "admin" and len(admins) <= 1:
        raise HTTPException(409, "Cannot delete the last remaining administrator")
    if target.id == admin.id:
        raise HTTPException(409, "Cannot delete your own account")
    username = target.username
    released = cases.release_account_cases(db, username, admin) if target.role == "analyst" else 0
    audit(db, admin, "delete_account", username, {"role": target.role, "released_cases": released})
    db.delete(target)
    db.commit()
    return {"deleted": username}


@router.post("/auth/accounts/{account_id}/reset-password")
def reset_account_password(account_id: int, body: ResetPasswordIn, db: Session = Depends(get_db),
                           admin: User = Depends(require_admin)):
    target = db.get(User, account_id)
    if target is None:
        raise HTTPException(404, "Account not found")
    if target.id == admin.id:
        raise HTTPException(409, "Cannot reset your own password here; use self-service password change")
    target.password_hash = hash_password(body.new_password, target.username)
    audit(db, admin, "reset_password", target.username, {"role": target.role})
    db.commit()
    return {"reset": target.username}


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
    from .models import EmployeeProfile
    profile_ids = set(db.scalars(select(EmployeeProfile.user_id)))
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
              "open_case_count": open_alerts.get(s.user_id, 0),
              "has_profile": s.user_id in profile_ids, "last_seen": _iso(s.last_seen),
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
    assignments = cases.owners_for(db, [a.id for a in alerts])
    states = cases.detection_states(db, [a.id for a in alerts])
    verdicts = resolutions.current_for(db, [a.id for a in alerts])
    audit(db, user, "view_user_risk", user_id)
    db.commit()
    return {
        "user_id": user_id, "department": sub.department, "baseline_status": sub.baseline_status,
        "risk_score": r["score"] if r else 0.0, "risk_category": r["category"] if r else "Low",
        "as_of": _iso(r["as_of"]) if r else None, "breakdown": mitre.enrich_breakdown(r["breakdown"] if r else []),
        "baseline": ({"status": base.status, "window_start": _iso(base.window_start),
                      "window_end": _iso(base.window_end), "event_count": base.event_count, **(base.stats or {})}
                     if base else None),
        "alerts": [_alert_dict(a, sub.department, assignment=assignments.get(a.id), detection_state=states.get(a.id), resolution=verdicts.get(a.id)) for a in alerts],
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
        "attack": mitre.resolve(mitre.techniques_for(d.name, d.detail), d.name, d.detail),
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
def _case_or_404(db, alert_id):
    alert = db.scalar(select(Alert).where(Alert.id == alert_id).with_for_update())
    if alert is None:
        raise HTTPException(404, "Alert not found")
    return alert


def _owned_alert_dict(db, alert):
    subject = db.get(Subject, alert.user_id)
    return _alert_dict(alert, subject.department if subject else None,
                       assignment=cases.owners_for(db, [alert.id]).get(alert.id),
                       detection_state=cases.detection_states(db, [alert.id]).get(alert.id),
                       resolution=resolutions.current_for(db, [alert.id]).get(alert.id))


class ReleaseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class AssignIn(BaseModel):
    owner: str = Field(min_length=1, max_length=64)


@router.post("/alerts/{alert_id}/claim")
def claim_alert(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_analyst)):
    alert = _case_or_404(db, alert_id)
    if alert.status == "closed":
        raise HTTPException(409, "Closed cases cannot be claimed")
    owner = cases.get_owner(db, alert_id)
    if owner:
        raise HTTPException(409, f"Already claimed by {owner}")
    db.add(AlertAssignment(alert_id=alert_id, owner=user.username, assigned_by=user.username))
    try:
        db.flush()  # The unique alert_id constraint decides concurrent claims, not the read above.
    except IntegrityError:
        db.rollback()
        owner = cases.get_owner(db, alert_id)
        raise HTTPException(409, f"Already claimed by {owner}" if owner else "Case ownership changed; try again")
    cases.record_event(db, alert, "claimed", user, {"from": None, "to": user.username})
    audit(db, user, "claim_case", str(alert_id), {"owner": user.username})
    db.commit()
    return _owned_alert_dict(db, alert)


@router.post("/alerts/{alert_id}/release")
def release_alert(alert_id: int, body: ReleaseIn, db: Session = Depends(get_db), user: User = Depends(require_analyst)):
    alert = _case_or_404(db, alert_id)
    assignment = cases.require_owner(db, alert, user)
    if alert.status == "closed":
        raise HTTPException(409, "Closed cases cannot be released")
    reason = body.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "Reason must contain at least 3 non-padding characters")
    cases.release_assignment(db, alert, assignment, user, reason)
    db.commit()
    return _owned_alert_dict(db, alert)


@router.post("/alerts/{alert_id}/assign")
def assign_alert(alert_id: int, body: AssignIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    alert = _case_or_404(db, alert_id)
    target = db.scalar(select(User).where(User.username == body.owner).with_for_update())
    if target is None or target.role != "analyst":
        raise HTTPException(422, "Owner must be an existing analyst")
    assignment = db.scalar(select(AlertAssignment).where(AlertAssignment.alert_id == alert_id).with_for_update())
    previous = assignment.owner if assignment else None
    now = utcnow()
    if assignment is None:
        assignment = AlertAssignment(alert_id=alert_id, owner=target.username, assigned_by=admin.username,
                                     assigned_at=now, updated_at=now)
        db.add(assignment)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Case ownership changed; refresh and try again")
    else:
        assignment.owner, assignment.assigned_by = target.username, admin.username
        assignment.assigned_at = assignment.updated_at = now
    action = "reassigned" if previous else "assigned"
    detail = {"from": previous, "to": target.username}
    cases.record_event(db, alert, action, admin, detail)
    audit(db, admin, "reassign_case" if previous else "assign_case", str(alert_id), detail)
    db.commit()
    return _owned_alert_dict(db, alert)


@router.get("/alerts/{alert_id}/events")
def alert_events(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    if db.get(Alert, alert_id) is None:
        raise HTTPException(404, "Alert not found")
    return [{"id": e.id, "alert_id": e.alert_id, "action": e.action, "actor": e.actor,
             "actor_role": e.actor_role, "detail": e.detail, "created_at": _iso(e.created_at)}
            for e in db.scalars(select(CaseEvent).where(CaseEvent.alert_id == alert_id)
                                .order_by(CaseEvent.created_at, CaseEvent.id))]


@router.get("/my-cases")
def my_cases(status: Literal["open", "under_investigation", "closed"] | None = None,
              db: Session = Depends(get_db), user: User = Depends(require_analyst)):
    rows = db.execute(select(Alert, Subject.department, AlertAssignment)
                      .join(AlertAssignment, AlertAssignment.alert_id == Alert.id)
                      .outerjoin(Subject, Subject.user_id == Alert.user_id)
                      .where(AlertAssignment.owner == user.username).order_by(Alert.start_time, Alert.id)).all()
    states = cases.detection_states(db, [a.id for a, _, _ in rows])
    verdicts = resolutions.current_for(db, [a.id for a, _, _ in rows])
    now = utcnow()
    return {"cases": [{**_alert_dict(a, department, assignment=assignment, detection_state=states.get(a.id), resolution=verdicts.get(a.id)),
                        "age_hours": cases.age_hours(a, now)} for a, department, assignment in rows
                       if not status or a.status == status],
            "summary": cases.summarize([a for a, _, _ in rows], now)}


@router.get("/team/workload")
def team_workload(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return cases.workload(db)


@router.get("/alerts")
def list_alerts(status: str | None = None, category: str | None = None, department: str | None = None,
                user_id: str | None = None, owner: str | None = None, outcome: str | None = None, limit: int = Query(200, ge=1, le=1000),
                sort_by: Literal['id', 'user_id', 'department', 'start_time', 'peak_score', 'category', 'status', 'indicator_count', 'owner'] = 'peak_score',
                sort_dir: Literal['asc', 'desc'] = 'desc',
                then_by: Literal['id', 'user_id', 'department', 'start_time', 'peak_score', 'category', 'status', 'indicator_count', 'owner', ''] | None = Query('start_time', description='Secondary column; empty disables secondary sorting'),
                then_dir: Literal['asc', 'desc'] = 'desc', db: Session = Depends(get_db),
                user: User = Depends(require_staff)):
    q = select(Alert, Subject.department, AlertAssignment).join(Subject, Subject.user_id == Alert.user_id).outerjoin(
        AlertAssignment, AlertAssignment.alert_id == Alert.id)
    outcomes = resolutions.parse_outcomes(outcome)
    if outcomes:
        current = resolutions.current_query().subquery()
        q = q.join(current, current.c.alert_id == Alert.id).where(current.c.outcome.in_(outcomes))
    if owner == "unassigned":
        q = q.where(AlertAssignment.id.is_(None))
    elif owner:
        q = q.where(AlertAssignment.owner == (user.username if owner == "me" else owner))
    if status:
        q = q.where(Alert.status == status)
    if category:
        q = q.where(Alert.category == category)
    if department:
        q = q.where(Subject.department == department)
    if user_id:
        q = q.where(Alert.user_id == user_id)
    severity = {'Low': 0, 'Medium': 1, 'High': 2, 'Critical': 3}
    workflow = {'open': 0, 'under_investigation': 1, 'closed': 2}
    columns = {
        'id': Alert.id, 'user_id': Alert.user_id, 'department': Subject.department,
        'start_time': Alert.start_time, 'peak_score': Alert.peak_score,
        'category': case(severity, value=Alert.category, else_=-1),
        'status': case(workflow, value=Alert.status, else_=-1),
        'owner': func.coalesce(AlertAssignment.owner, ''),
    }
    ordering = [(sort_by, sort_dir)] + ([(then_by, then_dir)] if then_by else [])
    if any(key == 'indicator_count' for key, _ in ordering):
        # JSON array length is not portable across the supported SQL backends.
        rows = db.execute(q.order_by(Alert.id.asc())).all()
        def value(row, key):
            alert, dept, assignment = row
            if key == 'owner':
                return assignment.owner if assignment else ''
            if key == 'indicator_count':
                return len(alert.breakdown or [])
            if key == 'department':
                return dept or ''
            if key == 'category':
                return severity.get(alert.category, -1)
            if key == 'status':
                return workflow.get(alert.status, -1)
            return getattr(alert, key)
        for key, direction in reversed(ordering):
            rows.sort(key=lambda row: value(row, key), reverse=direction == 'desc')
        rows = rows[:limit]
    else:
        expressions = [(columns[key].desc() if direction == 'desc' else columns[key].asc()) for key, direction in ordering]
        rows = db.execute(q.order_by(*expressions, Alert.id.asc()).limit(limit)).all()
    states = cases.detection_states(db, [a.id for a, _, _ in rows])
    verdicts = resolutions.current_for(db, [a.id for a, _, _ in rows])
    return [_alert_dict(a, d, assignment=assignment, detection_state=states.get(a.id), resolution=verdicts.get(a.id)) for a, d, assignment in rows]


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    sub = db.get(Subject, a.user_id)
    notes = db.scalars(select(CaseNote).where(CaseNote.alert_id == a.id).order_by(CaseNote.id)).all()
    audit(db, user, "view_alert", str(a.id), {"score": a.peak_score})  # REQ-10-01: reviewing the score
    db.commit()
    return {**_alert_dict(a, sub.department if sub else None, notes, cases.owners_for(db, [a.id]).get(a.id),
                         cases.detection_states(db, [a.id]).get(a.id), resolutions.current_for(db, [a.id]).get(a.id)),
            "resolution_history": resolutions.history_for(db, a.id),
            "open_escalation_id": db.scalar(select(Escalation.id).where(
                Escalation.alert_id == a.id, Escalation.status.notin_(["completed", "withdrawn"])))}


class StatusIn(BaseModel):
    status: str = Field(pattern="^(open|under_investigation|closed)$")
    outcome: str | None = None
    note: str | None = None
    reason: str | None = None


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


@router.patch("/alerts/{alert_id}")
def update_alert(alert_id: int, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    a = _case_or_404(db, alert_id)
    assignment = cases.require_owner(db, a, user)
    resolutions.transition(db, a, user, assignment, body.status, body.outcome, body.note, body.reason)
    db.commit()
    return _owned_alert_dict(db, a)


@router.post("/alerts/{alert_id}/notes", status_code=201)
def add_note(alert_id: int, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    a = _case_or_404(db, alert_id)
    cases.require_owner(db, a, user)
    n = CaseNote(alert_id=alert_id, author=user.username, note=body.note.strip())
    db.add(n)
    audit(db, user, "add_investigation_note", str(alert_id), {"length": len(body.note)})
    db.commit()
    return {"id": n.id, "author": n.author, "note": n.note, "created_at": _iso(n.created_at)}


@router.post("/alerts/{alert_id}/explain")
def explain(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    a = _case_or_404(db, alert_id)
    assignment = cases.require_owner(db, a, user)
    ok = ai.explain_alert(db, a)
    audit(db, user, "request_ai_explanation", str(a.id), {"ok": ok})
    db.commit()
    return {**_owned_alert_dict(db, a), "ai_available": ok}


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


class RuleIn(BaseModel):
    key: str = Field(min_length=1, max_length=48, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1, max_length=256, pattern=r"\S")
    value: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)


@router.get("/rules")
def get_rules(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return [{"key": r.key, "value": r.value, "default": config.DEFAULT_RULES[r.key][0] if r.key in config.DEFAULT_RULES else None,
             "built_in": r.key in config.DEFAULT_RULES,
             "description": r.description, "updated_by": r.updated_by, "updated_at": _iso(r.updated_at)}
            for r in db.scalars(select(RuleConfig).order_by(RuleConfig.key))]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.get(RuleConfig, body.key) is not None or body.key in config.DEFAULT_RULES:
        raise HTTPException(409, "A rule with this parameter already exists")
    row = RuleConfig(key=body.key, description=body.description.strip(), value=body.value,
                     updated_by=admin.username, updated_at=utcnow())
    db.add(row)
    audit(db, admin, "create_rule", body.key, {"description": row.description, "value": row.value})
    db.commit()
    return {"key": row.key, "description": row.description, "value": row.value, "built_in": False}


@router.delete("/rules/{key}")
def delete_rule(key: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    row = db.get(RuleConfig, key)
    if row is None:
        raise HTTPException(404, "Rule not found")
    if key in config.DEFAULT_RULES:
        raise HTTPException(409, "Built-in engine parameters cannot be removed")
    audit(db, admin, "delete_rule", key, {"description": row.description, "value": row.value})
    db.delete(row)
    db.commit()
    return {"deleted": key}


@router.put("/rules")
def update_rules(body: RulesIn, background: BackgroundTasks, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    known = {r.key for r in db.scalars(select(RuleConfig))}
    unknown = [k for k in body.values if k not in known]
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
    if any(key in config.DEFAULT_RULES for key in changes):
        reprocess_users(db)  # thresholds changed -> rescore everyone (REQ-07-04)
    return {"changed": changes}


@router.get("/mitre/mapping")
def mitre_mapping(user: User = Depends(require_staff)):
    return mitre.mapping_table()


# --------------------------------------------------------------------------- evaluation & audit (3.10)
@router.get("/evaluation/feedback")
def evaluation_feedback(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return resolutions.feedback(db)


@router.get("/evaluation/results")
def evaluation_results(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    run = db.scalar(select(EvaluationRun).order_by(EvaluationRun.id.desc()))
    if not run:
        raise HTTPException(404, "No evaluation has been run yet")
    return {"run_id": run.id, "run_by": run.run_by, **run.results}


@router.post("/evaluation/run")
def evaluation_run(threshold: float | None = Query(None, ge=1, le=100), db: Session = Depends(get_db),
                   user: User = Depends(require_admin)):
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
