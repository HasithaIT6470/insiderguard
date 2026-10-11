"""Parsing and normalization of raw telemetry into the standard internal event format (3.2)."""
import re
from datetime import datetime, timezone

EVENT_TYPE_ALIASES = {
    "auth": "auth", "login": "auth", "logon": "auth", "authentication": "auth", "logoff": "auth",
    "file_access": "file_access", "file": "file_access", "read": "file_access", "open": "file_access",
    "file_read": "file_access", "access": "file_access", "fileaccess": "file_access",
    "download": "download", "file_download": "download", "export": "download",
    "denied_access": "denied_access", "denied": "denied_access", "access_denied": "denied_access",
    "device": "device", "usb": "device", "device_connect": "device", "usb_mount": "device",
    "honeytoken": "honeytoken", "decoy": "honeytoken",
}
RESULT_ALIASES = {
    "success": "success", "ok": "success", "allowed": "success", "succeeded": "success", "true": "success",
    "fail": "fail", "failure": "fail", "failed": "fail", "error": "fail", "false": "fail",
    "denied": "denied", "blocked": "denied", "deny": "denied",
}
FIELD_ALIASES = {
    "timestamp": ["timestamp", "ts", "time", "datetime", "date_time", "event_time"],
    "user_id": ["user_id", "user", "userid", "username", "uid", "account"],
    "event_type": ["event_type", "type", "event", "action"],
    "resource": ["resource", "file", "path", "object", "target", "file_path"],
    "resource_type": ["resource_type", "resource_category", "file_type", "classification"],
    "device_id": ["device_id", "device", "host", "hostname", "machine"],
    "result": ["result", "status", "outcome"],
    "volume_mb": ["volume_mb", "volume", "size_mb", "mb"],
    "volume_bytes": ["volume_bytes", "bytes", "size_bytes"],
    "honeytoken": ["honeytoken", "is_honeytoken", "honeytoken_flag"],
    "department": ["department", "dept"],
    "label_malicious": ["label_malicious", "is_malicious", "malicious", "label"],
    "scenario_id": ["scenario_id", "scenario"],
}
USER_RE = re.compile(r"^[A-Za-z0-9_.@\-]{1,64}$")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S",
)
MAX_VOLUME_MB = 10_000_000


def _pick(raw: dict, field: str):
    for name in FIELD_ALIASES[field]:
        if name in raw and raw[name] not in (None, ""):
            return raw[name]
    return None


def _clean(value, limit: int) -> str | None:
    if value is None:
        return None
    text = CTRL_RE.sub("", str(value)).strip()
    return text[:limit] if text else None


def _to_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "malicious", "t"):
        return True
    if text in ("0", "false", "no", "n", "benign", "normal", "f"):
        return False
    return None


def parse_timestamp(value) -> datetime:
    """Accepts ISO-8601, common date strings and epoch seconds/milliseconds. Returns naive UTC."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}(\.\d+)?", value.strip())):
        num = float(value)
        if num > 1e11:
            num /= 1000.0
        dt = datetime.fromtimestamp(num, tz=timezone.utc)
    else:
        text = str(value).strip()
        dt = None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in TS_FORMATS:
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError(f"unrecognised timestamp format: {text[:40]!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def normalize_record(raw) -> tuple[dict | None, list[dict]]:
    """Return (normalized_event, errors). errors is a list of {field, message}."""
    errors: list[dict] = []
    if not isinstance(raw, dict):
        return None, [{"field": "*", "message": "record must be an object"}]
    rec = {str(k).strip().lower(): v for k, v in raw.items()}

    ts = None
    raw_ts = _pick(rec, "timestamp")
    if raw_ts is None:
        errors.append({"field": "timestamp", "message": "required"})
    else:
        try:
            ts = parse_timestamp(raw_ts)
        except (ValueError, OverflowError, OSError) as exc:
            errors.append({"field": "timestamp", "message": str(exc)})

    user_id = _clean(_pick(rec, "user_id"), 64)
    if not user_id:
        errors.append({"field": "user_id", "message": "required"})
    elif not USER_RE.match(user_id):
        errors.append({"field": "user_id", "message": "must match [A-Za-z0-9_.@-]{1,64}"})

    event_type = None
    raw_type = _pick(rec, "event_type")
    if raw_type is None:
        errors.append({"field": "event_type", "message": "required"})
    else:
        event_type = EVENT_TYPE_ALIASES.get(str(raw_type).strip().lower())
        if event_type is None:
            errors.append({"field": "event_type", "message": f"unsupported value {str(raw_type)[:30]!r}"})

    result = "success"
    raw_result = _pick(rec, "result")
    if raw_result is not None:
        result = RESULT_ALIASES.get(str(raw_result).strip().lower())
        if result is None:
            errors.append({"field": "result", "message": f"unsupported value {str(raw_result)[:30]!r}"})
    if event_type == "denied_access":
        result = "denied"

    volume = 0.0
    raw_vol = _pick(rec, "volume_mb")
    raw_bytes = _pick(rec, "volume_bytes")
    try:
        if raw_vol is not None:
            volume = float(raw_vol)
        elif raw_bytes is not None:
            volume = float(raw_bytes) / (1024 * 1024)
    except (TypeError, ValueError):
        errors.append({"field": "volume_mb", "message": "must be numeric"})
    else:
        if volume != volume or volume < 0 or volume > MAX_VOLUME_MB:  # NaN / out of range
            errors.append({"field": "volume_mb", "message": "must be between 0 and 10,000,000"})

    resource = _clean(_pick(rec, "resource"), 512)
    if event_type in ("file_access", "download", "denied_access", "honeytoken") and not resource:
        errors.append({"field": "resource", "message": f"required for {event_type} events"})

    if errors:
        return None, errors

    return (
        {
            "timestamp": ts,
            "user_id": user_id,
            "department": _clean(_pick(rec, "department"), 64),
            "event_type": event_type,
            "resource": resource,
            "resource_type": _clean(_pick(rec, "resource_type"), 64),
            "device_id": _clean(_pick(rec, "device_id"), 64),
            "result": result,
            "volume_mb": round(volume, 4),
            "honeytoken_flag": bool(_to_bool(_pick(rec, "honeytoken"))),
            "label_malicious": _to_bool(_pick(rec, "label_malicious")),
            "scenario_id": _clean(_pick(rec, "scenario_id"), 64),
        },
        [],
    )
