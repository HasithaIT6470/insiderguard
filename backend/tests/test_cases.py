from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

from app import cases, config
from app.database import Base, SessionLocal
from app.models import Alert, AlertAssignment, AuditLog, CaseEvent, Subject, utcnow
from app.pipeline import _sync_alerts


@pytest.fixture(scope="module")
def operators(client, admin):
    result = []
    for _ in range(2):
        username = "case_" + uuid4().hex[:10]
        password = "CaseTesting#12345"
        assert client.post("/api/auth/accounts", json={"username": username, "password": password, "role": "analyst"}, headers=admin).status_code == 201
        token = client.post("/api/auth/login", data={"username": username, "password": password}).json()["access_token"]
        result.append((username, {"Authorization": f"Bearer {token}"}))
    return result


@pytest.fixture
def make_case(client):
    def make(status="open", category="High", age=48):
        uid = "case-subject-" + uuid4().hex[:12]
        with SessionLocal() as db:
            now = utcnow()
            db.add(Subject(user_id=uid, department="Synthetic Lab"))
            alert = Alert(user_id=uid, start_time=now - timedelta(hours=age), last_time=now - timedelta(hours=age - 1),
                          peak_score=80 if category == "Critical" else 60, category=category, status=status, breakdown=[])
            db.add(alert); db.commit()
            return alert.id, uid
    return make


def claim(client, aid, operator):
    response = client.post(f"/api/alerts/{aid}/claim", headers=operator[1])
    assert response.status_code == 200, response.text
    return response.json()


def events(client, aid, headers):
    response = client.get(f"/api/alerts/{aid}/events", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_claim_conflicts_closed_missing_and_role(client, admin, operators, make_case):
    aid, uid = make_case()
    assert client.post(f"/api/alerts/{aid}/claim", headers=admin).status_code == 403
    result = claim(client, aid, operators[0])
    assert result["owner"] == operators[0][0] and result["assigned_at"] and result["status"] == "open"
    for op in operators:
        response = client.post(f"/api/alerts/{aid}/claim", headers=op[1])
        assert response.status_code == 409 and response.json()["detail"] == f"Already claimed by {operators[0][0]}"
    assert client.get(f"/api/alerts/{aid}", headers=admin).json()["owner"] == operators[0][0]
    listed = client.get("/api/alerts", params={"user_id": uid}, headers=admin).json()
    assert len(listed) == 1 and listed[0]["owner"] == operators[0][0]
    closed, _ = make_case(status="closed")
    assert client.post(f"/api/alerts/{closed}/claim", headers=operators[0][1]).json()["detail"] == "Closed cases cannot be claimed"
    assert client.post("/api/alerts/99999999/claim", headers=operators[0][1]).status_code == 404
    assert [e["action"] for e in events(client, aid, admin)] == ["claimed"]


def test_concurrent_claim_has_exactly_one_owner(client, operators, make_case):
    aid, _ = make_case()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda op: client.post(f"/api/alerts/{aid}/claim", headers=op[1]), operators))
    assert sorted(r.status_code for r in responses) == [200, 409]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AlertAssignment).where(AlertAssignment.alert_id == aid)) == 1
        assert db.scalar(select(func.count()).select_from(CaseEvent).where(CaseEvent.alert_id == aid)) == 1


@pytest.mark.parametrize("action", ["status", "note", "explain"])
def test_only_owner_can_edit(client, admin, operators, make_case, action):
    aid, _ = make_case()
    def edit(headers):
        if action == "status":
            return client.patch(f"/api/alerts/{aid}", json={"status": "under_investigation"}, headers=headers)
        if action == "note":
            return client.post(f"/api/alerts/{aid}/notes", json={"note": "Synthetic evidence checked"}, headers=headers)
        return client.post(f"/api/alerts/{aid}/explain", headers=headers)
    assert edit(operators[0][1]).status_code == 409
    assert edit(admin).json()["detail"] == "Administrators have read-only access to case status"
    claim(client, aid, operators[0])
    assert edit(operators[1][1]).json()["detail"] == "Only the case owner can change this case"
    assert edit(admin).status_code == 403
    assert edit(operators[0][1]).status_code in (200, 201)
    if action == "status":
        assert events(client, aid, admin)[-1]["detail"] == {"from": "open", "to": "under_investigation"}
    actions = client.get("/api/audit", params={"limit": 1000}, headers=admin).json()
    assert any(e["action"] == "claim_case" and e["target"] == str(aid) for e in actions)


