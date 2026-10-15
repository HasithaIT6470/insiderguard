import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Alert, AlertResolution, AuditLog, CaseEvent, EmployeeContact, Escalation, EscalationEvent, utcnow
from test_cases import claim, make_case, operators


BODY = {"summary": "Please review the evidence and advise on next steps.", "recommendation": "contact_user", "priority": "urgent"}


def file_case(client, make_case, operator, status="open"):
    aid, uid = make_case()
    claim(client, aid, operator)
    if status == "closed":
        assert client.patch(f"/api/alerts/{aid}", json={"status": "closed", "outcome": "true_positive", "note": "The synthetic threat is confirmed."}, headers=operator[1]).status_code == 200
    response = client.post("/api/escalations", json={"alert_id": aid, **BODY}, headers=operator[1])
    assert response.status_code == 200, response.text
    return response.json(), aid, uid


@pytest.fixture(scope="module")
def other_admin(client, admin):
    name = "escalation_admin_" + uuid4().hex[:8]
    password = "AdminTesting#12345"
    assert client.post("/api/auth/accounts", json={"username": name, "password": password, "role": "admin"}, headers=admin).status_code == 201
    token = client.post("/api/auth/login", data={"username": name, "password": password}).json()["access_token"]
    return name, {"Authorization": "Bearer " + token}


def test_owner_only_one_open_snapshot_and_case_history(client, admin, operators, make_case):
    aid, uid = make_case()
    body = {**BODY, "alert_id": aid}
    assert client.post("/api/escalations", json=body, headers=admin).status_code == 403
    assert client.post("/api/escalations", json=body, headers=operators[0][1]).status_code == 409
    claim(client, aid, operators[0])
    assert client.post("/api/escalations", json=body, headers=operators[1][1]).status_code == 403
    with SessionLocal() as db:
        db.get(Alert, aid).breakdown = [{"name": "test_indicator"}]
        db.commit()
    created = client.post("/api/escalations", json=body, headers=operators[0][1]).json()
    assert created["user_id"] == uid and created["snapshot"]["indicators"] == ["test_indicator"]
    assert created["case_status_at_filing"] == "open" and created["snapshot"]["peak_score"] == 60
    assert client.post("/api/escalations", json=body, headers=operators[0][1]).status_code == 409
    assert client.get(f"/api/alerts/{aid}", headers=admin).json()["open_escalation_id"] == created["id"]
    with SessionLocal() as db:
        db.get(Alert, aid).peak_score = 95
        db.commit()
    detail = client.get(f"/api/escalations/{created['id']}", headers=operators[0][1]).json()
    assert detail["snapshot"]["peak_score"] == 60 and detail["timeline"][0]["to_status"] == "submitted"
    with SessionLocal() as db:
        assert db.scalar(select(CaseEvent).where(CaseEvent.alert_id == aid, CaseEvent.action == "escalated"))
    closed, _, _ = file_case(client, make_case, operators[0], "closed")
    assert closed["snapshot"]["outcome"] == "true_positive" and closed["case_status_at_filing"] == "closed"


@pytest.mark.parametrize("fields", [{"summary": "short"}, {"summary": " " * 30}, {"summary": "x" * 4001}, {"recommendation": "disable_account"}, {"priority": "critical"}, {"user_id": "spoofed"}, {"summary": "invalid control\x00text sufficiently long"}])
def test_filing_validation(client, operators, make_case, fields):
    aid, _ = make_case(); claim(client, aid, operators[0])
    assert client.post("/api/escalations", json={**BODY, "alert_id": aid, **fields}, headers=operators[0][1]).status_code == 422


