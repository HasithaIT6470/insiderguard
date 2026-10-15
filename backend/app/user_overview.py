"""Staff analytics: explicit non-personal serializers shared by both roles."""
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import cases, resolutions
from .database import get_db
from .models import Alert, Baseline, CaseNote, EmployeeProfile, Event, Escalation, RiskPoint, Subject, User, utcnow
from .pipeline import current_risk, dataset_end, load_config
from .security import audit, require_staff

router = APIRouter(prefix="/users")


def iso(value):
    return value.isoformat() if value else None


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    subjects = db.scalars(select(Subject)).all()
    risk = current_risk(db, load_config(db))
    distribution = {c: 0 for c in ("Low", "Medium", "High", "Critical")}
    ranked = []
    for subject in subjects:
        r = risk.get(subject.user_id, {})
        category = r.get("category", "Low")
        distribution[category] += 1
        ranked.append({"user_id": subject.user_id, "department": subject.department,
                       "risk_score": r.get("score", 0), "risk_category": category})
    volumes = dict(db.execute(select(Subject.department, func.count(Event.id)).join(Event, Event.user_id == Subject.user_id).group_by(Subject.department)).all())
    return {"users_by_department": dict(Counter(s.department for s in subjects)),
            "risk_distribution": distribution, "baseline_status_counts": dict(Counter(s.baseline_status for s in subjects)),
            "event_volume_by_department": volumes,
            "top_risky_users": sorted(ranked, key=lambda r: (-r["risk_score"], r["user_id"]))[:5]}


@router.get("/{user_id}/overview")
def overview(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    subject = db.get(Subject, user_id)
    # Query only the identity, never load a personal field in this staff endpoint.
    has_profile = db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id)) is not None
    if subject is None and not has_profile:
        raise HTTPException(404, "Unknown user")
    risk = current_risk(db, load_config(db)).get(user_id, {})
    points = db.scalars(select(RiskPoint).where(RiskPoint.user_id == user_id).order_by(RiskPoint.time)).all()
    trend = {}
    for point in points:
        day = point.time.date().isoformat()
        trend[day] = max(trend.get(day, 0), point.score)
    end = dataset_end(db) or utcnow()
    last_day = end.date()
    thirty_start = end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)
    week_start = last_day - timedelta(days=6)
    heatmap = [[0] * 24 for _ in range(7)]
    types, devices = Counter(), {}
    totals = {"download_mb": 0.0, "file_access": 0}
    events = db.execute(select(Event.timestamp, Event.event_type, Event.volume_mb, Event.device_id).where(Event.user_id == user_id)).all()
    for timestamp, event_type, volume, device_id in events:
        types[event_type] += 1
        if thirty_start <= timestamp <= end:
            heatmap[timestamp.weekday()][timestamp.hour] += 1
        if week_start <= timestamp.date() <= last_day:
            if event_type == "download":
                totals["download_mb"] += volume or 0
            elif event_type == "file_access":
                totals["file_access"] += 1
        if device_id:
            device = devices.setdefault(device_id, {"name": device_id, "first_seen": timestamp, "count": 0})
            device["first_seen"] = min(device["first_seen"], timestamp)
            device["count"] += 1
    baseline = db.get(Baseline, user_id)
    base_stats = (baseline.stats or {}) if baseline else {}
    comparisons = {}
    for metric, base_key in (("download_mb", "daily_download_mb"), ("file_access", "daily_access")):
        b = base_stats.get(base_key, {})
        comparisons[metric] = {"recent_daily_average": round(totals[metric] / 7, 2), "baseline_mean": b.get("mean"), "baseline_std": b.get("std")}
    alerts = db.scalars(select(Alert).where(Alert.user_id == user_id).order_by(Alert.start_time.desc())).all()
    ids = [a.id for a in alerts]
    assignments, verdicts = cases.owners_for(db, ids), resolutions.current_for(db, ids)
    notes = db.scalars(select(CaseNote).where(CaseNote.alert_id.in_(ids)).order_by(CaseNote.created_at.desc(), CaseNote.id.desc())).all() if ids else []
    audit(db, user, "view_user_overview", user_id)
    db.commit()
    return {"user_id": user_id, "department": subject.department if subject else None,
            "baseline_status": subject.baseline_status if subject else "pending",
            "first_seen": iso(subject.first_seen) if subject else None, "last_seen": iso(subject.last_seen) if subject else None,
            "event_count": subject.event_count if subject else 0, "has_profile": has_profile,
            "current_risk": {"score": risk.get("score", 0), "category": risk.get("category", "Low"), "as_of": iso(risk.get("as_of"))},
            "risk_trend": [{"date": d, "score": score} for d, score in sorted(trend.items())],
            "activity_heatmap": heatmap, "activity_window": {"start": iso(thirty_start), "end": iso(end)},
            "event_type_breakdown": dict(types), "baseline_vs_recent": comparisons,
            "recent_window": {"start": week_start.isoformat(), "end": last_day.isoformat(), "days": 7},
            "devices": [{**d, "first_seen": iso(d["first_seen"])} for d in sorted(devices.values(), key=lambda d: d["name"])],
            "case_history": [{"id": a.id, "status": a.status, "owner": assignments[a.id].owner if a.id in assignments else None,
                              "outcome": verdicts[a.id].outcome if a.id in verdicts else None, "peak_score": a.peak_score,
                              "category": a.category, "start_time": iso(a.start_time)} for a in alerts],
            "case_notes": [{"id": n.id, "alert_id": n.alert_id, "author": n.author, "note": n.note, "created_at": iso(n.created_at)} for n in notes],
            "escalations": [{"id": e.id, "status": e.status, "priority": e.priority, "created_by": e.created_by,
                             "created_at": iso(e.created_at), "handling_note": e.handling_note}
                            for e in db.scalars(select(Escalation).where(Escalation.user_id == user_id).order_by(Escalation.created_at.desc()))]}