def test_admin_assign_reassign_closed_and_invalid_owner(client, admin, operators, make_case):
    aid, _ = make_case(status="closed")
    for owner in ("nonexistent-analyst", "admin"):
        assert client.post(f"/api/alerts/{aid}/assign", json={"owner": owner}, headers=admin).status_code == 422
    for op in operators:
        r = client.post(f"/api/alerts/{aid}/assign", json={"owner": op[0]}, headers=admin)
        assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["owner"] == op[0]
    assert client.post(f"/api/alerts/{aid}/assign", json={"owner": operators[0][0]}, headers=operators[0][1]).status_code == 403
    history = events(client, aid, admin)
    assert [e["action"] for e in history] == ["assigned", "reassigned"]
    assert history[-1]["detail"] == {"from": operators[0][0], "to": operators[1][0]}


def test_release_returns_case_to_queue_and_keeps_history(client, admin, operators, make_case):
    aid, _ = make_case(status="under_investigation")
    claim(client, aid, operators[0])
    assert client.post(f"/api/alerts/{aid}/release", json={"reason": "Handoff"}, headers=operators[1][1]).status_code == 403
    assert client.post(f"/api/alerts/{aid}/release", json={"reason": "Handoff"}, headers=admin).status_code == 403
    for reason in ("", "ab", "   "):
        assert client.post(f"/api/alerts/{aid}/release", json={"reason": reason}, headers=operators[0][1]).status_code == 422
    r = client.post(f"/api/alerts/{aid}/release", json={"reason": "Shift handoff"}, headers=operators[0][1])
    assert r.status_code == 200 and r.json()["owner"] is None and r.json()["status"] == "open"
    assert events(client, aid, admin)[-1]["detail"]["from"] == "under_investigation"
    claim(client, aid, operators[0])
    client.patch(f"/api/alerts/{aid}", json={"status": "closed", "outcome": "true_positive", "note": "Confirmed synthetic policy violation"}, headers=operators[0][1])
    assert client.post(f"/api/alerts/{aid}/release", json={"reason": "Handoff"}, headers=operators[0][1]).status_code == 409


def test_owner_filter_sort_my_cases_summary_workload_and_permissions(client, admin, operators, make_case):
    ids = [make_case(category="Critical")[0], make_case(status="under_investigation")[0], make_case()[0]]
    claim(client, ids[0], operators[0]); claim(client, ids[1], operators[1])
    for key, expected in [("me", ids[0]), (operators[0][0], ids[0])]:
        rows = client.get("/api/alerts", params={"owner": key}, headers=operators[0][1]).json()
        assert expected in [a["id"] for a in rows] and all(a["owner"] == operators[0][0] for a in rows)
    rows = client.get("/api/alerts", params={"owner": "unassigned", "limit": 1000}, headers=admin).json()
    assert all(a["owner"] is None for a in rows) and ids[2] in [a["id"] for a in rows]
    for direction in ("asc", "desc"):
        rows = client.get("/api/alerts", params={"sort_by": "owner", "sort_dir": direction, "then_by": "", "limit": 1000}, headers=admin).json()
        values = [a["owner"] or "" for a in rows]
        assert values == sorted(values, reverse=direction == "desc")
    mine = client.get("/api/my-cases", headers=operators[0][1]).json()
    assert ids[0] in [a["id"] for a in mine["cases"]] and all(a["owner"] == operators[0][0] for a in mine["cases"])
    assert mine["summary"]["total"] == sum(mine["summary"][s] for s in ("open", "under_investigation", "closed"))
    assert mine["summary"]["oldest_open_age_hours"] >= 48
    assert all(a["status"] == "closed" for a in client.get("/api/my-cases?status=closed", headers=operators[0][1]).json()["cases"])
    assert client.get("/api/my-cases", headers=admin).status_code == 403
    assert client.get("/api/team/workload", headers=operators[0][1]).status_code == 403
    loads = client.get("/api/team/workload", headers=admin).json()
    own = next(a for a in loads if a["username"] == operators[0][0])
    assert own["critical"] >= 1 and own["oldest_open_age_hours"] >= 48
    assert client.post("/api/evaluation/run", headers=operators[0][1]).status_code == 403
    # Seed an isolated result so this assertion does not depend on another test running first.
    from app.models import EvaluationRun
    with SessionLocal() as db:
        db.add(EvaluationRun(run_by="ownership-test", results={"modes": {}})); db.commit()
    assert client.get("/api/evaluation/results", headers=operators[0][1]).status_code == 200


