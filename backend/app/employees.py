"""Admin directory. Personal fields never enter staff serializers or audit details."""
import csv
import io
import re
import unicodedata
from collections import Counter
from datetime import date

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import EmployeeContact, EmployeeProfile, Subject, User, UserDirectoryRemoval, utcnow
from .security import audit, require_admin

router = APIRouter(prefix="/admin/employees")
STATUSES = ("active", "on_leave", "contractor", "offboarded")
FIELDS = {"full_name": 160, "email": 254, "phone": 20, "job_title": 160,
          "supervisor_name": 160, "supervisor_email": 254, "supervisor_phone": 20,
          "employment_status": 16, "start_date": None, "location": 160, "contact_notes": 4000}
CSV_FIELDS = ["user_id", *[k for k in FIELDS if k != "contact_notes"]]


def text(value, field, maximum):
    if not isinstance(value, str):
        raise ValueError(f"{field}: must be text")
    if any(unicodedata.category(c).startswith("C") for c in value):
        raise ValueError(f"{field}: control characters are not allowed")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{field}: maximum {maximum} characters")
    return value


def validate(payload, creating=False):
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")
    allowed = set(FIELDS) | ({"user_id"} if creating else set())
    if set(payload) - allowed:
        raise ValueError("Unknown or immutable field")
    out = {}
    if creating:
        uid = text(payload.get("user_id", ""), "user_id", 64)
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", uid):
            raise ValueError("user_id: use 1–64 letters, digits, underscore, dot, @ or hyphen")
        out["user_id"] = uid
    for field, maximum in FIELDS.items():
        if field not in payload:
            continue
        raw = payload[field]
        if field == "start_date":
            try:
                value = text(raw, field, 10) if raw is not None else ""
                out[field] = date.fromisoformat(value) if value else None
            except ValueError:
                raise ValueError("start_date: expected YYYY-MM-DD") from None
            continue
        value = text(raw, field, maximum)
        if field.endswith("email") and value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError(f"{field}: invalid email address")
        if field.endswith("phone") and value and not (7 <= len(value) <= 20 and re.fullmatch(r"[0-9+ ()-]+", value) and re.search(r"[0-9]", value)):
            raise ValueError(f"{field}: use 7–20 digits and + space - ( )")
        if field == "employment_status" and value not in STATUSES:
            raise ValueError("employment_status: expected active, on_leave, contractor or offboarded")
        out[field] = value
    return out


def validated(payload, creating=False):
    try:
        return validate(payload, creating)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def find(db, user_id):
    row = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))
    if row is None:
        raise HTTPException(404, "No employee profile")
    return row


def serialize(db, row):
    subject = db.get(Subject, row.user_id)
    return {key: getattr(row, key) for key in ["id", "user_id", *FIELDS, "created_by", "created_at", "updated_by", "updated_at"]} | {
        "pre_registered": subject is None, "department": subject.department if subject else None}


def save(db, actor, values, row=None):
    if row is None:
        row = EmployeeProfile(**values, created_by=actor.username, updated_by=actor.username)
        db.add(row)
        action, changed = "create_employee_profile", sorted(values)
    else:
        changed = sorted(k for k, v in values.items() if getattr(row, k) != v)
        for key in changed:
            setattr(row, key, values[key])
        row.updated_by, row.updated_at = actor.username, utcnow()
        action = "update_employee_profile"
    audit(db, actor, action, row.user_id, {"fields": changed})
    db.flush()
    return row


@router.get("")
def directory(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    removed = select(UserDirectoryRemoval.user_id)
    profiles = db.scalars(select(EmployeeProfile).where(EmployeeProfile.user_id.not_in(removed)).order_by(EmployeeProfile.user_id)).all()
    subjects = db.scalars(select(Subject).where(Subject.user_id.not_in(removed))).all()
    ids = {p.user_id for p in profiles}
    missing = sorted(s.user_id for s in subjects if s.user_id not in ids)
    audit(db, user, "view_employee_directory")
    db.commit()
    return {"profiles": [serialize(db, p) for p in profiles], "missing_profiles": missing,
            "stats": {"total_profiles": len(profiles), "missing_count": len(missing),
                      "completeness_percent": round(100 * (len(subjects) - len(missing)) / len(subjects), 1) if subjects else 100,
                      "by_employment_status": {s: sum(p.employment_status == s for p in profiles) for s in STATUSES},
                      "by_department": dict(Counter(s.department for s in subjects if s.user_id in ids))}}


@router.post("")
def create(payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    values = validated(payload, True)
    if db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == values["user_id"])):
        raise HTTPException(409, "A profile already exists for this user ID")
    try:
        row = save(db, user, values)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A profile already exists for this user ID") from None
    return serialize(db, row)


