import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import config
from app.database import SessionLocal
from app.models import Alert, AlertAssignment, AlertResolution, CaseEvent, EvaluationRun, Subject, utcnow
from app.pipeline import _sync_alerts
from test_accounts import account_env
from test_cases import claim, make_case, operators


NOTE = "Reviewed the synthetic evidence and confirmed the outcome."


def close(client, aid, operator, outcome="true_positive", note=NOTE):
    result = client.patch(f"/api/alerts/{aid}", json={"status": "closed", "outcome": outcome, "note": note}, headers=operator[1])
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize("fields", [
    {}, {"note": NOTE}, {"outcome": "true_positive"}, {"outcome": "wrong", "note": NOTE},
    {"outcome": "false_positive", "note": "short"}, {"outcome": "benign_explained", "note": " " * 20},
    {"outcome": "true_positive", "note": "x" * 4001},
])
def test_close_requires_valid_outcome_and_trimmed_note(client, operators, make_case, fields):
    aid, _ = make_case(); claim(client, aid, operators[0])
    response = client.patch(f"/api/alerts/{aid}", json={"status": "closed", **fields}, headers=operators[0][1])
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.get(Alert, aid).status == "open"
        assert db.scalar(select(func.count()).select_from(AlertResolution).where(AlertResolution.alert_id == aid)) == 0


def test_close_owner_only_response_and_safe_audit(client, admin, operators, make_case):
    aid, _ = make_case(); claim(client, aid, operators[0])
    body = {"status": "closed", "outcome": "true_positive", "note": NOTE}
    for headers in (admin, operators[1][1]):
        assert client.patch(f"/api/alerts/{aid}", json=body, headers=headers).status_code == 403
    result = close(client, aid, operators[0], note="  " + NOTE + "  ")
    assert result["status"] == "closed" and result["outcome"] == "true_positive"
    assert result["resolution"]["note"] == NOTE and result["resolution"]["resolved_by"] == operators[0][0]
    detail = client.get(f"/api/alerts/{aid}", headers=admin).json()
    assert len(detail["resolution_history"]) == 1 and detail["resolution_history"][0]["reopened_at"] is None
    audit = next(e for e in client.get("/api/audit?limit=1000", headers=admin).json() if e["action"] == "resolve_case" and e["target"] == str(aid))
    assert audit["detail"] == {"outcome": "true_positive", "note_length": len(NOTE)}
    assert NOTE not in str(audit)
    history = client.get(f"/api/alerts/{aid}/events", headers=admin).json()
    assert any(e["action"] == "resolved" and e["detail"]["outcome"] == "true_positive" for e in history)
    # A repeated closed status is a no-op; replacing the verdict in place is forbidden.
    assert client.patch(f"/api/alerts/{aid}", json={"status": "closed"}, headers=operators[0][1]).status_code == 200
    assert client.patch(f"/api/alerts/{aid}", json=body, headers=operators[0][1]).status_code == 422


def test_simultaneous_close_creates_one_current_resolution(client, operators, make_case):
    aid, _ = make_case(); claim(client, aid, operators[0])
    body = {"status": "closed", "outcome": "true_positive", "note": NOTE}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.patch(f"/api/alerts/{aid}", json=body, headers=operators[0][1]), range(2)))
    assert sum(r.status_code == 200 for r in results) == 1
    assert all(r.status_code in (200, 409, 422) for r in results)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AlertResolution).where(AlertResolution.alert_id == aid)) == 1


def test_reopen_reason_and_multiple_resolutions_preserve_history(client, admin, operators, make_case):
    aid, _ = make_case(); claim(client, aid, operators[0]); first = close(client, aid, operators[0])
    for reason in (None, "", "tiny", "     "):
        body = {"status": "open", **({"reason": reason} if reason is not None else {})}
        assert client.patch(f"/api/alerts/{aid}", json=body, headers=operators[0][1]).status_code == 422
    body = {"status": "under_investigation", "reason": "  New evidence received  "}
    assert client.patch(f"/api/alerts/{aid}", json=body, headers=admin).status_code == 403
    assert client.patch(f"/api/alerts/{aid}", json=body, headers=operators[1][1]).status_code == 403
    result = client.patch(f"/api/alerts/{aid}", json=body, headers=operators[0][1]).json()
    assert result["resolution"] is None and result["outcome"] is None
    second = close(client, aid, operators[0], outcome="false_positive")
    detail = client.get(f"/api/alerts/{aid}", headers=admin).json()
    assert len(detail["resolution_history"]) == 2
    old, new = detail["resolution_history"]
    assert old["id"] == first["resolution"]["id"] and old["outcome"] == "true_positive"
    assert old["reopened_by"] == operators[0][0] and old["reopen_reason"] == "New evidence received" and old["reopened_at"]
    assert new["id"] == second["resolution"]["id"] and new["reopened_at"] is None
    assert detail["resolution"]["id"] == new["id"]


