"""Evaluation of Rule-Only, Anomaly-Only and Hybrid detection on the labelled synthetic data set (3.10)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import MODES, Indicator, build_series
from .models import Baseline, Detection, Event, EvaluationRun, utcnow
from .pipeline import load_config


def _metrics(tp: int, fp: int, fn: int, tn: int) -> dict:
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else 0.0,
    }


def run_evaluation(db: Session, run_by: str = "system", threshold: float | None = None, store: bool = True) -> dict:
    cfg = load_config(db)
    if threshold is not None:
        cfg["alert_threshold"] = float(threshold)
    thr = cfg["alert_threshold"]
    window = timedelta(hours=cfg["score_window_hours"])

    baselines = {b.user_id: b for b in db.scalars(select(Baseline))}
    ev_rows = db.execute(select(Event.user_id, Event.timestamp, Event.label_malicious, Event.scenario_id)).all()
    if not any(r.scenario_id or r.label_malicious for r in ev_rows):
        return {"error": "No labelled events found. Load the labelled synthetic data set first."}

    # ---- ground truth at user-day level (only days after each user's learning window)
    eval_days: set[tuple[str, object]] = set()
    pos_days: set[tuple[str, object]] = set()
    scenarios: dict[str, dict] = {}
    for r in ev_rows:
        b = baselines.get(r.user_id)
        if b is None or b.status != "established":
            continue
        day = r.timestamp.date()
        if day > b.window_end.date():
            eval_days.add((r.user_id, day))
            if r.label_malicious:
                pos_days.add((r.user_id, day))
        if r.scenario_id:
            s = scenarios.setdefault(r.scenario_id, {"user_id": r.user_id, "start": r.timestamp, "end": r.timestamp})
            s["start"], s["end"] = min(s["start"], r.timestamp), max(s["end"], r.timestamp)
    for sid, s in scenarios.items():
        s["type"] = sid.rsplit("-", 1)[0]

    # ---- indicators -> per-mode score series
    by_user: dict[str, list[Indicator]] = defaultdict(list)
    for d in db.scalars(select(Detection)):
        by_user[d.user_id].append(
            Indicator(d.time, d.user_id, d.event_id, d.source, d.category, d.name, d.weight, d.detail or {})
        )

    results: dict = {}
    per_type: dict = defaultdict(lambda: defaultdict(dict))
    per_scenario: list[dict] = []
    type_totals: dict = defaultdict(int)
    for s in scenarios.values():
        type_totals[s["type"]] += 1

    for mode in MODES:
        alert_times: dict[str, list] = {}
        pred_days: set = set()
        for uid, inds in by_user.items():
            pts = [(t, sc) for t, sc, _ in build_series(inds, mode, cfg) if sc >= thr]
            alert_times[uid] = [t for t, _ in pts]
            pred_days.update((uid, t.date()) for t, _ in pts)
        pred_in_eval = pred_days & eval_days
        tp = len(pred_in_eval & pos_days)
        fp = len(pred_in_eval - pos_days)
        fn = len(pos_days - pred_in_eval)
        tn = len(eval_days) - tp - fp - fn

        latencies, detected = [], 0
        type_detect: dict = defaultdict(list)
        for sid, s in scenarios.items():
            hits = [t for t in alert_times.get(s["user_id"], []) if s["start"] <= t <= s["end"] + window]
            row = {"scenario_id": sid, "type": s["type"], "user_id": s["user_id"], "mode": mode,
                   "start": s["start"].isoformat(), "detected": bool(hits), "latency_minutes": None}
            if hits:
                detected += 1
                lat = round((min(hits) - s["start"]).total_seconds() / 60.0, 1)
                row["latency_minutes"] = lat
                latencies.append(lat)
                type_detect[s["type"]].append(lat)
            per_scenario.append(row)
        for typ, total in type_totals.items():
            lats = type_detect.get(typ, [])
            per_type[typ][mode] = {
                "detected": len(lats), "total": total,
                "median_latency_minutes": round(statistics.median(lats), 1) if lats else None,
            }
        results[mode] = {
            **_metrics(tp, fp, fn, tn),
            "scenarios_detected": detected,
            "scenarios_total": len(scenarios),
            "scenario_detection_rate": round(detected / len(scenarios), 4) if scenarios else 0.0,
            "mean_detection_latency_minutes": round(statistics.mean(latencies), 1) if latencies else None,
            "median_detection_latency_minutes": round(statistics.median(latencies), 1) if latencies else None,
        }

    payload = {
        "created_at": utcnow().isoformat(),
        "alert_threshold": thr,
        "unit_of_analysis": "user-day (days after each user's baseline learning window)",
        "dataset": {
            "users_evaluated": len({u for u, _ in eval_days}),
            "evaluated_user_days": len(eval_days),
            "malicious_user_days": len(pos_days),
            "scenarios": len(scenarios),
        },
        "modes": results,
        "by_scenario_type": {t: dict(m) for t, m in per_type.items()},
        "per_scenario": per_scenario,
    }
    if store:
        db.add(EvaluationRun(run_by=run_by, results=payload))
        db.commit()
    return payload
