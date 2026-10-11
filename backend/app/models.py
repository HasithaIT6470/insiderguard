from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
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
