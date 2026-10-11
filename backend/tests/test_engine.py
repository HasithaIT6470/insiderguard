from datetime import datetime, timedelta

import pandas as pd

from app import config
from app.engine import build_series, categorize, compute_baseline, detect_user, incidents_from_series, score_window

CFG = {k: float(v[0]) for k, v in config.DEFAULT_RULES.items()}
T0 = datetime(2026, 8, 3, 9, 0)


def ev(i, ts, etype, **kw):
    base = dict(id=i, user_id="u1", timestamp=ts, event_type=etype, resource="/x/doc", resource_type="general",
                device_id="LT-1", result="success", volume_mb=0.0)
    base.update(kw)
    return base


def history(days=20):
    events, i = [], 0
    for d in range(days):
        day = T0 + timedelta(days=d)
        for k in range(12):
            i += 1
            events.append(ev(i, day + timedelta(minutes=k * 10), "file_access"))
        i += 1
        events.append(ev(i, day, "auth"))
        i += 1
        events.append(ev(i, day + timedelta(hours=2), "download", volume_mb=10.0))
    return events


def test_baseline_pending_then_established():
    ev_ = history(5)
    assert compute_baseline(pd.DataFrame(ev_), CFG)["status"] == "pending"
    b = compute_baseline(pd.DataFrame(history(20)), CFG)
    assert b["status"] == "established" and b["devices"] == ["LT-1"]
    assert 8.5 < b["login_hour"]["mean"] < 9.5


def test_rule_bulk_download_and_honeytoken():
    events = history(20)
    day = T0 + timedelta(days=20)
    events.append(ev(9001, day + timedelta(hours=3), "download", volume_mb=800))
    events.append(ev(9002, day + timedelta(hours=4), "file_access", resource="/decoy/x"))
    inds = detect_user(sorted(events, key=lambda e: e["timestamp"]), None, {"/decoy/x"}, CFG)
    names = {(i.source, i.name) for i in inds}
    assert ("rule", "bulk_download") in names and ("honeytoken", "honeytoken_interaction") in names
    assert not any(i.source == "anomaly" for i in inds)  # no baseline -> no anomaly engine


def test_anomaly_uses_personal_baseline_and_records_it():
    events = history(20)
    day = T0 + timedelta(days=20)
    events.append(ev(9001, day + timedelta(hours=3), "download", volume_mb=300))  # below the fixed rule threshold
    base = compute_baseline(pd.DataFrame(events), CFG)
    inds = detect_user(events, base, set(), CFG)
    anomalies = [i for i in inds if i.name == "download_volume_anomaly"]
    assert anomalies and anomalies[0].detail["baseline_mean"] > 0 and anomalies[0].detail["z"] >= CFG["anomaly_z"]
    assert not any(i.name == "bulk_download" for i in inds)


def test_failed_logon_burst_rule():
    ts = T0 + timedelta(days=1)
    events = [ev(i, ts + timedelta(seconds=10 * i), "auth", result="fail") for i in range(6)]
    inds = detect_user(events, None, set(), CFG)
    assert any(i.name == "failed_logon_burst" for i in inds)


def test_score_is_deterministic_capped_and_categorised():
    events = history(20)
    day = T0 + timedelta(days=20, hours=1)
    events += [ev(9000 + i, day + timedelta(minutes=i), "download", volume_mb=900) for i in range(3)]
    events.append(ev(9100, day, "file_access", resource="/d", resource_type="restricted"))
    events.append(ev(9101, day, "file_access", resource="/decoy/x"))
    events.sort(key=lambda e: e["timestamp"])
    base = compute_baseline(pd.DataFrame(events), CFG)
    inds = detect_user(events, base, {"/decoy/x"}, CFG)
    s1 = build_series(inds, "hybrid", CFG)
    s2 = build_series(list(reversed(inds)), "hybrid", CFG)
    assert [round(x[1], 1) for x in s1] == [round(x[1], 1) for x in s2]
    peak = max(s[1] for s in s1)
    assert 75 <= peak <= 100 and categorize(peak, CFG) == "Critical"
    assert max(s[1] for s in build_series(inds, "rule_only", CFG)) <= peak
    assert incidents_from_series(s1, CFG)


def test_score_breakdown_has_one_entry_per_category():
    events = history(20)
    day = T0 + timedelta(days=20, hours=2)
    events += [ev(9000 + i, day + timedelta(minutes=i), "download", volume_mb=900) for i in range(3)]
    events.sort(key=lambda e: e["timestamp"])
    inds = detect_user(events, None, set(), CFG)
    score, breakdown = score_window(inds, inds[-1].time, "hybrid", CFG)
    cats = [b["category"] for b in breakdown if b["category"] != "correlation"]
    assert len(cats) == len(set(cats)) and score == min(100.0, sum(b["weight"] for b in breakdown))
