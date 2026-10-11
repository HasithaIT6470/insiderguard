from datetime import date, timedelta

from app.generator import generate


def test_auth_required_and_rbac(client, admin, analyst):
    assert client.get("/api/alerts").status_code == 401
    assert client.post("/api/events", json={}, headers=analyst).status_code == 403  # analysts cannot ingest
    assert client.put("/api/rules", json={"values": {"alert_threshold": 40}}, headers=analyst).status_code == 403
    assert client.get("/api/audit", headers=analyst).status_code == 403
    assert client.get("/api/alerts", headers=analyst).status_code == 200
    bad = client.post("/api/auth/login", data={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401


def test_structured_error_for_invalid_events(client, admin):
    r = client.post("/api/events", json={"user_id": "u1"}, headers=admin)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["errors"][0]["errors"]
    errs = client.get("/api/parse-errors", headers=admin).json()
    assert errs and errs[0]["errors"]


def test_full_flow_ingest_score_case_and_evaluate(client, admin, analyst):
    events, honeytokens, _ = generate(seed=7, n_users=10, days=35, start=date(2026, 8, 3))
    for h in honeytokens:
        assert client.post("/api/honeytokens", json=h, headers=admin).status_code == 201
    for i in range(0, len(events), 4000):
        r = client.post("/api/events", json={"events": events[i: i + 4000]}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["rejected"] == 0

    summary = client.get("/api/dashboard/summary", headers=analyst).json()
    assert summary["totals"]["users"] == 10 and summary["totals"]["alerts"] > 0

    users = client.get("/api/users", headers=analyst).json()
    assert users[0]["risk_score"] >= users[-1]["risk_score"]
    risky = client.get("/api/alerts", headers=analyst).json()
    assert risky
    top = risky[0]
    assert top["breakdown"] and top["narrative_status"] in ("none", "unavailable")

    detail = client.get(f"/api/alerts/{top['id']}", headers=analyst).json()
    assert detail["notes"] == []
    assert client.post(f"/api/alerts/{top['id']}/notes", json={"note": "Looking into it"}, headers=analyst).status_code == 201
    assert client.patch(f"/api/alerts/{top['id']}", json={"status": "under_investigation"}, headers=analyst).status_code == 200
    assert client.patch(f"/api/alerts/{top['id']}", json={"status": "bogus"}, headers=analyst).status_code == 422

    # AI optional: without a key the deterministic evidence is still returned (REQ-08-04)
    ex = client.post(f"/api/alerts/{top['id']}/explain", headers=analyst).json()
    assert ex["ai_available"] is False and ex["breakdown"] and ex["peak_score"] == top["peak_score"]

    risk = client.get(f"/api/users/{top['user_id']}/risk", headers=analyst).json()
    assert risk["baseline"]["status"] == "established"
    tl = client.get(f"/api/users/{top['user_id']}/timeline", headers=analyst).json()
    assert tl and {"indicator", "weight", "source"} <= set(tl[0])

    # rules are admin-editable and changes trigger rescoring while preserving case state
    before = client.get(f"/api/alerts/{top['id']}", headers=analyst).json()
    assert client.put("/api/rules", json={"values": {"bulk_download_mb": 450}}, headers=admin).status_code == 200
    after = client.get(f"/api/alerts/{top['id']}", headers=analyst).json()
    assert after["status"] == "under_investigation" and len(after["notes"]) == 1
    assert client.put("/api/rules", json={"values": {"nope": 1}}, headers=admin).status_code == 422
    client.put("/api/rules", json={"values": {"bulk_download_mb": 500}}, headers=admin)

    ev = client.post("/api/evaluation/run", headers=analyst)
    assert ev.status_code == 200
    modes = ev.json()["modes"]
    assert set(modes) == {"rule_only", "anomaly_only", "hybrid"}
    assert {"precision", "recall", "f1", "false_positive_rate", "false_negative_rate"} <= set(modes["hybrid"])
    assert client.get("/api/evaluation/results", headers=analyst).status_code == 200

    rep = client.get("/api/reports/risk", headers=analyst)
    assert rep.status_code == 200 and rep.json()["alerts"]
    assert client.get("/api/reports/risk?format=csv", headers=analyst).headers["content-type"].startswith("text/csv")

    actions = {a["action"] for a in client.get("/api/audit?limit=500", headers=admin).json()}
    assert {"view_alert", "add_investigation_note", "change_case_status", "modify_rules", "run_evaluation"} <= actions


def test_honeytoken_revoke_stops_detection(client, admin, analyst):
    h = client.post("/api/honeytokens", json={"resource": "/finance/decoy/extra_decoy.xlsx"}, headers=admin).json()
    assert client.post("/api/honeytokens", json={"resource": "/finance/decoy/extra_decoy.xlsx"}, headers=admin).status_code == 409
    start = date(2026, 9, 20)
    evs = [{"timestamp": f"{start + timedelta(days=0)} 11:00:00", "user_id": "u001", "event_type": "file_access",
            "resource": "/finance/decoy/extra_decoy.xlsx"}]
    assert client.post("/api/events", json=evs, headers=admin).status_code == 200
    tl = client.get("/api/users/u001/timeline", headers=analyst).json()
    assert any(t["indicator"] == "honeytoken_interaction" and t["event"]["resource"].endswith("extra_decoy.xlsx") for t in tl)
    assert client.delete(f"/api/honeytokens/{h['id']}", headers=admin).status_code == 200
    tl = client.get("/api/users/u001/timeline", headers=analyst).json()
    assert not any(t["source"] == "honeytoken" and (t["event"] or {}).get("resource", "").endswith("extra_decoy.xlsx")
                   for t in tl)
