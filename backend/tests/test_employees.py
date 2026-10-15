import csv
import io
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.employees import CSV_FIELDS
from app.models import Alert, AuditLog, Baseline, CaseNote, EmployeeProfile, Event, RiskPoint, Subject


def uid():
    return "directory_" + uuid4().hex[:16]


def profile(user_id):
    return {"user_id": user_id, "full_name": "PrivateMarkerName", "email": "private-marker@example.test",
            "phone": "+94 771234567", "job_title": "PrivateMarkerTitle", "supervisor_name": "PrivateMarkerSupervisor",
            "supervisor_email": "supervisor-marker@example.test", "supervisor_phone": "+94 771234568",
            "employment_status": "active", "start_date": "2025-01-02", "location": "PrivateMarkerLocation",
            "contact_notes": "PrivateMarkerNotes"}


def create(client, admin, user_id=None):
    body = profile(user_id or uid())
    response = client.post("/api/admin/employees", json=body, headers=admin)
    assert response.status_code == 200, response.text
    return response.json()


def test_directory_crud_preregistration_audit_and_retention(client, admin):
    row = create(client, admin)
    user_id = row["user_id"]
    path = f"/api/admin/employees/{user_id}"
    assert row["pre_registered"] is True and row["department"] is None
    assert client.post("/api/admin/employees", json=profile(user_id), headers=admin).status_code == 409
    assert client.get(path, headers=admin).json()["full_name"] == "PrivateMarkerName"
    assert client.put(path, json={"full_name": "  ChangedPrivateName  "}, headers=admin).json()["full_name"] == "ChangedPrivateName"
    assert client.put(path, json={"user_id": uid()}, headers=admin).status_code == 422
    assert client.post(path + "/offboard", headers=admin).json()["employment_status"] == "offboarded"
    assert client.delete(path, headers=admin).status_code == 405
    directory = client.get("/api/admin/employees", headers=admin).json()
    assert any(p["user_id"] == user_id for p in directory["profiles"])
    assert "offboarded" in directory["stats"]["by_employment_status"]
    with SessionLocal() as db:
        events = db.scalars(select(AuditLog).where(AuditLog.target == user_id)).all()
        assert any(e.action == "view_employee_profile" for e in events)
        edit = next(e for e in events if e.action == "update_employee_profile")
        assert edit.detail == {"fields": ["full_name"]}
        assert "ChangedPrivateName" not in str([e.detail for e in events])


@pytest.mark.parametrize("field,value", [
    ("user_id", "bad/id"), ("user_id", "x" * 65), ("full_name", "x" * 161),
    ("email", "bad email"), ("supervisor_email", "bad"), ("phone", "abc123456"),
    ("phone", "123"), ("supervisor_phone", "1" * 21), ("location", "bad\x00location"),
    ("full_name", "bad\nname"), ("employment_status", "departed"), ("start_date", "2025-02-30"),
    ("department", "Not allowed"), ("contact_notes", "x" * 4001), ("email", None),
])
def test_profile_validation(client, admin, field, value):
    assert client.post("/api/admin/employees", json={**profile(uid()), field: value}, headers=admin).status_code == 422


def test_import_upserts_rejects_rows_and_limits(client, admin):
    first, second = uid(), uid()
    create(client, admin, first)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for body in ({**profile(first), "job_title": "Updated title"}, profile(second), {**profile(uid()), "email": "invalid"}):
        writer.writerow({k: body[k] for k in CSV_FIELDS})
    response = client.post("/api/admin/employees/import", files={"file": ("employees.csv", output.getvalue(), "text/csv")}, headers=admin)
    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": 2, "rejected": 1, "errors": [{"row": 4, "message": "email: invalid email address"}]}
    assert client.get(f"/api/admin/employees/{first}", headers=admin).json()["job_title"] == "Updated title"
    assert client.get(f"/api/admin/employees/{second}", headers=admin).status_code == 200
    big = output.getvalue().splitlines()[0] + "\n" + (",".join(["x"] * len(CSV_FIELDS)) + "\n") * 1001
    assert client.post("/api/admin/employees/import", files={"file": ("large.csv", big)}, headers=admin).status_code == 422
    assert client.post("/api/admin/employees/import", files={"file": ("bad.csv", "user_id\nu1")}, headers=admin).status_code == 422


