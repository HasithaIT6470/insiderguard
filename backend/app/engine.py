"""Pure detection logic: behavioural baseline, rule engine, anomaly engine, honeytoken
engine and the deterministic risk-scoring model. No database access here, so the very same
code is used by the live pipeline and by the offline evaluation."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .mitre import techniques_for

SOURCES_BY_MODE = {
    "rule_only": {"rule"},
    "anomaly_only": {"anomaly"},
    "hybrid": {"rule", "anomaly", "honeytoken"},
}
MODES = tuple(SOURCES_BY_MODE)

DECOY_EVENT_TYPES = {"file_access", "download", "denied_access", "honeytoken"}


@dataclass
class Indicator:
    time: datetime
    user_id: str
    event_id: int | None
    source: str  # rule | anomaly | honeytoken
    category: str  # time | volume | resource | denied | device | honeytoken
    name: str
    weight: float
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["time"] = self.time.isoformat()
        return d


# --------------------------------------------------------------------------- baseline
def _hour(ts: datetime) -> float:
    return ts.hour + ts.minute / 60.0


def circ_diff(a: float, b: float) -> float:
    d = abs(a - b) % 24.0
    return min(d, 24.0 - d)


def _circular_stats(hours: np.ndarray) -> tuple[float, float]:
    """Circular mean and standard deviation (in hours) of hour-of-day values."""
    if len(hours) == 0:
        return 12.0, 12.0
    ang = hours / 24.0 * 2 * math.pi
    s, c = np.sin(ang).mean(), np.cos(ang).mean()
    mean = (math.atan2(s, c) % (2 * math.pi)) / (2 * math.pi) * 24.0
    r = min(max(math.hypot(s, c), 1e-9), 1.0)
    std = math.sqrt(-2.0 * math.log(r)) / (2 * math.pi) * 24.0
    return float(mean), float(std)


def compute_baseline(df: pd.DataFrame, cfg: dict) -> dict:
    """Per-user baseline over the first `baseline_days` of the user's history (REQ-03-01/02/04).

    df columns: timestamp (datetime64), event_type, resource_type, device_id, result, volume_mb.
    """
    first, last = df["timestamp"].min(), df["timestamp"].max()
    window_end = first + timedelta(days=float(cfg["baseline_days"]))
    win = df[df["timestamp"] < window_end]
    established = (last - first) >= timedelta(days=float(cfg["baseline_days"])) and len(win) >= cfg[
        "baseline_min_events"
    ]
    out: dict = {
        "status": "established" if established else "pending",
        "window_start": first.to_pydatetime().isoformat(),
        "window_end": window_end.to_pydatetime().isoformat(),
        "event_count": int(len(win)),
    }
    if not established:
        return out

    auth_ok = win[(win["event_type"] == "auth") & (win["result"] == "success")]
    src = auth_ok if len(auth_ok) >= 5 else win
    hours = (src["timestamp"].dt.hour + src["timestamp"].dt.minute / 60.0).to_numpy(dtype=float)
    mean_h, std_h = _circular_stats(hours)

    days = win["timestamp"].dt.date
    all_days = sorted(days.unique())
    acc = (
        win[win["event_type"] == "file_access"].groupby(win["timestamp"].dt.date).size().reindex(all_days, fill_value=0)
    )
    dl = (
        win[win["event_type"] == "download"]
        .groupby(win["timestamp"].dt.date)["volume_mb"]
        .sum()
        .reindex(all_days, fill_value=0.0)
    )

    def _stats(series: pd.Series, min_std: float) -> dict:
        mean = float(series.mean()) if len(series) else 0.0
        std = float(series.std(ddof=0)) if len(series) > 1 else 0.0
        return {
            "mean": round(mean, 3),
            "std": round(max(std, 0.25 * mean, min_std), 3),
            "max": round(float(series.max()) if len(series) else 0.0, 3),
            "days": int(len(series)),
        }

    out.update(
        login_hour={"mean": round(mean_h, 3), "std": round(max(std_h, 1.0), 3)},
        daily_access=_stats(acc, 1.0),
        daily_download_mb=_stats(dl, 5.0),
        resource_types=sorted({str(x) for x in win["resource_type"].dropna().unique()}),
        devices=sorted({str(x) for x in win["device_id"].dropna().unique()}),
    )
    return out


# --------------------------------------------------------------------------- detection
def _scale(z: float, sens: float, wmin: float, wmax: float) -> float:
    frac = min(1.0, max(0.0, (z - sens) / (2.0 * sens)))
    return round(wmin + (wmax - wmin) * frac, 2)


def detect_user(events: list[dict], baseline: dict | None, honeytokens: set[str], cfg: dict) -> list[Indicator]:
    """Run the rule, honeytoken and anomaly engines over one user's chronological events."""
    out: list[Indicator] = []
    uid = events[0]["user_id"] if events else ""
    sens = float(cfg["anomaly_z"])
    burst = timedelta(minutes=float(cfg["burst_window_min"]))
    off_start, off_end = cfg["off_hours_start"], cfg["off_hours_end"]

    use_anomaly = bool(baseline and baseline.get("status") == "established")
    cutoff = datetime.fromisoformat(baseline["window_end"]) if use_anomaly else None
    known_dev = set(baseline.get("devices", [])) if use_anomaly else set()
    known_types = set(baseline.get("resource_types", [])) if use_anomaly else set()

    failed: deque = deque()
    denied: deque = deque()
    cooldown: dict = {}
    day_access: dict = {}
    day_dl: dict = {}
    last_z: dict = {}
    flagged: set = set()

    def cool(key, t, minutes) -> bool:
        """True (and arms the cooldown) if `key` has not fired within `minutes`."""
        prev = cooldown.get(key)
        if prev is not None and t - prev < timedelta(minutes=minutes):
            return False
        cooldown[key] = t
        return True

    def add(e, source, category, name, weight, **detail):
        out.append(Indicator(e["timestamp"], uid, e["id"], source, category, name, float(weight), detail))

    for e in events:
        t, et, day = e["timestamp"], e["event_type"], e["timestamp"].date()
        hour = _hour(t)
        vol = float(e.get("volume_mb") or 0.0)

        # ---- honeytoken engine
        if e.get("resource") in honeytokens and et in DECOY_EVENT_TYPES:
            if cool(("honey", e["resource"]), t, 5):
                add(e, "honeytoken", "honeytoken", "honeytoken_interaction", cfg["w_honeytoken"],
                    resource_event=et, result=e.get("result"))

        # ---- rule engine
        if et in ("auth", "file_access", "download") and not (et == "auth" and e["result"] != "success"):
            if (hour >= off_start or hour < off_end) and cool("off_hours", t.replace(minute=0, second=0), 59):
                add(e, "rule", "time", "off_hours_activity", cfg["w_off_hours"], hour=round(hour, 2), event_type=et)
        if et == "download":
            if vol >= cfg["bulk_download_mb"]:
                add(e, "rule", "volume", "bulk_download", cfg["w_bulk_download"],
                    volume_mb=vol, threshold_mb=cfg["bulk_download_mb"])
            day_dl_rule = day_dl.get(day, 0.0) + vol
            day_dl[day] = day_dl_rule
            if day_dl_rule >= cfg["daily_download_mb"] and cool(("daily_dl", day), t, 24 * 60):
                add(e, "rule", "volume", "bulk_download", cfg["w_bulk_download"],
                    daily_total_mb=round(day_dl_rule, 1), threshold_mb=cfg["daily_download_mb"])
        if et == "auth" and e["result"] == "fail":
            failed.append(t)
            while failed and t - failed[0] > burst:
                failed.popleft()
            if len(failed) >= cfg["failed_logon_count"] and cool("failed_burst", t, cfg["burst_window_min"]):
                add(e, "rule", "denied", "failed_logon_burst", cfg["w_failed_logon"], failures=len(failed))
        if et == "denied_access" or e["result"] == "denied":
            denied.append(t)
            while denied and t - denied[0] > burst:
                denied.popleft()
            if len(denied) >= cfg["denied_access_count"] and cool("denied_burst", t, cfg["burst_window_min"]):
                add(e, "rule", "denied", "repeated_denied_access", cfg["w_denied_access"], denials=len(denied))
        if et in ("file_access", "download") and e.get("resource_type") == "restricted":
            if cool(("restricted", e.get("resource")), t, 24 * 60):
                add(e, "rule", "resource", "restricted_resource_access", cfg["w_restricted"],
                    resource_type="restricted")

        # ---- anomaly engine (needs an established baseline; only after the learning window)
        if not use_anomaly or t < cutoff:
            if et == "file_access":
                day_access[day] = day_access.get(day, 0) + 1
            continue

        if et == "auth" and e["result"] == "success":
            lh = baseline["login_hour"]
            z = circ_diff(hour, lh["mean"]) / lh["std"]
            if z >= sens and cool(("login_anom", day), t, 60):
                add(e, "anomaly", "time", "anomalous_login_time", _scale(z, sens, 8, 15), metric="login_hour",
                    observed=round(hour, 2), baseline_mean=lh["mean"], baseline_std=lh["std"], z=round(z, 2))
        if et == "file_access":
            day_access[day] = day_access.get(day, 0) + 1
            b = baseline["daily_access"]
            z = (day_access[day] - b["mean"]) / b["std"]
            if z >= sens and z >= last_z.get(("acc", day), sens - 1.0) + 1.0:
                last_z[("acc", day)] = z
                add(e, "anomaly", "volume", "access_volume_anomaly", _scale(z, sens, 10, 25), metric="daily_access",
                    observed=day_access[day], baseline_mean=b["mean"], baseline_std=b["std"], z=round(z, 2))
        if et == "download":
            b = baseline["daily_download_mb"]
            total = day_dl.get(day, 0.0)  # already includes this event (updated in the rule section)
            z = (total - b["mean"]) / b["std"]
            if z >= sens and z >= last_z.get(("dl", day), sens - 1.0) + 1.0:
                last_z[("dl", day)] = z
                add(e, "anomaly", "volume", "download_volume_anomaly", _scale(z, sens, 12, 30),
                    metric="daily_download_mb", observed=round(total, 1), baseline_mean=b["mean"],
                    baseline_std=b["std"], z=round(z, 2))
        dev = e.get("device_id")
        if dev and dev not in known_dev and ("dev", dev, day) not in flagged:
            flagged.add(("dev", dev, day))
            add(e, "anomaly", "device", "unknown_device", 12, metric="device_usage", observed=dev,
                baseline_devices=sorted(known_dev))
        rtype = e.get("resource_type")
        if et in ("file_access", "download") and rtype and rtype not in known_types and ("rt", rtype, day) not in flagged:
            flagged.add(("rt", rtype, day))
            add(e, "anomaly", "resource", "novel_resource_category", 8, metric="resource_type", observed=rtype,
                baseline_types=sorted(known_types))
    return out


