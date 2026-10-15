"""Case ownership and history. All writes participate in the caller's transaction."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from .models import Alert, AlertAssignment, AlertResolution, CaseEvent, User, utcnow
from .security import audit


def record_event(db, alert, action, actor, detail=None, *, silent=False):
    """Single case-event write point; future notification hooks belong here."""
    db.flush()  # New alerts need their persistent ID before the event is inserted.
    username = actor.username if isinstance(actor, User) else str(actor)
    role = actor.role if isinstance(actor, User) else "system"
    event = CaseEvent(alert_id=alert.id, action=action, actor=username, actor_role=role, detail=detail or {})
    db.add(event)
    db.flush()
    from .notifications import case_event
    case_event(db, alert, event, silent=silent)
    return event


def owners_for(db, alert_ids):
    """Bulk map from alert ID to its assignment, without per-alert queries."""
    ids = list(alert_ids)
    if not ids:
        return {}
    return {a.alert_id: a for a in db.scalars(select(AlertAssignment).where(AlertAssignment.alert_id.in_(ids)))}


def get_owner(db, alert_id):
    return db.scalar(select(AlertAssignment.owner).where(AlertAssignment.alert_id == alert_id))


def require_owner(db, alert, user):
    if user.role == "admin":
        raise HTTPException(403, "Administrators have read-only access to case status")
    owner = db.scalar(select(AlertAssignment).where(AlertAssignment.alert_id == alert.id).with_for_update())
    if owner is None:
        raise HTTPException(409, "Claim this case first")
    if owner.owner != user.username:
        raise HTTPException(403, "Only the case owner can change this case")
    return owner


def age_hours(alert, now=None):
    return round(max(0.0, ((now or utcnow()) - alert.start_time).total_seconds() / 3600), 2)


def summarize(alerts, now=None):
    now = now or utcnow()
    active = [a for a in alerts if a.status != "closed"]
    return {"total": len(alerts), **{s: sum(a.status == s for a in alerts)
                                    for s in ("open", "under_investigation", "closed")},
            "by_category": {c: sum(a.category == c for a in alerts) for c in ("Low", "Medium", "High", "Critical")},
            "oldest_open_age_hours": max((age_hours(a, now) for a in active), default=None)}


def workload(db):
    now = utcnow()
    rows = db.execute(select(Alert, AlertAssignment.owner).join(AlertAssignment, AlertAssignment.alert_id == Alert.id)).all()
    grouped = {}
    for alert, owner in rows:
        grouped.setdefault(owner, []).append(alert)
    # Most recent actual closing transition, so later reassignment doesn't change closure time.
    closed_at = {}
    for event in db.scalars(select(CaseEvent).where(CaseEvent.action == "status_changed").order_by(CaseEvent.id)):
        if event.detail.get("to") == "closed":
            closed_at[event.alert_id] = event.created_at
    for resolution in db.scalars(select(AlertResolution).where(AlertResolution.reopened_at.is_(None)).order_by(AlertResolution.id)):
        closed_at[resolution.alert_id] = resolution.resolved_at
    result = []
    for analyst in db.scalars(select(User).where(User.role == "analyst").order_by(User.username)):
        alerts = grouped.get(analyst.username, [])
        summary = summarize(alerts, now)
        result.append({"username": analyst.username, "open": summary["open"],
                       "under_investigation": summary["under_investigation"], "closed_total": summary["closed"],
                       "closed_last_7_days": sum(a.status == "closed" and
                           closed_at.get(a.id, a.updated_at) >= now - timedelta(days=7) for a in alerts),
                       "oldest_open_age_hours": summary["oldest_open_age_hours"],
                       **{c.lower(): sum(a.category == c and a.status != "closed" for a in alerts)
                          for c in ("Critical", "High")}})
    return result


def release_assignment(db, alert, assignment, actor, reason):
    old_status = alert.status
    if alert.status == "under_investigation":
        alert.status = "open"
    alert.updated_at = utcnow()
    detail = {"owner": assignment.owner, "reason": reason, "from": old_status, "to": alert.status}
    db.delete(assignment)
    record_event(db, alert, "released", actor, detail)
    audit(db, actor, "release_case", str(alert.id), detail)


def release_account_cases(db, username, actor):
    rows = db.execute(select(Alert, AlertAssignment).join(AlertAssignment, AlertAssignment.alert_id == Alert.id)
                      .where(AlertAssignment.owner == username, Alert.status != "closed").with_for_update()).all()
    for alert, assignment in rows:
        release_assignment(db, alert, assignment, actor, "owner account deleted")
    return len(rows)


def detection_states(db, alert_ids):
    states = {}
    ids = list(alert_ids)
    if ids:
        for event in db.scalars(select(CaseEvent).where(CaseEvent.alert_id.in_(ids),
                               CaseEvent.action.in_(["no_longer_detected", "redetected"]))
                               .order_by(CaseEvent.id)):
            states[event.alert_id] = event.action
    return states
