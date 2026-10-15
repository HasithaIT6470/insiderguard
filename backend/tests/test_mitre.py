import copy
import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app import config, mitre
from app.ai import SYSTEM_PROMPT, anonymize_alert
from app.engine import Indicator, compute_baseline, detect_user, score_window
from app.generator import generate


def test_catalog_and_all_mappings_are_active():
    catalog = mitre.load_catalog()
    assert catalog["attack_version"]
    assert catalog["domain"] == "enterprise-attack"
    assert len(catalog["techniques"]) > 500
    assert catalog["tactics"] == sorted(catalog["tactics"], key=lambda t: t["order"])
    for rules in mitre.MAPPINGS.values():
        for rule in rules:
            technique = catalog["techniques"][rule["technique"]]
            assert not technique.get("revoked") and not technique.get("x_mitre_deprecated")


def test_builder_excludes_revoked_and_deprecated_and_uses_matrix_order():
    spec = importlib.util.spec_from_file_location("builder", Path(__file__).parents[1] / "scripts/build_mitre_catalog.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    ref = lambda tid: [{"source_name": "mitre-attack", "external_id": tid, "url": f"https://attack.mitre.org/techniques/{tid}"}]
    pattern = {"type": "attack-pattern", "name": "Brute Force", "external_references": ref("T1110"),
               "kill_chain_phases": [{"kill_chain_name": "mitre-attack", "phase_name": "credential-access"}]}
    objects = [
        {"type": "x-mitre-collection", "name": "Enterprise ATT&CK", "x_mitre_version": "test"},
        {"type": "x-mitre-matrix", "x_mitre_domains": ["enterprise-attack"], "tactic_refs": ["b", "a"]},
        {"type": "x-mitre-tactic", "id": "a", "name": "Credential Access", "x_mitre_shortname": "credential-access", "external_references": ref("TA0006")},
        {"type": "x-mitre-tactic", "id": "b", "name": "Discovery", "x_mitre_shortname": "discovery", "external_references": ref("TA0007")},
        pattern,
        {**pattern, "revoked": True, "external_references": ref("T1083")},
        {**pattern, "x_mitre_deprecated": True, "external_references": ref("T1039")},
    ]
    catalog = builder.build_catalog({"objects": objects}, "test")
    assert list(catalog["techniques"]) == ["T1110"]
    assert [t["id"] for t in catalog["tactics"]] == ["TA0007", "TA0006"]


def test_failed_logons_resolve_and_unknown_ids_do_not_raise():
    assert mitre.techniques_for("failed_logon_burst", {}) == ["T1110"]
    technique = mitre.resolve(["T1110"], "failed_logon_burst", {})[0]
    assert technique["name"] == "Brute Force"
    assert technique["tactics"] == [{"id": "TA0006", "name": "Credential Access"}]
    assert technique["confidence"] == "high"
    assert technique["url"] == "https://attack.mitre.org/techniques/T1110/"
    unknown = mitre.resolve(["not-a-technique"], "unknown", {})[0]
    assert unknown["name"] == "Unknown technique" and unknown["url"] is None and unknown["tactics"] == []


@pytest.mark.parametrize("observed,expected", [("USB-EXT-1234", "T1052.001"), ("EXT-disk", "T1052.001"),
                                                   ("RMV-drive", "T1052.001"), ("WS-U1", "T1078"), (None, "T1078")])
def test_device_conditions(observed, expected):
    assert mitre.techniques_for("unknown_device", {"observed": observed}) == [expected]


def test_configurable_device_pattern(monkeypatch):
    monkeypatch.setattr(config, "REMOVABLE_DEVICE_PATTERN", r"^PORTABLE-")
    assert mitre.techniques_for("unknown_device", {"observed": "PORTABLE-1"}) == ["T1052.001"]
    assert mitre.techniques_for("unknown_device", {"observed": "USB-EXT-1234"}) == ["T1078"]


@pytest.mark.parametrize("event,result,expected", [
    ("file_access", "success", ["T1083", "T1039"]), ("download", "success", ["T1083", "T1039"]),
    ("honeytoken", "success", ["T1083", "T1039"]), ("file_access", "denied", ["T1083"]),
    ("denied_access", "success", ["T1083"]), ("auth", "success", ["T1083"]),
])
def test_honeytoken_conditions(event, result, expected):
    assert mitre.techniques_for("honeytoken_interaction", {"resource_event": event, "result": result}) == expected


def test_unknown_indicator_warns_once(caplog):
    name = "future_indicator_for_warning_test"
    mitre._warned_names.discard(name)
    assert mitre.techniques_for(name, {}) == []
    assert mitre.techniques_for(name, {}) == []
    assert sum(name in record.message for record in caplog.records) == 1


def test_legacy_enrichment_and_summary_do_not_mutate_evidence():
    items = [{"name": "failed_logon_burst", "detail": {}},
             {"name": "unknown_device", "detail": {"observed": "USB-EXT-1234"}},
             {"name": "off_hours_activity", "detail": {}},
             {"name": "anomalous_login_time", "detail": {}}]
    original = copy.deepcopy(items)
    assert mitre.enrich_breakdown(items)[0]["attack"][0]["id"] == "T1110"
    summary = mitre.attack_summary(items)
    assert items == original
    assert next(t for t in summary["techniques"] if t["id"] == "T1078")["indicators"] == ["off_hours_activity", "anomalous_login_time"]
    assert next(t for t in summary["techniques"] if t["id"] == "T1078")["confidence"] == "medium"
    order = {t["id"]: t["order"] for t in mitre.load_catalog()["tactics"]}
    assert [order[t["id"]] for t in summary["tactics"]] == sorted(order[t["id"]] for t in summary["tactics"])
    # Explicit persisted tags remain authoritative, even when empty.
    assert mitre.enrich_breakdown([{**items[0], "attack_techniques": []}])[0]["attack"] == []


def test_generator_coverage_and_score_invariance():
    events, honeytokens, _ = generate(seed=7, n_users=10, days=35, start=date(2026, 8, 3))
    cfg = {k: float(v[0]) for k, v in config.DEFAULT_RULES.items()}
    frame = pd.DataFrame(events)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    names = set()
    for uid, user in frame.groupby("user_id"):
        records = user.sort_values("timestamp").to_dict("records")
        for i, event in enumerate(records):
            event["id"] = i
        baseline = compute_baseline(user, cfg)
        indicators = detect_user(records, baseline, {h["resource"] for h in honeytokens}, cfg)
        names.update(i.name for i in indicators)
        assert names <= mitre.MAPPINGS.keys()
        if indicators:
            for mode in ("rule_only", "anomaly_only", "hybrid"):
                score, breakdown = score_window(indicators, indicators[-1].time, mode, cfg)
                assert all("attack_techniques" in item for item in breakdown)
                assert score == round(min(100, sum(item["weight"] for item in breakdown)), 1)
                assert all(item["attack_techniques"] == [] for item in breakdown if item["name"] == "correlated_indicators")
    assert "failed_logon_burst" in names and "unknown_device" in names


def test_scoring_does_not_load_or_consult_catalog(monkeypatch):
    def forbidden():
        raise AssertionError("Scoring must not read the ATT&CK catalog")

    monkeypatch.setattr(mitre, "load_catalog", forbidden)
    cfg = {k: float(v[0]) for k, v in config.DEFAULT_RULES.items()}
    now = datetime(2026, 8, 20, 2)
    indicators = [Indicator(now, "u1", 1, "rule", "denied", "failed_logon_burst", 15, {}),
                  Indicator(now, "u1", 2, "rule", "volume", "bulk_download", 30, {})]
    score, breakdown = score_window(indicators, now, "hybrid", cfg)
    assert score == 55
    assert breakdown[-1]["name"] == "correlated_indicators"
    assert breakdown[-1]["attack_techniques"] == []


def test_mapping_api_and_alert_risk_timeline(client, admin, analyst):
    assert client.get("/api/mitre/mapping").status_code == 401
    mapping = client.get("/api/mitre/mapping", headers=analyst)
    assert mapping.status_code == 200
    assert mapping.json()["attack_version"] == mitre.load_catalog()["attack_version"]
    assert len(mapping.json()["mappings"]["unknown_device"]) == 2
    events = [{"timestamp": f"2026-08-20T02:00:{i:02}", "user_id": "mitre-test-user",
               "event_type": "auth", "result": "fail"} for i in range(7)]
    events.append({"timestamp": "2026-08-20T02:01:00", "user_id": "mitre-test-user",
                   "event_type": "download", "resource": "/synthetic/shared/report.csv", "volume_mb": 900})
    ingested = client.post("/api/events", json=events, headers=admin)
    assert ingested.status_code == 200
    assert ingested.json()["rejected"] == 0
    alerts = client.get("/api/alerts", headers=analyst).json()
    alert = next(a for a in alerts if a["user_id"] == "mitre-test-user")
    detail = client.get(f"/api/alerts/{alert['id']}", headers=analyst).json()
    assert detail["attack"]["techniques"]
    assert all(isinstance(b["attack"], list) for b in detail["breakdown"])
    assert any(t["id"] == "T1110" for t in detail["attack"]["techniques"])
    timeline = client.get("/api/users/mitre-test-user/timeline", headers=analyst).json()
    assert all(isinstance(item["attack"], list) for item in timeline)
    risk = client.get("/api/users/mitre-test-user/risk", headers=analyst).json()
    assert all(isinstance(b["attack"], list) for b in risk["breakdown"])


def test_ai_ids_are_included_without_identifiers():
    now = datetime(2026, 8, 3, 9)
    alert = SimpleNamespace(user_id="private-employee", peak_score=50, category="High", start_time=now,
                            last_time=now + timedelta(minutes=5), breakdown=[
        {"name": "unknown_device", "category": "device", "source": "anomaly", "weight": 12,
         "detail": {"observed": "USB-EXT-private", "metric": "device_usage", "resource": "/private/file"}},
        {"name": "failed_logon_burst", "category": "denied", "source": "rule", "weight": 15,
         "detail": {"failures": 6}},
    ])
    summary = anonymize_alert(alert)
    assert summary["indicators"][0]["attack_techniques"] == ["T1052.001"]
    assert summary["indicators"][1]["attack_techniques"] == ["T1110"]
    encoded = json.dumps(summary)
    assert all(secret not in encoded for secret in ["user_id", "private-employee", "USB-EXT-private", "/private/file"])
    assert "120 words" in SYSTEM_PROMPT and "Never introduce technique IDs" in SYSTEM_PROMPT
