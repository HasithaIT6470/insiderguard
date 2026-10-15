"""Advisory analyst-to-admin workflow; no enforcement or scoring side effects."""
import csv
import io
import unicodedata
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import cases, resolutions
from .database import get_db
from .models import Alert, EmployeeContact, Escalation, EscalationEvent, EscalationMessage, User, utcnow
from .security import audit, require_admin, require_analyst, require_staff

router = APIRouter(prefix="/escalations")
STATUSES = ("submitted", "acknowledged", "needs_info", "contacted", "completed", "withdrawn")
TERMINAL = ("completed", "withdrawn")
OVERDUE = ("submitted", "acknowledged", "needs_info")
Priority = Literal["low", "normal", "urgent"]
Recommendation = Literal["contact_user", "contact_supervisor", "access_review", "monitor_only", "training", "hr_referral", "other"]
Method = Literal["email", "phone", "in_person", "other"]


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str) and any(unicodedata.category(c).startswith("C") and c not in "\n\r\t" for c in value):
            raise ValueError("Control characters are not allowed")
        return value


class Filing(TextInput):
    alert_id: int = Field(gt=0)
    summary: str = Field(min_length=20, max_length=4000)
    recommendation: Recommendation
    recommendation_note: str = Field(default="", max_length=4000)
    priority: Priority = "normal"


class MessageInput(TextInput):
    message: str = Field(min_length=1, max_length=4000)


class ContactInput(TextInput):
    contact_method: Method
    summary: str = Field(min_length=1, max_length=4000)


class CompleteInput(TextInput):
    handling_note: str = Field(min_length=10, max_length=4000)


def iso(value):
    return value.isoformat() if value else None


def record_escalation_event(db, escalation, actor, action, from_status=None, *, silent=False):
    """Single status-history write point. Task 10 notification hooks belong here."""
    db.flush()
    event = EscalationEvent(escalation_id=escalation.id, actor=actor.username, role=actor.role,
                            action=action, from_status=from_status, to_status=escalation.status)
    db.add(event)
    db.flush()
    from .notifications import escalation_event
    escalation_event(db, escalation, event, silent=silent)
    return event


def visible_query(user):
    q = select(Escalation)
    return q if user.role == "admin" else q.where(Escalation.created_by == user.username)


