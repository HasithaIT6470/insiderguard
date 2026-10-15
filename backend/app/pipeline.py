"""Persistence glue: config loading, ingestion, and (re)processing of users through the engines."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from . import cases, config
from .engine import (
    build_series,
    categorize,
    compute_baseline,
    detect_user,
    incidents_from_series,
)
from .models import (
    Alert,
    Baseline,
    CaseNote,
    CaseEvent,
    Detection,
    Event,
    Honeytoken,
    ParseError,
    RiskPoint,
    RuleConfig,
    Subject,
    utcnow,
)
from .normalize import normalize_record
from .security import audit


# --------------------------------------------------------------------------- configuration
def seed_rule_config(db: Session) -> None:
    existing = {r.key for r in db.scalars(select(RuleConfig))}
    for key, (value, desc) in config.DEFAULT_RULES.items():
        if key not in existing:
            db.add(RuleConfig(key=key, value=float(value), description=desc, updated_by="system"))
    db.commit()


def load_config(db: Session) -> dict:
    cfg = {k: float(v[0]) for k, v in config.DEFAULT_RULES.items()}
    for row in db.scalars(select(RuleConfig)):
        if row.key in cfg:
            cfg[row.key] = float(row.value)
    return cfg


# --------------------------------------------------------------------------- ingestion
def ingest_records(db: Session, records: list, source: str = "api") -> dict:
    """Validate + normalize + store. Returns {accepted, rejected, errors, affected_users}."""
    good: list[dict] = []
    errors: list[dict] = []
    for idx, raw in enumerate(records):
        rec, errs = normalize_record(raw)
        if errs:
            row_ref = str(idx + 1)
            errors.append({"row": idx + 1, "errors": errs})
            db.add(
                ParseError(
                    source=source,
                    row_ref=row_ref,
                    raw=json.dumps(raw, default=str)[:2000],
                    errors=errs,
                )
            )
        else:
            good.append(rec)

    affected: set[str] = set()
    if good:
        known = {s.user_id: s for s in db.scalars(select(Subject).where(Subject.user_id.in_({g["user_id"] for g in good})))}
        for g in good:
            sub = known.get(g["user_id"])
            if sub is None:
                sub = Subject(user_id=g["user_id"], department=g["department"] or "Unknown",
                              first_seen=g["timestamp"], last_seen=g["timestamp"], event_count=0)
                db.add(sub)
                known[g["user_id"]] = sub
            if g["department"] and sub.department in (None, "Unknown"):
                sub.department = g["department"]
            sub.event_count = (sub.event_count or 0) + 1
            sub.first_seen = min(sub.first_seen or g["timestamp"], g["timestamp"])
            sub.last_seen = max(sub.last_seen or g["timestamp"], g["timestamp"])
            affected.add(g["user_id"])
            g["department"] = sub.department
            g["source"] = source
        for start in range(0, len(good), 5000):
            db.execute(insert(Event), good[start: start + 5000])
    db.commit()
    return {
        "accepted": len(good),
        "rejected": len(errors),
        "errors": errors[:200],
        "errors_truncated": len(errors) > 200,
        "affected_users": sorted(affected),
    }


# --------------------------------------------------------------------------- processing
def _process_user(db: Session, uid: str, cfg: dict, honey: set[str]) -> None:
    rows = db.execute(
        select(Event.id, Event.user_id, Event.timestamp, Event.event_type, Event.resource, Event.resource_type,
               Event.device_id, Event.result, Event.volume_mb)
        .where(Event.user_id == uid)
        .order_by(Event.timestamp, Event.id)
    ).all()
    db.execute(delete(Detection).where(Detection.user_id == uid))
    db.execute(delete(RiskPoint).where(RiskPoint.user_id == uid))
    if not rows:
        return
    events = [r._asdict() for r in rows]
    df = pd.DataFrame(events)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["volume_mb"] = df["volume_mb"].fillna(0.0)

    baseline = compute_baseline(df, cfg)
    row = db.get(Baseline, uid) or Baseline(user_id=uid)
    row.status = baseline["status"]
    row.computed_at = utcnow()
    row.window_start = datetime.fromisoformat(baseline["window_start"])
    row.window_end = datetime.fromisoformat(baseline["window_end"])
    row.event_count = baseline["event_count"]
    row.stats = {k: v for k, v in baseline.items() if k not in ("status", "window_start", "window_end", "event_count")}
    db.merge(row)
    sub = db.get(Subject, uid)
    if sub:
        sub.baseline_status = baseline["status"]
        sub.event_count = len(events)
        sub.first_seen, sub.last_seen = events[0]["timestamp"], events[-1]["timestamp"]

    inds = detect_user(events, baseline, honey, cfg)
    if inds:
        db.execute(
            insert(Detection),
            [
                {"user_id": uid, "event_id": i.event_id, "time": i.time, "source": i.source,
                 "category": i.category, "name": i.name, "weight": i.weight, "detail": i.detail}
                for i in inds
            ],
        )

    series = build_series(inds, "hybrid", cfg)
    prev = None
    points = []
    for t, score, breakdown in series:
        if prev is None or score != prev:
            points.append({"user_id": uid, "time": t, "score": score, "category": categorize(score, cfg),
                           "breakdown": breakdown})
        prev = score
    if points:
        db.execute(insert(RiskPoint), points)

    _sync_alerts(db, uid, incidents_from_series(series, cfg), cfg)


def _sync_alerts(db: Session, uid: str, incidents: list[dict], cfg: dict) -> None:
    """Upsert alerts keyed by (user, incident start) so case status/notes/narratives survive re-scoring."""
    existing = {a.start_time: a for a in db.scalars(select(Alert).where(Alert.user_id == uid))}
    assignments = cases.owners_for(db, [a.id for a in existing.values()])
    history_ids = set(db.scalars(select(CaseEvent.alert_id).where(
        CaseEvent.alert_id.in_([a.id for a in existing.values()])).distinct()))
    states = cases.detection_states(db, [a.id for a in existing.values()])
    seen = set()
    shifted = {}
    exact_starts = {inc["start_time"] for inc in incidents}
    gap = timedelta(hours=float(cfg["score_window_hours"]))
    for inc in incidents:
        alert = existing.get(inc["start_time"])
        if alert is None:
            # Keep the original case identity/evidence when its incident start shifts.
            # A nearby replacement must not create a duplicate investigation.
            candidates = [a for start, a in existing.items() if a.id not in seen and a.id not in shifted and start not in exact_starts
                          and (a.id in assignments or a.id in history_ids)
                          and inc["start_time"] <= a.last_time + gap and inc["last_time"] >= a.start_time - gap]
            if candidates:
                alert = min(candidates, key=lambda a: (abs((a.start_time - inc["start_time"]).total_seconds()), a.id))
                shifted[alert.id] = {"reason": "incident start shifted", "from": alert.start_time.isoformat(),
                                     "to": inc["start_time"].isoformat()}
                continue
        if alert is None:
            alert = Alert(user_id=uid, start_time=inc["start_time"], status="open", narrative_status="none")
            db.add(alert)
        if states.get(alert.id) == "no_longer_detected":
            cases.record_event(db, alert, "redetected", "system")
            audit(db, "system", "case_redetected", str(alert.id))
        alert.last_time = inc["last_time"]
        alert.peak_score = inc["peak_score"]
        alert.category = categorize(inc["peak_score"], cfg)
        alert.breakdown = inc["breakdown"]
        alert.updated_at = utcnow()
        db.flush()
        seen.add(alert.id)
    for alert in existing.values():
        if alert.id in seen:
            continue
        if alert.id in assignments:
            if states.get(alert.id) != "no_longer_detected":
                detail = shifted.get(alert.id, {})
                cases.record_event(db, alert, "no_longer_detected", "system", detail)
                audit(db, "system", "case_no_longer_detected", str(alert.id), detail)
        elif alert.id not in history_ids and alert.status == "open" and not alert.narrative:
            has_notes = db.scalar(select(func.count()).select_from(CaseNote).where(CaseNote.alert_id == alert.id))
            if not has_notes:
                db.delete(alert)


def reprocess_users(db: Session, user_ids: list[str] | None = None) -> dict:
    cfg = load_config(db)
    honey = {h.resource for h in db.scalars(select(Honeytoken).where(Honeytoken.active.is_(True)))}
    if user_ids is None:
        user_ids = [r[0] for r in db.execute(select(Subject.user_id))]
    for uid in user_ids:
        _process_user(db, uid, cfg, honey)
        db.flush()
    db.commit()
    return {"users_processed": len(user_ids)}


def dataset_end(db: Session) -> datetime | None:
    return db.scalar(select(func.max(Event.timestamp)))


def current_risk(db: Session, cfg: dict | None = None) -> dict[str, dict]:
    """Current risk per user = peak hybrid score within the risk horizon of the newest data."""
    cfg = cfg or load_config(db)
    end = dataset_end(db)
    if end is None:
        return {}
    since = end - timedelta(days=float(cfg["risk_horizon_days"]))
    best: dict[str, RiskPoint] = {}
    for p in db.scalars(select(RiskPoint).where(RiskPoint.time >= since)):
        if p.user_id not in best or p.score > best[p.user_id].score:
            best[p.user_id] = p
    return {
        uid: {"score": p.score, "category": categorize(p.score, cfg), "as_of": p.time, "breakdown": p.breakdown}
        for uid, p in best.items()
    }
