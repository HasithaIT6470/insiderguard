from datetime import datetime

from app.normalize import normalize_record


def test_aliases_and_formats_are_normalized():
    rec, errs = normalize_record({"ts": "03/09/2026 14:05", "user": "u001", "type": "logon", "status": "ok",
                                  "device": "LT-1", "dept": "HR"})
    assert not errs
    assert rec["timestamp"] == datetime(2026, 9, 3, 14, 5)
    assert rec["event_type"] == "auth" and rec["result"] == "success" and rec["department"] == "HR"


def test_epoch_and_bytes():
    rec, errs = normalize_record({"timestamp": 1788000000, "user_id": "u1", "event_type": "download",
                                  "resource": "/a/b", "bytes": 5 * 1024 * 1024})
    assert not errs and rec["volume_mb"] == 5.0


def test_structured_errors():
    rec, errs = normalize_record({"user_id": "bad user!", "event_type": "nope", "volume_mb": -1})
    assert rec is None
    fields = {e["field"] for e in errs}
    assert {"timestamp", "user_id", "event_type", "volume_mb"} <= fields


def test_resource_required_for_file_events():
    _, errs = normalize_record({"timestamp": "2026-09-01T10:00:00", "user_id": "u1", "event_type": "download"})
    assert any(e["field"] == "resource" for e in errs)


def test_control_chars_stripped():
    rec, _ = normalize_record({"timestamp": "2026-09-01T10:00:00", "user_id": "u1", "event_type": "file_access",
                               "resource": "/a/\x00b\n"})
    assert rec["resource"] == "/a/b"