# --------------------------------------------------------------------------- scoring
def categorize(score: float, cfg: dict) -> str:
    if score >= cfg["critical_threshold"]:
        return "Critical"
    if score >= cfg["high_threshold"]:
        return "High"
    if score >= cfg["medium_threshold"]:
        return "Medium"
    return "Low"


def _bonus(n_categories: int) -> int:
    return 0 if n_categories < 2 else {2: 10, 3: 20}.get(n_categories, 25)


def score_window(inds: list[Indicator], now: datetime, mode: str, cfg: dict) -> tuple[float, list[dict]]:
    """Deterministic 0-100 score: strongest indicator per category, summed, plus a correlation
    bonus (hybrid only) when several categories fire inside a short window; capped at 100."""
    allowed = SOURCES_BY_MODE[mode]
    best: dict[str, Indicator] = {}
    for x in inds:
        if x.source in allowed and (x.category not in best or x.weight > best[x.category].weight):
            best[x.category] = x
    breakdown = [
        {"category": x.category, "name": x.name, "source": x.source, "weight": x.weight, "time": x.time.isoformat(),
         "detail": x.detail, "attack_techniques": techniques_for(x.name, x.detail)}
        for x in sorted(best.values(), key=lambda i: -i.weight)
    ]
    total = sum(x.weight for x in best.values())
    if mode == "hybrid":
        horizon = now - timedelta(minutes=float(cfg["correlation_window_min"]))
        cats = {x.category for x in inds if x.source in allowed and x.time > horizon}
        bonus = _bonus(len(cats))
        if bonus:
            breakdown.append({"category": "correlation", "name": "correlated_indicators", "source": "rule",
                              "weight": float(bonus), "time": now.isoformat(),
                              "detail": {"distinct_categories": sorted(cats)}, "attack_techniques": []})
            total += bonus
    return round(min(100.0, total), 1), breakdown


