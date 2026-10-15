"""Transactional notification delivery and own-recipient inbox operations."""
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import Alert, AlertAssignment, Notification, NotificationMaintenance, NotificationReceipt, User, utcnow
from .security import audit, get_current_user

router = APIRouter(prefix="/notifications")


def ensure_outer_transaction(db):
    # Python sqlite3's legacy mode doesn't BEGIN on SELECT. Without this, a
    # first SAVEPOINT can commit independently of the caller's transaction.
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


def notify(db, recipients, type, title, message, link, *, alert_id=None, escalation_id=None,
           severity="info", silent=False, dedupe_key=None):
    if silent or db.info.get("notifications_silent", False):
        return []
    key = dedupe_key or (f"alert:{alert_id}" if alert_id is not None else f"escalation:{escalation_id}" if escalation_id is not None else uuid4().hex)
    recipients = [recipients] if isinstance(recipients, str) else list(recipients)
    existing_users = set(db.scalars(select(User.username).where(User.username.in_(set(recipients)))))
    if existing_users:
        ensure_outer_transaction(db)
    created = []
    for recipient in sorted(existing_users):
        try:
            with db.begin_nested():
                db.add(NotificationReceipt(recipient=recipient, type=type, delivery_key=key))
                db.flush()
                row = Notification(recipient=recipient, type=type, title=title, message=message, link=link,
                                   alert_id=alert_id, escalation_id=escalation_id, severity=severity)
                db.add(row); db.flush()
                audit(db, "system", "create_notification", str(row.id), {"recipient": recipient, "type": type})
                created.append(row)
        except IntegrityError:
            pass  # Another transaction already delivered this logical event.
    return created


def notify_role(db, role, type, title, message, link, *, exclude=None, **refs):
    excluded = {exclude} if isinstance(exclude, str) else set(exclude or [])
    recipients = [name for name in db.scalars(select(User.username).where(User.role == role)) if name not in excluded]
    return notify(db, recipients, type, title, message, link, **refs)


def case_event(db, alert, event, *, silent=False):
    detail = event.detail or {}
    refs = {"alert_id": alert.id, "dedupe_key": f"case_event:{event.id}", "silent": silent}
    case = f"Case #{alert.id}"
    if event.action in ("assigned", "reassigned"):
        owner, previous = detail.get("to"), detail.get("from")
        if owner and owner != previous:
            notify(db, [owner], "case_assigned", f"{case} is now yours", f"You are the owner of {case}.", f"/my-cases/{alert.id}", **refs)
        if previous and owner != previous:
            notify(db, [previous], "case_reassigned", f"{case} ownership changed", f"An administrator moved {case} to another owner.", f"/alerts/{alert.id}", **refs)
    elif event.action == "claimed" and event.actor_role == "analyst":
        notify_role(db, "admin", "case_claimed", f"{case} claimed", f"An analyst claimed {case}.", f"/alerts/{alert.id}", **refs)
    elif event.action == "resolved" and event.actor_role == "analyst":
        outcome = {"true_positive": "True positive", "false_positive": "False positive", "benign_explained": "Benign/explained"}.get(detail.get("outcome"), "Outcome recorded")
        notify_role(db, "admin", "case_closed", f"{case} closed", f"An analyst closed {case}. Outcome: {outcome}.", f"/alerts/{alert.id}", **refs)
    elif event.action == "reopened" and event.actor_role == "analyst":
        notify_role(db, "admin", "case_reopened", f"{case} reopened", f"An analyst reopened {case}.", f"/alerts/{alert.id}", **refs)
    elif event.action == "released":
        notify_role(db, "admin", "case_released", f"{case} returned to the queue", f"{case} is available for an analyst to claim.", f"/alerts/{alert.id}", **refs)


def escalation_event(db, escalation, event, *, silent=False):
    refs = {"alert_id": escalation.alert_id, "escalation_id": escalation.id,
            "dedupe_key": f"escalation_event:{event.id}", "silent": silent}
    link = f"/escalations/{escalation.id}"
    label = f"Escalation #{escalation.id}"
    if event.action == "submitted":
        notify_role(db, "admin", "escalation_submitted", f"{label} submitted", f"An analyst escalated Case #{escalation.alert_id}.", link, **refs)
    elif event.action == "reply_escalation" and event.role == "analyst":
        notify_role(db, "admin", "escalation_reply", f"New reply on {label}", f"The filing analyst replied on {label}.", link, **refs)
    elif event.to_status == "withdrawn":
        notify_role(db, "admin", "escalation_withdrawn", f"{label} withdrawn", f"The filing analyst withdrew {label}.", link, **refs)
    elif event.to_status != event.from_status and event.to_status in ("acknowledged", "needs_info", "contacted", "completed") and event.role == "admin":
        labels = {"acknowledged": "acknowledged", "needs_info": "needs more information", "contacted": "contact logged", "completed": "handled"}
        notify(db, [escalation.created_by], f"escalation_{event.to_status}", f"{label}: {labels[event.to_status]}",
               f"An administrator updated {label} for Case #{escalation.alert_id}.", link,
               severity="warning" if event.to_status == "needs_info" else "info", **refs)