def test_contacts_and_analyst_denial_on_every_directory_route(client, admin, analyst):
    user_id = create(client, admin)["user_id"]
    path = f"/api/admin/employees/{user_id}"
    result = client.post(path + "/contacts", json={"method": "phone", "summary": "  PrivateMarkerContact  "}, headers=admin)
    assert result.status_code == 200
    assert result.json()["summary"] == "PrivateMarkerContact" and result.json()["contacted_by"] == "admin"
    assert client.get(path + "/contacts", headers=admin).json()[0]["id"] == result.json()["id"]
    for body in ({"method": "fax", "summary": "bad"}, {"method": "email", "summary": " "}, {"method": "other", "summary": "bad\x00"}):
        assert client.post(path + "/contacts", json=body, headers=admin).status_code == 422
    for method, endpoint, kwargs in [
        ("get", "/api/admin/employees", {}), ("post", "/api/admin/employees", {"json": profile(uid())}),
        ("get", path, {}), ("put", path, {"json": {"email": "valid@example.test"}}),
        ("post", path + "/offboard", {}), ("get", path + "/contacts", {}),
        ("post", path + "/contacts", {"json": {"method": "email", "summary": "Attempt"}}),
        ("post", "/api/admin/employees/import", {"files": {"file": ("data.csv", "user_id\nx")}}),
    ]:
        assert getattr(client, method)(endpoint, headers=analyst, **kwargs).status_code == 403


@pytest.fixture
def monitored_directory_user(client):
    user_id = uid()
    # Position events relative to the shared dataset so tests do not depend on ordering.
    with SessionLocal() as db:
        from app.pipeline import dataset_end
        end = dataset_end(db) or datetime(2026, 1, 10, 12)
        db.add(Subject(user_id=user_id, department="LogDepartment", first_seen=end - timedelta(days=6), last_seen=end, event_count=3, baseline_status="established"))
        db.add_all([Event(user_id=user_id, timestamp=end, event_type="download", volume_mb=70, device_id="device-test"),
                    Event(user_id=user_id, timestamp=end, event_type="file_access", device_id="device-test"),
                    Event(user_id=user_id, timestamp=end - timedelta(days=6), event_type="file_access", device_id="device-test")])
        db.add(Baseline(user_id=user_id, status="established", stats={"daily_access": {"mean": 4, "std": 2}, "daily_download_mb": {"mean": 12, "std": 3}}))
        db.add_all([RiskPoint(user_id=user_id, time=end - timedelta(hours=1), score=40, category="Medium"), RiskPoint(user_id=user_id, time=end, score=80, category="Critical")])
        alert = Alert(user_id=user_id, start_time=end, last_time=end, peak_score=80, category="Critical", status="open")
        db.add(alert); db.flush()
        db.add(CaseNote(alert_id=alert.id, author="analyst", note="Investigative context"))
        db.commit()
        return user_id, alert.id


def test_overview_stats_log_department_and_profile_booleans(client, admin, analyst, monitored_directory_user):
    user_id, alert_id = monitored_directory_user
    row = create(client, admin, user_id)
    assert row["department"] == "LogDepartment" and row["pre_registered"] is False
    for headers in (admin, analyst):
        overview = client.get(f"/api/users/{user_id}/overview", headers=headers).json()
        assert overview["department"] == "LogDepartment" and overview["has_profile"] is True
        assert len(overview["activity_heatmap"]) == 7 and all(len(row) == 24 for row in overview["activity_heatmap"])
        assert sum(map(sum, overview["activity_heatmap"])) == 3
        assert overview["risk_trend"][-1]["score"] == 80
        assert overview["baseline_vs_recent"]["download_mb"] == {"baseline_mean": 12, "baseline_std": 3, "recent_daily_average": 10}
        assert overview["baseline_vs_recent"]["file_access"]["recent_daily_average"] == 0.29
        assert overview["devices"][0]["count"] == 3
        assert overview["case_history"][0]["id"] == alert_id
        assert overview["case_notes"][0]["note"] == "Investigative context" and overview["escalations"] == []
        listed = next(r for r in client.get("/api/users", headers=headers).json() if r["user_id"] == user_id)
        assert listed["has_profile"] is True and listed["last_seen"] and listed["open_case_count"] == 1
        stats = client.get("/api/users/stats", headers=headers).json()
        assert stats["users_by_department"]["LogDepartment"] >= 1
        assert set(stats["risk_distribution"]) == {"Low", "Medium", "High", "Critical"}
        assert stats["event_volume_by_department"]["LogDepartment"] >= 3
        assert len(stats["top_risky_users"]) <= 5
    prereg = create(client, admin)["user_id"]
    empty = client.get(f"/api/users/{prereg}/overview", headers=analyst).json()
    assert empty["event_count"] == 0 and empty["department"] is None and empty["has_profile"]
    assert client.get(f"/api/users/{uid()}/overview", headers=admin).status_code == 404