@router.post("/import")
async def import_directory(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(422, "CSV must be at most 2 MB")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if not reader.fieldnames or set(reader.fieldnames) != set(CSV_FIELDS) or len(reader.fieldnames) != len(CSV_FIELDS):
            raise HTTPException(422, "CSV headers must match the directory template")
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) > 1000:
                raise HTTPException(422, "CSV supports at most 1000 rows")
    except (UnicodeDecodeError, csv.Error):
        raise HTTPException(422, "Invalid UTF-8 CSV") from None
    errors, accepted = [], 0
    for number, payload in enumerate(rows, 2):
        try:
            values = validate(payload, True)
            existing = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == values["user_id"]))
            with db.begin_nested():
                save(db, user, values if existing is None else {k: v for k, v in values.items() if k != "user_id"}, existing)
            accepted += 1
        except (ValueError, IntegrityError) as exc:
            errors.append({"row": number, "message": str(exc) if isinstance(exc, ValueError) else "Could not save row"})
    audit(db, user, "import_employee_directory", detail={"accepted": accepted, "rejected": len(errors)})
    db.commit()
    return {"accepted": accepted, "rejected": len(errors), "errors": errors}


@router.get("/{user_id}")
def detail(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = find(db, user_id)
    audit(db, user, "view_employee_profile", user_id)
    db.commit()
    return serialize(db, row)


@router.put("/{user_id}")
def update(user_id: str, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = save(db, user, validated(payload), find(db, user_id))
    db.commit()
    return serialize(db, row)


@router.post("/{user_id}/offboard")
def offboard(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = find(db, user_id)
    row.employment_status, row.updated_by, row.updated_at = "offboarded", user.username, utcnow()
    audit(db, user, "offboard_employee", user_id)
    db.commit()
    return serialize(db, row)


@router.get("/{user_id}/contacts")
def contacts(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if not db.get(Subject, user_id):
        find(db, user_id)
    rows = db.scalars(select(EmployeeContact).where(EmployeeContact.user_id == user_id).order_by(EmployeeContact.created_at.desc(), EmployeeContact.id.desc())).all()
    audit(db, user, "view_employee_contacts", user_id)
    db.commit()
    return [contact_dict(row) for row in rows]


def contact_dict(row):
    return {k: getattr(row, k) for k in ("id", "user_id", "contacted_by", "method", "summary", "escalation_id", "created_at")}


@router.post("/{user_id}/contacts")
def add_contact(user_id: str, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    find(db, user_id)
    try:
        if set(payload) - {"method", "summary"}:
            raise ValueError("Unknown contact field")
        method = text(payload.get("method", ""), "method", 16)
        summary = text(payload.get("summary", ""), "summary", 4000)
        if method not in ("email", "phone", "in_person", "other"):
            raise ValueError("method: expected email, phone, in_person or other")
        if not summary:
            raise ValueError("summary: required")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    row = EmployeeContact(user_id=user_id, contacted_by=user.username, method=method, summary=summary)
    db.add(row)
    audit(db, user, "add_employee_contact", user_id, {"method": method, "summary_length": len(summary)})
    db.commit()
    return contact_dict(row)


@router.post("/{user_id}/remove")
def remove_user(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if db.get(UserDirectoryRemoval, user_id) is not None:
        return {"user_id": user_id, "removed": True}
    if db.get(Subject, user_id) is None and db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.user_id == user_id)) is None:
        raise HTTPException(404, "Unknown user")
    db.add(UserDirectoryRemoval(user_id=user_id, removed_by=user.username))
    audit(db, user, "remove_directory_user", user_id, {"history_retained": True})
    db.commit()
    return {"user_id": user_id, "removed": True}