def get_visible(db, escalation_id, user):
    row = db.scalar(visible_query(user).where(Escalation.id == escalation_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Escalation not found")
    return row


def overdue(row, now):
    return row.status in OVERDUE and row.created_at < now - timedelta(hours=24)


def serialize(row, now=None):
    now = now or utcnow()
    # Deliberate allowlist: contact summaries and directory fields never enter this API.
    keys = ("id", "alert_id", "user_id", "created_by", "priority", "summary", "recommendation",
            "recommendation_note", "case_status_at_filing", "snapshot", "status", "handled_by", "handling_note")
    return {k: getattr(row, k) for k in keys} | {
        "created_at": iso(row.created_at), "updated_at": iso(row.updated_at), "completed_at": iso(row.completed_at),
        "age_hours": round(max(0, (now - row.created_at).total_seconds() / 3600), 2), "overdue": overdue(row, now)}


@router.post("")
def create(body: Filing, db: Session = Depends(get_db), user: User = Depends(require_analyst)):
    alert = db.scalar(select(Alert).where(Alert.id == body.alert_id).with_for_update())
    if alert is None:
        raise HTTPException(404, "Case not found")
    cases.require_owner(db, alert, user)
    if db.scalar(select(Escalation.id).where(Escalation.alert_id == alert.id, Escalation.status.notin_(TERMINAL))):
        raise HTTPException(409, "This case already has an open escalation")
    verdict = resolutions.current_for(db, [alert.id]).get(alert.id)
    now = utcnow()
    row = Escalation(**body.model_dump(), user_id=alert.user_id, created_by=user.username,
                     case_status_at_filing=alert.status, status="submitted", created_at=now, updated_at=now,
                     snapshot={"peak_score": alert.peak_score, "category": alert.category,
                               "indicators": list(dict.fromkeys(i["name"] for i in alert.breakdown or [] if i.get("name"))),
                               "outcome": verdict.outcome if verdict else None, "filed_at": iso(now)})
    db.add(row)
    try:
        db.flush()
        record_escalation_event(db, row, user, "submitted")
        cases.record_event(db, alert, "escalated", user, {"escalation_id": row.id, "priority": row.priority})
        audit(db, user, "create_escalation", str(row.id), {"alert_id": alert.id, "priority": row.priority})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This case already has an open escalation") from None
    return serialize(row)


@router.get("")
def listing(status: str | None = None, priority: Priority | None = None, user_id: str | None = None,
            analyst: str | None = None, overdue: bool = False, search: str | None = None, format: Literal["json", "csv"] = "json",
            db: Session = Depends(get_db), user: User = Depends(require_staff)):
    if format == "csv" and user.role != "admin":
        raise HTTPException(403, "Only administrators can export escalations")
    q = visible_query(user)
    if search and search.strip():
        q = q.where(Escalation.user_id.icontains(search.strip(), autoescape=True))
    if status is not None:
        statuses = list(dict.fromkeys(s.strip() for s in status.split(',')))
        if any(s not in STATUSES for s in statuses):
            raise HTTPException(422, "Invalid escalation status")
        q = q.where(Escalation.status.in_(statuses))
    for field, value in ((Escalation.priority, priority), (Escalation.user_id, user_id), (Escalation.created_by, analyst)):
        if value:
            q = q.where(field == value)
    now = utcnow()
    if overdue:
        q = q.where(Escalation.status.in_(OVERDUE), Escalation.created_at < now - timedelta(hours=24))
    rows = db.scalars(q.order_by(case((Escalation.priority == "urgent", 0), (Escalation.priority == "normal", 1), else_=2), Escalation.created_at, Escalation.id)).all()
    result = [serialize(row, now) for row in rows]
    if format == "json":
        return result
    fields = ["id", "alert_id", "user_id", "created_by", "priority", "status", "handled_by", "created_at", "age_hours", "overdue", "recommendation", "summary", "handling_note"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fields, extrasaction="ignore")
    writer.writeheader()
    # Spreadsheet formula protection for user-entered text.
    for row in result:
        writer.writerow({k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v) for k, v in row.items()})
    audit(db, user, "export_escalations", detail={"rows": len(result)})
    db.commit()
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="escalations.csv"'})


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    visible = visible_query(user).where(Escalation.status.notin_(TERMINAL)).subquery()
    return {"open_count": db.scalar(select(func.count()).select_from(visible)),
            "overdue_count": db.scalar(select(func.count()).select_from(visible).where(
                visible.c.status.in_(OVERDUE), visible.c.created_at < utcnow() - timedelta(hours=24)))}


@router.get("/{escalation_id}")
def detail(escalation_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_visible(db, escalation_id, user)
    messages = db.scalars(select(EscalationMessage).where(EscalationMessage.escalation_id == row.id).order_by(EscalationMessage.id)).all()
    events = db.scalars(select(EscalationEvent).where(EscalationEvent.escalation_id == row.id).order_by(EscalationEvent.id)).all()
    return serialize(row) | {"messages": [{"id": m.id, "author": m.author, "role": m.role, "message": m.message, "created_at": iso(m.created_at)} for m in messages],
                             "timeline": [{"id": e.id, "actor": e.actor, "role": e.role, "action": e.action, "from_status": e.from_status, "to_status": e.to_status, "created_at": iso(e.created_at)} for e in events]}


def transition(db, row, user, to_status, allowed, action, values=None):
    old = row.status
    if old not in allowed:
        raise HTTPException(409, f"Cannot {action.replace('_', ' ')} an escalation while {old}")
    if user.role == "admin" and row.handled_by and row.handled_by != user.username:
        raise HTTPException(409, f"This escalation is being handled by {row.handled_by}")
    updates = {"status": to_status, "updated_at": utcnow(), **(values or {})}
    # Compare-and-set also enforces races on SQLite, where FOR UPDATE is ignored.
    changed = db.execute(update(Escalation).where(Escalation.id == row.id, Escalation.status == old,
                         Escalation.handled_by == row.handled_by).values(**updates), execution_options={"synchronize_session": False}).rowcount
    if changed != 1:
        db.rollback()
        current = db.get(Escalation, row.id)
        raise HTTPException(409, f"Escalation changed; handled by {current.handled_by or 'another user'}. Reload and try again")
    db.refresh(row)
    record_escalation_event(db, row, user, action, old)
    audit(db, user, action, str(row.id), {"from": old, "to": to_status})


@router.post("/{escalation_id}/acknowledge")
def acknowledge(escalation_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = get_visible(db, escalation_id, user)
    if row.handled_by:
        raise HTTPException(409, f"Already acknowledged by {row.handled_by}")
    transition(db, row, user, "acknowledged", ("submitted",), "acknowledge_escalation", {"handled_by": user.username})
    db.commit()
    return serialize(row)


def add_message(db, row, user, message):
    db.add(EscalationMessage(escalation_id=row.id, author=user.username, role=user.role, message=message))


@router.post("/{escalation_id}/request-info")
def request_info(escalation_id: int, body: MessageInput, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = get_visible(db, escalation_id, user)
    transition(db, row, user, "needs_info", ("acknowledged", "needs_info", "contacted"), "request_escalation_info")
    add_message(db, row, user, body.message)
    db.commit()
    return serialize(row)


@router.post("/{escalation_id}/messages")
def message(escalation_id: int, body: MessageInput, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_visible(db, escalation_id, user)
    if user.username != (row.created_by if user.role == "analyst" else row.handled_by):
        raise HTTPException(403, "Only the filing analyst or handling admin may reply")
    if row.status in TERMINAL:
        raise HTTPException(409, "Cannot reply to a completed or withdrawn escalation")
    transition(db, row, user, "acknowledged" if user.role == "analyst" and row.status == "needs_info" else row.status,
               STATUSES, "reply_escalation")
    add_message(db, row, user, body.message)
    db.commit()
    return serialize(row)


@router.post("/{escalation_id}/contacted")
def contacted(escalation_id: int, body: ContactInput, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = get_visible(db, escalation_id, user)
    transition(db, row, user, "contacted", ("acknowledged", "needs_info", "contacted"), "contact_escalation", {"contact_method": body.contact_method})
    # A contact can precede directory registration. It becomes visible when a profile is created.
    db.add(EmployeeContact(user_id=row.user_id, contacted_by=user.username, method=body.contact_method,
                           summary=body.summary, escalation_id=row.id))
    db.commit()
    return serialize(row)


@router.post("/{escalation_id}/complete")
def complete(escalation_id: int, body: CompleteInput, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = get_visible(db, escalation_id, user)
    transition(db, row, user, "completed", ("acknowledged", "needs_info", "contacted"), "complete_escalation",
               {"handling_note": body.handling_note, "completed_at": utcnow()})
    db.commit()
    return serialize(row)


@router.post("/{escalation_id}/withdraw")
def withdraw(escalation_id: int, db: Session = Depends(get_db), user: User = Depends(require_analyst)):
    row = get_visible(db, escalation_id, user)
    transition(db, row, user, "withdrawn", ("submitted",), "withdraw_escalation")
    db.commit()
    return serialize(row)