def test_personal_markers_never_leak_to_staff_endpoints_or_audit(client, admin, analyst, monitored_directory_user):
    user_id, alert_id = monitored_directory_user
    row = create(client, admin, user_id)
    client.post(f"/api/admin/employees/{user_id}/contacts", json={"method": "other", "summary": "PrivateMarkerContact"}, headers=admin)
    markers = [row[k] for k in ("full_name", "email", "phone", "job_title", "supervisor_name", "supervisor_email", "supervisor_phone", "location", "contact_notes")] + ["PrivateMarkerContact"]
    endpoints = ["/api/auth/me", "/api/users", "/api/users/stats", f"/api/users/{user_id}/overview",
                 f"/api/users/{user_id}/risk", f"/api/users/{user_id}/timeline", f"/api/users/{user_id}/activity",
                 "/api/dashboard/summary", "/api/alerts", f"/api/alerts/{alert_id}", f"/api/alerts/{alert_id}/events",
                 "/api/reports/risk", "/api/reports/risk?format=csv", "/api/reports/range", "/api/reports/indicators",
                 "/api/honeytokens", "/api/rules", "/api/mitre/mapping", "/api/evaluation/feedback", "/api/evaluation/results",
                 "/api/audit", "/api/audit?format=csv"]
    for headers in (admin, analyst):
        for endpoint in endpoints + (["/api/my-cases"] if headers == analyst else ["/api/team/workload"]):
            response = client.get(endpoint, headers=headers)
            assert response.status_code in (200, 403, 404), (endpoint, response.text)
            assert not any(marker in response.text for marker in markers), endpoint
    with SessionLocal() as db:
        assert not any(marker in str([r.detail for r in db.scalars(select(AuditLog))]) for marker in markers)
        from app.ai import anonymize_alert
        assert not any(marker in str(anonymize_alert(db.get(Alert, alert_id))) for marker in markers)


def test_remove_directory_user_admin_only_and_retains_history(client, admin, analyst):
    from app.models import UserDirectoryRemoval
    user_id = uid()
    with SessionLocal() as db:
        db.add(Subject(user_id=user_id, department="Engineering"))
        db.commit()
    path = f"/api/admin/employees/{user_id}/remove"
    assert client.post(path, headers=analyst).status_code == 403
    assert any(row["user_id"] == user_id for row in client.get("/api/users", headers=analyst).json())
    assert client.post(path, headers=admin).json() == {"user_id": user_id, "removed": True}
    assert client.post(path, headers=admin).status_code == 200
    assert all(row["user_id"] != user_id for row in client.get("/api/users", headers=analyst).json())
    assert user_id not in client.get("/api/admin/employees", headers=admin).json()["missing_profiles"]
    with SessionLocal() as db:
        assert db.get(Subject, user_id) is not None
        assert db.get(UserDirectoryRemoval, user_id) is not None
        logs = db.scalars(select(AuditLog).where(AuditLog.target == user_id, AuditLog.action == "remove_directory_user")).all()
        assert len(logs) == 1 and logs[0].detail == {"history_retained": True}
    registered = create(client, admin)["user_id"]
    assert client.post(f"/api/admin/employees/{registered}/remove", headers=admin).status_code == 200
    assert all(row["user_id"] != registered for row in client.get("/api/admin/employees", headers=admin).json()["profiles"])
    with SessionLocal() as db:
        assert db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == registered)) is not None
    assert client.post(f"/api/admin/employees/{uid()}/remove", headers=admin).status_code == 404