def test_concurrent_filing_has_one_open_escalation(client, operators, make_case):
    aid, _ = make_case(); claim(client, aid, operators[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post("/api/escalations", json={**BODY, "alert_id": aid}, headers=operators[0][1]), range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]


def test_visibility_filters_summary_overdue_csv(client, admin, operators, make_case):
    mine, _, uid = file_case(client, make_case, operators[0])
    other, _, _ = file_case(client, make_case, operators[1])
    with SessionLocal() as db:
        db.get(Escalation, mine["id"]).created_at = utcnow() - timedelta(hours=25)
        db.commit()
    for endpoint in (f"/api/escalations/{other['id']}", f"/api/escalations/{other['id']}/messages", f"/api/escalations/{other['id']}/withdraw"):
        response = client.get(endpoint, headers=operators[0][1]) if endpoint.endswith(str(other["id"])) else client.post(endpoint, json={"message": "Attempt"} if endpoint.endswith("messages") else None, headers=operators[0][1])
        assert response.status_code == 404
    listed = client.get("/api/escalations", params={"status": "submitted,acknowledged", "priority": "urgent", "user_id": uid, "analyst": operators[0][0], "overdue": "true"}, headers=admin).json()
    assert [r["id"] for r in listed] == [mine["id"]] and listed[0]["overdue"]
    assert mine["id"] in [r["id"] for r in client.get("/api/escalations", headers=operators[0][1]).json()]
    assert all(r["created_by"] == operators[0][0] for r in client.get("/api/escalations", headers=operators[0][1]).json())
    summary = client.get("/api/escalations/summary", headers=operators[0][1]).json()
    assert summary["open_count"] >= 1 and summary["overdue_count"] >= 1
    assert client.get("/api/escalations?format=csv", headers=operators[0][1]).status_code == 403
    csv_result = client.get("/api/escalations", params={"format": "csv", "user_id": uid}, headers=admin)
    assert csv_result.status_code == 200 and list(csv.DictReader(io.StringIO(csv_result.text)))[0]["user_id"] == uid
    assert client.get("/api/escalations?status=invalid", headers=admin).status_code == 422


def test_acknowledge_race_and_other_admin_cannot_handle(client, admin, other_admin, operators, make_case):
    row, _, _ = file_case(client, make_case, operators[0]); path = f"/api/escalations/{row['id']}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda headers: client.post(path + "/acknowledge", headers=headers), [admin, other_admin[1]]))
    assert sorted(r.status_code for r in results) == [200, 409]
    winner = next(r.json()["handled_by"] for r in results if r.status_code == 200)
    assert winner in next(r.json()["detail"] for r in results if r.status_code == 409)
    loser = other_admin[1] if winner == "admin" else admin
    assert client.post(path + "/complete", json={"handling_note": "Reviewed all evidence"}, headers=loser).status_code == 409
    assert client.post(path + "/messages", json={"message": "Not my request"}, headers=loser).status_code == 403


def test_info_reply_contact_complete_and_personal_data_isolation(client, admin, operators, make_case):
    row, aid, uid = file_case(client, make_case, operators[0]); path = f"/api/escalations/{row['id']}"
    private = {"user_id": uid, "full_name": "EscalationPrivateName", "email": "escalation-private@example.test", "phone": "+94 776543210", "supervisor_name": "EscalationPrivateSupervisor", "contact_notes": "EscalationPrivateNotes"}
    assert client.post("/api/admin/employees", json=private, headers=admin).status_code == 200
    assert client.post(path + "/acknowledge", headers=admin).status_code == 200
    assert client.post(path + "/request-info", json={"message": " "}, headers=admin).status_code == 422
    assert client.post(path + "/request-info", json={"message": "Please provide more context"}, headers=admin).json()["status"] == "needs_info"
    assert client.post(path + "/messages", json={"message": "Here is the relevant case context"}, headers=operators[0][1]).json()["status"] == "acknowledged"
    contact_marker = "PrivateContactSummaryMarker"
    assert client.post(path + "/contacted", json={"contact_method": "phone", "summary": contact_marker}, headers=admin).json()["status"] == "contacted"
    contacts = client.get(f"/api/admin/employees/{uid}/contacts", headers=admin).json()
    assert contacts[0]["escalation_id"] == row["id"] and contacts[0]["summary"] == contact_marker
    assert client.post(path + "/complete", json={"handling_note": "short"}, headers=admin).status_code == 422
    final = client.post(path + "/complete", json={"handling_note": "Reviewed context and handled the request"}, headers=admin).json()
    assert final["status"] == "completed" and final["completed_at"]
    overview = client.get(f"/api/users/{uid}/overview", headers=operators[1][1]).json()
    assert overview["escalations"][0]["id"] == row["id"]
    assert set(overview["escalations"][0]) == {"id", "status", "priority", "created_by", "created_at", "handling_note"}
    markers = [private[k] for k in ("full_name", "email", "phone", "supervisor_name", "contact_notes")] + [contact_marker]
    for headers in (admin, operators[0][1]):
        for endpoint in ("/api/escalations", path, "/api/escalations/summary", f"/api/users/{uid}/overview", f"/api/alerts/{aid}", "/api/audit", "/api/escalations?format=csv"):
            result = client.get(endpoint, headers=headers)
            assert not any(marker in result.text for marker in markers), endpoint
    detail = client.get(path, headers=admin).json()
    assert [e["to_status"] for e in detail["timeline"]] == ["submitted", "acknowledged", "needs_info", "acknowledged", "contacted", "completed"]
    assert len(detail["messages"]) == 2
    with SessionLocal() as db:
        audit_rows = db.scalars(select(AuditLog).where(AuditLog.target == str(row["id"]))).all()
        assert {"create_escalation", "acknowledge_escalation", "request_escalation_info", "reply_escalation", "contact_escalation", "complete_escalation"}.issubset({a.action for a in audit_rows})
        assert db.get(Alert, aid).status == "open"
    assert client.post("/api/escalations", json={**BODY, "alert_id": aid}, headers=operators[0][1]).status_code == 200


def test_withdraw_invalid_transitions_role_guards_and_contact_without_profile(client, admin, operators, make_case):
    row, aid, uid = file_case(client, make_case, operators[0]); path = f"/api/escalations/{row['id']}"
    for suffix, body in [("request-info", {"message": "More context"}), ("contacted", {"contact_method": "other", "summary": "Private context"}), ("complete", {"handling_note": "Handled this request"})]:
        assert client.post(path + "/" + suffix, json=body, headers=admin).status_code == 409
        assert client.post(path + "/" + suffix, json=body, headers=operators[0][1]).status_code == 403
    assert client.post(path + "/withdraw", headers=admin).status_code == 403
    assert client.post(path + "/withdraw", headers=operators[0][1]).json()["status"] == "withdrawn"
    for suffix, body, headers in [("withdraw", None, operators[0][1]), ("acknowledge", None, admin), ("messages", {"message": "Late reply"}, operators[0][1])]:
        assert client.post(path + "/" + suffix, json=body, headers=headers).status_code == 409
    row = client.post("/api/escalations", json={**BODY, "alert_id": aid}, headers=operators[0][1]).json(); path = f"/api/escalations/{row['id']}"
    assert client.post(path + "/acknowledge", headers=admin).status_code == 200
    assert client.post(path + "/withdraw", headers=operators[0][1]).status_code == 409
    assert client.post(path + "/contacted", json={"contact_method": "other", "summary": "Private context without a directory profile"}, headers=admin).status_code == 200
    assert client.get(f"/api/admin/employees/{uid}/contacts", headers=admin).json()[0]["escalation_id"] == row["id"]