def new_alerts(db, alerts, *, silent=False):
    eligible = [a for a in alerts if a.category in ("High", "Critical") and a.status != "closed"]
    owners = set(db.scalars(select(AlertAssignment.alert_id).where(AlertAssignment.alert_id.in_([a.id for a in eligible]))))
    eligible = [a for a in eligible if a.id not in owners]
    if len(eligible) > 10:
        notify_role(db, "admin", "alert_batch", f"{len(eligible)} new High/Critical alerts",
                    f"{len(eligible)} new High/Critical alerts are unassigned. Review the alert queue.", "/alerts?owner=unassigned",
                    severity="critical" if any(a.category == "Critical" for a in eligible) else "warning",
                    dedupe_key="batch:" + sha256(','.join(str(a.id) for a in sorted(eligible, key=lambda a: a.id)).encode()).hexdigest(), silent=silent)
    else:
        for alert in eligible:
            notify_role(db, "admin", "alert_new", f"New {alert.category} alert: Case #{alert.id}",
                        f"Case #{alert.id} is unassigned and ready for review.", f"/alerts/{alert.id}", alert_id=alert.id,
                        severity="critical" if alert.category == "Critical" else "warning", silent=silent)


def lazy_reminders(db, user):
    if user.role != "admin":
        return
    alerts = db.scalars(select(Alert).outerjoin(AlertAssignment, AlertAssignment.alert_id == Alert.id).where(
        AlertAssignment.id.is_(None), Alert.status != "closed", Alert.category.in_(["High", "Critical"]),
        Alert.created_at < utcnow() - timedelta(hours=24))).all()
    for alert in alerts:
        notify_role(db, "admin", "alert_unassigned_24h", f"Case #{alert.id} is still unassigned",
                    f"High/Critical Case #{alert.id} has been unassigned for more than 24 hours.", f"/alerts/{alert.id}",
                    alert_id=alert.id, severity="warning")


def purge_old(db):
    now = utcnow()
    row = db.get(NotificationMaintenance, "retention")
    if row is None:
        ensure_outer_transaction(db)
        try:
            with db.begin_nested():
                db.add(NotificationMaintenance(key="retention", last_run=now - timedelta(hours=2)))
                db.flush()
        except IntegrityError:
            pass
    claimed = db.execute(update(NotificationMaintenance).where(NotificationMaintenance.key == "retention",
                         NotificationMaintenance.last_run <= now - timedelta(hours=1)).values(last_run=now)).rowcount
    if claimed:
        removed = db.execute(delete(Notification).where(Notification.created_at < now - timedelta(days=30))).rowcount
        audit(db, "system", "purge_notifications", detail={"deleted": removed})


def serialize(row):
    return {k: (getattr(row, k).isoformat() if getattr(row, k) else None) if k in ("created_at", "read_at") else getattr(row, k)
            for k in ("id", "type", "title", "message", "link", "alert_id", "escalation_id", "severity", "created_at", "read_at")}


@router.get("")
def listing(unread: bool = False, type: str | None = None, limit: int = Query(50, ge=1, le=100),
            before_id: int | None = Query(None, gt=0), search: str | None = None,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lazy_reminders(db, user); db.commit()
    q = select(Notification).where(Notification.recipient == user.username)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    if before_id:
        q = q.where(Notification.id < before_id)
    if type:
        if type in ("cases", "escalations", "alerts"):
            q = q.where(Notification.type.startswith({"cases": "case_", "escalations": "escalation_", "alerts": "alert_"}[type], autoescape=True))
        else:
            q = q.where(Notification.type == type)
    if search and search.strip():
        q = q.where(Notification.title.icontains(search.strip(), autoescape=True) | Notification.message.icontains(search.strip(), autoescape=True))
    return [serialize(row) for row in db.scalars(q.order_by(Notification.id.desc()).limit(limit))]


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    purge_old(db); lazy_reminders(db, user); db.commit()
    return {"unread_count": db.scalar(select(func.count()).select_from(Notification).where(Notification.recipient == user.username, Notification.read_at.is_(None)))}


def own_row(db, notification_id, user):
    row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.recipient == user.username))
    if row is None:
        raise HTTPException(404, "Notification not found")
    return row


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lazy_reminders(db, user)
    count = db.execute(update(Notification).where(Notification.recipient == user.username, Notification.read_at.is_(None)).values(read_at=utcnow())).rowcount
    audit(db, user, "read_all_notifications", detail={"count": count}); db.commit()
    return {"updated": count}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = own_row(db, notification_id, user)
    row.read_at = row.read_at or utcnow()
    audit(db, user, "read_notification", str(row.id)); db.commit()
    return serialize(row)


@router.post("/{notification_id}/unread")
def mark_unread(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = own_row(db, notification_id, user)
    row.read_at = None
    audit(db, user, "unread_notification", str(row.id)); db.commit()
    return serialize(row)


@router.delete("/{notification_id}")
def dismiss(notification_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = own_row(db, notification_id, user)
    db.delete(row); audit(db, user, "dismiss_notification", str(notification_id)); db.commit()
    return {"dismissed": notification_id}