@pytest.mark.parametrize("extra", [{"outcome": "true_positive"}, {"note": NOTE}, {"reason": "Not a reopen"}])
def test_unrelated_resolution_fields_are_rejected(client, operators, make_case, extra):
    aid, _ = make_case(); claim(client, aid, operators[0])
    assert client.patch(f"/api/alerts/{aid}", json={"status": "under_investigation", **extra}, headers=operators[0][1]).status_code == 422


def test_legacy_closed_can_reopen_then_record_an_outcome(client, admin, operators, make_case):
    aid, _ = make_case(status="closed")
    result = client.get(f"/api/alerts/{aid}", headers=admin).json()
    assert result["resolution"] is None and result["resolution_history"] == [] and result["outcome"] is None
    client.post(f"/api/alerts/{aid}/assign", json={"owner": operators[0][0]}, headers=admin)
    assert client.patch(f"/api/alerts/{aid}", json={"status": "open", "reason": "Review legacy case"}, headers=operators[0][1]).status_code == 200
    assert close(client, aid, operators[0], outcome="benign_explained")["resolution"]["outcome"] == "benign_explained"


def test_resolution_survives_rescore_and_update_marker_is_idempotent(client, admin, operators, make_case):
    aid, uid = make_case(); claim(client, aid, operators[0]); result = close(client, aid, operators[0])
    cfg = {k: float(v[0]) for k, v in config.DEFAULT_RULES.items()}
    with SessionLocal() as db:
        alert = db.get(Alert, aid)
        inc = {"start_time": alert.start_time, "last_time": alert.last_time + timedelta(minutes=5), "peak_score": 95, "breakdown": []}
        _sync_alerts(db, uid, [inc], cfg); db.commit()
        _sync_alerts(db, uid, [inc], cfg); db.commit()
        _sync_alerts(db, uid, [], cfg); db.commit()
        assert db.get(Alert, aid).status == "closed"
    detail = client.get(f"/api/alerts/{aid}", headers=admin).json()
    assert detail["resolution"]["id"] == result["resolution"]["id"]
    events = client.get(f"/api/alerts/{aid}/events", headers=admin).json()
    changes = [e for e in events if e["action"] == "updated_after_closure"]
    assert len(changes) == 1 and changes[0]["detail"]["old_peak_score"] == 60 and changes[0]["detail"]["new_peak_score"] == 95


def test_list_current_outcome_filter(client, operators, make_case):
    aid, uid = make_case(); claim(client, aid, operators[0]); close(client, aid, operators[0], outcome="false_positive")
    result = client.get("/api/alerts", params={"user_id": uid, "outcome": "false_positive,benign_explained"}, headers=operators[0][1]).json()
    assert len(result) == 1 and result[0]["outcome"] == "false_positive"
    assert result[0]["resolution"]["note"] == NOTE
    assert client.get("/api/alerts?outcome=bogus", headers=operators[0][1]).status_code == 422
    client.patch(f"/api/alerts/{aid}", json={"status": "open", "reason": "More evidence required"}, headers=operators[0][1])
    assert client.get("/api/alerts", params={"user_id": uid, "outcome": "false_positive"}, headers=operators[0][1]).json() == []


@pytest.fixture
def verdict_data(account_env):
    client, admin, analyst, _, sessions = account_env
    now = utcnow()
    with sessions() as db:
        for i, (outcome, score, category, duration) in enumerate([
            ("true_positive", 35, "High", 2), ("true_positive", 75, "Critical", 6),
            ("false_positive", 45, "High", 4), ("benign_explained", 65, "Medium", 8),
            (None, 90, "Critical", 0), (None, 100, "Critical", 0),
        ], 1):
            db.add(Subject(user_id=f"feedback-{i}", department="Synthetic Lab"))
            alert = Alert(id=i, user_id=f"feedback-{i}", status="open" if i == 6 else "closed", category=category,
                          peak_score=score, start_time=now - timedelta(days=1), last_time=now,
                          breakdown=[{"name": "noisy_signal"}, {"name": "shared"}, {"name": "noisy_signal"}] if i == 3 else [{"name": "noisy_signal"}])
            db.add(alert); db.flush()
            if outcome:
                row = AlertResolution(alert_id=i, outcome=outcome, note=NOTE, resolved_by="viewer", resolved_at=now)
                db.add(row); db.flush()
                assigned = now - timedelta(hours=duration)
                db.add(AlertAssignment(alert_id=i, owner="viewer", assigned_by="rootadmin", assigned_at=assigned))
                db.add(CaseEvent(alert_id=i, action="resolved", actor="viewer", actor_role="analyst",
                                 detail={"outcome": outcome, "resolution_id": row.id, "assigned_at": assigned.isoformat()}))
        db.commit()
    return account_env