def build_series(inds: list[Indicator], mode: str, cfg: dict) -> list[tuple[datetime, float, list[dict]]]:
    """Score evaluated at every indicator instant of the chosen mode (REQ-07-04)."""
    allowed = SOURCES_BY_MODE[mode]
    seq = sorted((i for i in inds if i.source in allowed), key=lambda i: i.time)
    window = timedelta(hours=float(cfg["score_window_hours"]))
    series, lo = [], 0
    for idx, ind in enumerate(seq):
        if idx + 1 < len(seq) and seq[idx + 1].time == ind.time:
            continue  # evaluate once per instant, with every indicator at that instant included
        while seq[lo].time <= ind.time - window:
            lo += 1
        score, breakdown = score_window(seq[lo: idx + 1], ind.time, mode, cfg)
        series.append((ind.time, score, breakdown))
    return series


def incidents_from_series(series, cfg: dict) -> list[dict]:
    """Group consecutive above-threshold points into incidents (alerts)."""
    gap = timedelta(hours=float(cfg["score_window_hours"]))
    thr = float(cfg["alert_threshold"])
    incidents: list[dict] = []
    cur = None
    for t, score, breakdown in series:
        if score < thr:
            continue
        if cur is None or t - cur["last_time"] > gap:
            cur = {"start_time": t, "last_time": t, "peak_score": score, "breakdown": breakdown}
            incidents.append(cur)
        else:
            cur["last_time"] = t
            if score > cur["peak_score"]:
                cur["peak_score"], cur["breakdown"] = score, breakdown
    return incidents