def test_owned_cases_survive_disappearance_and_shift_without_duplicates(client, admin, operators, make_case):
    aid, uid = make_case()
    claim(client, aid, operators[0])
    cfg = {k: float(v[0]) for k, v in config.DEFAULT_RULES.items()}
    with SessionLocal() as db:
        original = db.get(Alert, aid).start_time
        inc = {"start_time": original + timedelta(minutes=3), "last_time": original + timedelta(hours=1), "peak_score": 80, "breakdown": []}
        _sync_alerts(db, uid, [inc], cfg); db.commit()
        _sync_alerts(db, uid, [inc], cfg); db.commit()
        assert db.get(Alert, aid).start_time == original
        assert db.scalar(select(func.count()).select_from(Alert).where(Alert.user_id == uid)) == 1
        _sync_alerts(db, uid, [], cfg); db.commit()
        _sync_alerts(db, uid, [], cfg); db.commit()
        assert db.get(Alert, aid) is not None
        inc["start_time"] = original
        _sync_alerts(db, uid, [inc], cfg); db.commit()
        _sync_alerts(db, uid, [inc], cfg); db.commit()
        assert db.scalar(select(func.count()).select_from(Alert).where(Alert.user_id == uid)) == 1
        assert cases.get_owner(db, aid) == operators[0][0]
    history = events(client, aid, admin)
    assert [e["action"] for e in history] == ["claimed", "no_longer_detected", "redetected"]
    # A released case has history and must also survive pruning.
    client.post(f"/api/alerts/{aid}/release", json={"reason": "Return to queue"}, headers=operators[0][1])
    with SessionLocal() as db:
        _sync_alerts(db, uid, [], cfg); db.commit()
        assert db.get(Alert, aid) is not None


def test_deleting_analyst_releases_only_nonclosed_cases(client, admin, make_case):
    username = "delete_" + uuid4().hex[:10]
    assert client.post("/api/auth/accounts", json={"username": username, "password": "CaseTesting#12345", "role": "analyst"}, headers=admin).status_code == 201
    ids = [make_case(status=s)[0] for s in ("open", "under_investigation", "closed")]
    for aid in ids:
        assert client.post(f"/api/alerts/{aid}/assign", json={"owner": username}, headers=admin).status_code == 200
    account = next(a for a in client.get("/api/auth/accounts", headers=admin).json() if a["username"] == username)
    assert account["open_cases"] == 2
    assert client.delete(f"/api/auth/accounts/{account['id']}", headers=admin).status_code == 200
    for aid in ids[:2]:
        a = client.get(f"/api/alerts/{aid}", headers=admin).json()
        assert a["owner"] is None and a["status"] == "open"
        assert events(client, aid, admin)[-1]["detail"]["reason"] == "owner account deleted"
    a = client.get(f"/api/alerts/{ids[-1]}", headers=admin).json()
    assert a["owner"] == username and a["status"] == "closed"
    log = next(e for e in client.get("/api/audit?limit=1000", headers=admin).json() if e["action"] == "delete_account" and e["target"] == username)
    assert log["detail"]["released_cases"] == 2


def test_existing_schema_needs_only_new_tables():
    engine = create_engine("sqlite://")
    old = [table for name, table in Base.metadata.tables.items() if name not in {"alert_assignments", "case_events", "alert_resolutions"}]
    Base.metadata.create_all(engine, tables=old)
    before = {t.name: [c["name"] for c in inspect(engine).get_columns(t.name)] for t in old}
    Base.metadata.create_all(engine)
    assert {"alert_assignments", "case_events", "alert_resolutions"} <= set(inspect(engine).get_table_names())
    assert before == {t.name: [c["name"] for c in inspect(engine).get_columns(t.name)] for t in old}
    engine.dispose()