def test_feedback_numbers_thresholds_and_no_lab_mutation(verdict_data):
    client, admin, analyst, _, sessions = verdict_data
    with sessions() as db:
        db.add(EvaluationRun(run_by="test", results={"modes": {"lab_only": True}})); db.commit()
        before = db.scalar(select(func.count()).select_from(EvaluationRun))
    assert client.get("/api/evaluation/feedback").status_code == 401
    response = client.get("/api/evaluation/feedback", headers=analyst)
    assert response.status_code == 200
    data = response.json()
    assert data["counts_by_outcome"] == {"true_positive": 2, "false_positive": 1, "benign_explained": 1}
    assert data["closed_with_outcome"] == 4 and data["legacy_closed"] == 1 and data["alert_precision"] == .5
    assert "true_positive /" in data["precision_formula"]
    assert data["median_time_to_close_hours"] == 5 and data["time_to_close_sample_count"] == 4
    assert data["precision_by_category"]["High"]["alert_precision"] == .5
    assert data["precision_by_category"]["Critical"]["alert_precision"] == 1
    assert data["precision_by_category"]["Medium"]["alert_precision"] == 0
    assert data["precision_by_category"]["Low"]["alert_precision"] is None
    assert data["top_indicators"]["false_positive"] == [{"name": "noisy_signal", "count": 1}, {"name": "shared", "count": 1}]
    expected = [(30, 4, 2, 0, 0, 0, .5), (40, 3, 1, 1, 0, 0, 1/3),
                (50, 2, 1, 1, 1, 0, .5), (60, 2, 1, 1, 1, 0, .5), (70, 1, 1, 1, 1, 1, 1)]
    for row, values in zip(data["what_if"], expected):
        assert tuple(row[k] for k in ["threshold", "alerts_kept", "true_positives_kept", "true_positives_lost", "false_positives_removed", "benign_removed", "resulting_precision"]) == values
    assert "missed attacks are never reviewed" in data["note"] and "Recall/F1" in data["note"]
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(EvaluationRun)) == before
        assert db.scalar(select(EvaluationRun)).results == {"modes": {"lab_only": True}}
        # Reassigning a closed case must not corrupt the captured closure duration.
        db.scalar(select(AlertAssignment).where(AlertAssignment.alert_id == 1)).assigned_at = utcnow(); db.commit()
    assert client.get("/api/evaluation/feedback", headers=admin).json()["median_time_to_close_hours"] == 5


def test_feedback_empty(account_env):
    client, _, analyst, _, _ = account_env
    data = client.get("/api/evaluation/feedback", headers=analyst).json()
    assert data["closed_with_outcome"] == data["legacy_closed"] == 0
    assert all(v == 0 for v in data["counts_by_outcome"].values())
    assert data["alert_precision"] is None and data["median_time_to_close_hours"] is None
    assert all(r["alerts_kept"] == 0 and r["resulting_precision"] is None for r in data["what_if"])


def test_reports_owner_outcome_filters_and_columns(verdict_data):
    client, _, analyst, _, _ = verdict_data
    params = {"owner": "viewer", "outcome": "false_positive,benign_explained", "limit": 1}
    result = client.get("/api/reports/risk", params=params, headers=analyst).json()
    assert result["summary"]["total_alerts"] == 2 and len(result["alerts"]) == 1
    assert result["summary"]["alerts_by_outcome"]["false_positive"] == 1
    assert result["summary"]["alerts_by_outcome"]["benign_explained"] == 1
    assert result["alerts"][0]["owner"] == "viewer" and result["alerts"][0]["outcome"] in {"false_positive", "benign_explained"}
    csv_result = client.get("/api/reports/risk", params={**params, "format": "csv"}, headers=analyst)
    rows = list(csv.DictReader(io.StringIO(csv_result.text)))
    assert rows[0]["owner"] == "viewer" and rows[0]["outcome"] == result["alerts"][0]["outcome"]
    unassigned = client.get("/api/reports/risk?owner=unassigned", headers=analyst).json()
    assert {a["alert_id"] for a in unassigned["alerts"]} == {5, 6}
    assert unassigned["summary"]["alerts_by_outcome"]["no_outcome"] == 2
    assert client.get("/api/reports/risk?outcome=bogus", headers=analyst).status_code == 422
