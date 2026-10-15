from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Platform accounts (administrators / security analysts)."""

    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(16), nullable=False)  # admin | analyst
    created_at = Column(DateTime, default=utcnow)


class Subject(Base):
    """A monitored (synthetic) employee identity."""

    __tablename__ = "subjects"
    user_id = Column(String(64), primary_key=True)
    department = Column(String(64), default="Unknown")
    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    event_count = Column(Integer, default=0)
    baseline_status = Column(String(16), default="pending")


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    department = Column(String(64))
    event_type = Column(String(24), nullable=False)  # auth|file_access|download|denied_access|device|honeytoken
    resource = Column(String(512))
    resource_type = Column(String(64))
    device_id = Column(String(64))
    result = Column(String(16), default="success")  # success|fail|denied
    volume_mb = Column(Float, default=0.0)
    honeytoken_flag = Column(Boolean, default=False)
    # Ground-truth labels, present only for the labelled synthetic data set (evaluation).
    label_malicious = Column(Boolean)
    scenario_id = Column(String(64))
    source = Column(String(16), default="api")
    ingested_at = Column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_events_user_time", "user_id", "timestamp"),)


class Baseline(Base):
    __tablename__ = "baselines"
    user_id = Column(String(64), primary_key=True)
    status = Column(String(16), nullable=False)  # established | pending
    computed_at = Column(DateTime, default=utcnow)
    window_start = Column(DateTime)
    window_end = Column(DateTime)
    event_count = Column(Integer, default=0)
    stats = Column(JSON, default=dict)


class Honeytoken(Base):
    __tablename__ = "honeytokens"
    id = Column(Integer, primary_key=True)
    resource = Column(String(512), unique=True, nullable=False)
    description = Column(String(256))
    created_by = Column(String(64))
    created_at = Column(DateTime, default=utcnow)
    active = Column(Boolean, default=True)
    revoked_at = Column(DateTime)


class Detection(Base):
    """One fired indicator (rule, anomaly or honeytoken)."""

    __tablename__ = "detections"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    event_id = Column(Integer, index=True)
    time = Column(DateTime, nullable=False, index=True)
    source = Column(String(16), nullable=False)  # rule | anomaly | honeytoken
    category = Column(String(24), nullable=False)  # time|volume|resource|denied|device|honeytoken
    name = Column(String(64), nullable=False)
    weight = Column(Float, nullable=False)
    detail = Column(JSON, default=dict)  # includes the baseline used for anomalies (REQ-05-04)


class RiskPoint(Base):
    """Hybrid risk score for a user at an instant (stored when it changes)."""

    __tablename__ = "risk_points"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    time = Column(DateTime, nullable=False, index=True)
    score = Column(Float, nullable=False)
    category = Column(String(16), nullable=False)
    breakdown = Column(JSON, default=list)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False)
    last_time = Column(DateTime, nullable=False)
    peak_score = Column(Float, nullable=False)
    category = Column(String(16), nullable=False)
    breakdown = Column(JSON, default=list)
    status = Column(String(24), default="open")  # open | under_investigation | closed
    narrative = Column(Text)
    narrative_status = Column(String(16), default="none")  # none | generated | unavailable
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "start_time", name="uq_alert_user_start"),)


class CaseNote(Base):
    __tablename__ = "case_notes"
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    author = Column(String(64), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class AlertAssignment(Base):
    __tablename__ = "alert_assignments"
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    # Username intentionally has no foreign key: closed cases retain historical ownership.
    owner = Column(String(64), nullable=False, index=True)
    assigned_by = Column(String(64), nullable=False)
    assigned_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)


class CaseEvent(Base):
    __tablename__ = "case_events"
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), index=True, nullable=False)
    action = Column(String(48), nullable=False)
    actor = Column(String(64), nullable=False)
    actor_role = Column(String(16), nullable=False)
    detail = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AlertResolution(Base):
    __tablename__ = "alert_resolutions"
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), index=True, nullable=False)
    outcome = Column(String(24), nullable=False)
    note = Column(Text, nullable=False)
    resolved_by = Column(String(64), nullable=False)
    resolved_at = Column(DateTime, default=utcnow, nullable=False)
    reopened_at = Column(DateTime)
    reopened_by = Column(String(64))
    reopen_reason = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=utcnow, index=True)
    actor = Column(String(64), nullable=False)
    role = Column(String(16))
    action = Column(String(48), nullable=False)
    target = Column(String(128))
    detail = Column(JSON, default=dict)


class RuleConfig(Base):
    __tablename__ = "rule_config"
    key = Column(String(48), primary_key=True)
    value = Column(Float, nullable=False)
    description = Column(String(256))
    updated_by = Column(String(64))
    updated_at = Column(DateTime, default=utcnow)


class ParseError(Base):
    __tablename__ = "parse_errors"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    source = Column(String(16))
    row_ref = Column(String(32))
    raw = Column(Text)
    errors = Column(JSON, default=list)
    acknowledged = Column(Boolean, default=False)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow)
    run_by = Column(String(64))
    results = Column(JSON, default=dict)


class EmployeeProfile(Base):
    __tablename__ = "employee_profiles"
    id = Column(Integer, primary_key=True)
    # No Subject foreign key: directory registration may precede log ingestion.
    user_id = Column(String(64), unique=True, index=True, nullable=False)
    full_name = Column(String(160), default="")
    email = Column(String(254), default="")
    phone = Column(String(20), default="")
    job_title = Column(String(160), default="")
    supervisor_name = Column(String(160), default="")
    supervisor_email = Column(String(254), default="")
    supervisor_phone = Column(String(20), default="")
    employment_status = Column(String(16), default="active", nullable=False)
    start_date = Column(Date)
    location = Column(String(160), default="")
    contact_notes = Column(Text, default="")
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_by = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)


class EmployeeContact(Base):
    __tablename__ = "employee_contacts"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), index=True, nullable=False)
    contacted_by = Column(String(64), nullable=False)
    method = Column(String(16), nullable=False)
    summary = Column(Text, nullable=False)
    escalation_id = Column(Integer)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Escalation(Base):
    __tablename__ = "escalations"
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    created_by = Column(String(64), nullable=False)
    priority = Column(String(16), nullable=False)
    summary = Column(Text, nullable=False)
    recommendation = Column(String(32), nullable=False)
    recommendation_note = Column(Text, default="")
    case_status_at_filing = Column(String(24), nullable=False)
    snapshot = Column(JSON, nullable=False)
    status = Column(String(24), default="submitted", nullable=False)
    handled_by = Column(String(64))
    handling_note = Column(Text)
    contact_method = Column(String(16))
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("uq_escalation_open_alert", alert_id, unique=True,
                           sqlite_where=status.notin_(["completed", "withdrawn"]),
                           postgresql_where=status.notin_(["completed", "withdrawn"])),)


class EscalationMessage(Base):
    __tablename__ = "escalation_messages"
    id = Column(Integer, primary_key=True)
    escalation_id = Column(Integer, ForeignKey("escalations.id"), index=True, nullable=False)
    author = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class EscalationEvent(Base):
    __tablename__ = "escalation_events"
    id = Column(Integer, primary_key=True)
    escalation_id = Column(Integer, ForeignKey("escalations.id"), index=True, nullable=False)
    actor = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False)
    action = Column(String(48), nullable=False)
    from_status = Column(String(24))
    to_status = Column(String(24), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    recipient = Column(String(64), index=True, nullable=False)
    type = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    message = Column(Text, nullable=False)
    link = Column(String(512), nullable=False)
    alert_id = Column(Integer)
    escalation_id = Column(Integer)
    severity = Column(String(16), default="info", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    read_at = Column(DateTime)
    __table_args__ = (Index("ix_notification_recipient_read", recipient, read_at),)


class NotificationReceipt(Base):
    """Delivery keys survive dismissal/retention so reminders cannot reappear."""
    __tablename__ = "notification_receipts"
    id = Column(Integer, primary_key=True)
    recipient = Column(String(64), index=True, nullable=False)
    type = Column(String(64), nullable=False)
    delivery_key = Column(String(128), nullable=False)
    __table_args__ = (UniqueConstraint("recipient", "type", "delivery_key", name="uq_notification_delivery"),)


class NotificationMaintenance(Base):
    __tablename__ = "notification_maintenance"
    key = Column(String(32), primary_key=True)
    last_run = Column(DateTime, nullable=False)


class DemoSeedRun(Base):
    __tablename__ = "demo_seed_runs"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, nullable=False)
    manifest = Column(JSON, nullable=False)


class UserDirectoryRemoval(Base):
    """Directory visibility only; evidence and employee profiles remain intact."""

    __tablename__ = "user_directory_removals"
    user_id = Column(String(64), primary_key=True)
    removed_by = Column(String(64), nullable=False)
    removed_at = Column(DateTime, nullable=False, default=utcnow)
