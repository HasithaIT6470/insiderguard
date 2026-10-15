"""Analyst verdict history and operational feedback, separate from lab evaluation."""
from collections import Counter
from datetime import datetime
from statistics import median

from fastapi import HTTPException
from sqlalchemy import func, select, update

from . import cases
from .models import Alert, AlertAssignment, AlertResolution, CaseEvent, utcnow
from .security import audit

OUTCOMES = ("true_positive", "false_positive", "benign_explained")


def parse_outcomes(value):
    if value is None:
        return []
    values = list(dict.fromkeys(v.strip() for v in value.split(',')))
    if any(v not in OUTCOMES for v in values):
        raise HTTPException(422, "Outcome must be true_positive, false_positive or benign_explained")
    return values


def current_query():
    latest = select(AlertResolution.alert_id, func.max(AlertResolution.id).label("id")).where(
        AlertResolution.reopened_at.is_(None)).group_by(AlertResolution.alert_id).subquery()
    return select(AlertResolution).join(latest, latest.c.id == AlertResolution.id).join(
        Alert, Alert.id == AlertResolution.alert_id).where(Alert.status == "closed")


def current_for(db, alert_ids):
    ids = list(alert_ids)
    if not ids:
        return {}
    return {r.alert_id: r for r in db.scalars(current_query().where(AlertResolution.alert_id.in_(ids)))}


def as_dict(row, history=False):
    if row is None:
        return None
    result = {"id": row.id, "outcome": row.outcome, "note": row.note, "resolved_by": row.resolved_by,
              "resolved_at": row.resolved_at.isoformat()}
    if history:
        result.update(alert_id=row.alert_id, reopened_at=row.reopened_at.isoformat() if row.reopened_at else None,
                      reopened_by=row.reopened_by, reopen_reason=row.reopen_reason)
    return result


def history_for(db, alert_id):
    return [as_dict(r, history=True) for r in db.scalars(select(AlertResolution).where(
        AlertResolution.alert_id == alert_id).order_by(AlertResolution.resolved_at, AlertResolution.id))]


def transition(db, alert, user, assignment, status, outcome=None, note=None, reason=None):
    """Caller holds the alert/assignment locks and commits the whole transition."""
    old = alert.status
    closing = old != "closed" and status == "closed"
    reopening = old == "closed" and status != "closed"
    if not closing and (outcome is not None or note is not None):
        raise HTTPException(422, "Outcome and closing note are only allowed when closing a case; reopen a closed case before resolving it again")
    if not reopening and reason is not None:
        raise HTTPException(422, "A reopen reason is only allowed when reopening a closed case")
    now = utcnow()
    action = None
    row = None
    if closing:
        if outcome not in OUTCOMES:
            raise HTTPException(422, "Closing a case requires an outcome: true_positive, false_positive or benign_explained")
        clean_note = (note or "").strip()
        if not 15 <= len(clean_note) <= 4000:
            raise HTTPException(422, "Closing note must contain 15 to 4000 characters after trimming whitespace")
    elif reopening:
        clean_reason = (reason or "").strip()
        if not 5 <= len(clean_reason) <= 4000:
            raise HTTPException(422, "Reopening a case requires a reason of 5 to 4000 characters after trimming whitespace")
        row = current_for(db, [alert.id]).get(alert.id)
    if old != status:
        # SQLite ignores SELECT FOR UPDATE. Compare-and-set the status as well so
        # two owner tabs cannot create two current resolutions or reopen twice.
        changed = db.execute(update(Alert).where(Alert.id == alert.id, Alert.status == old)
                             .values(status=status, updated_at=now), execution_options={"synchronize_session": False})
        if changed.rowcount != 1:
            raise HTTPException(409, "Case status changed; refresh the case before trying again")
    if closing:
        row = AlertResolution(alert_id=alert.id, outcome=outcome, note=clean_note,
                              resolved_by=user.username, resolved_at=now)
        db.add(row); db.flush()
        cases.record_event(db, alert, "resolved", user, {"outcome": outcome, "resolution_id": row.id,
                           "assigned_at": assignment.assigned_at.isoformat()})
        audit(db, user, "resolve_case", str(alert.id), {"outcome": outcome, "note_length": len(clean_note)})
        action = "resolved"
    elif reopening:
        if row:
            row.reopened_at, row.reopened_by, row.reopen_reason = now, user.username, clean_reason
        cases.record_event(db, alert, "reopened", user, {"reason": clean_reason, "from": old, "to": status,
                           "resolution_id": row.id if row else None})
        audit(db, user, "reopen_case", str(alert.id), {"from": old, "to": status, "reason_length": len(clean_reason)})
        action = "reopened"
    alert.status, alert.updated_at = status, now
    if old != status:
        cases.record_event(db, alert, "status_changed", user,
                           {"from": old, "to": status, **({"transition": action} if action else {})})
    audit(db, user, "change_case_status", str(alert.id), {"from": old, "to": status})


def feedback(db):
    current = {r.alert_id: r for r in db.scalars(current_query())}
    alerts = list(db.scalars(select(Alert).where(Alert.status == "closed")))
    resolved = [a for a in alerts if a.id in current]
    counts = {o: sum(current[a.id].outcome == o for a in resolved) for o in OUTCOMES}
    by_category = {}
    for category in ("Low", "Medium", "High", "Critical"):
        rows = [a for a in resolved if a.category == category]
        tp = sum(current[a.id].outcome == "true_positive" for a in rows)
        by_category[category] = {"resolved_alerts": len(rows), "true_positive": tp,
                                 "alert_precision": tp / len(rows) if rows else None}
    indicators = {o: Counter() for o in ("false_positive", "benign_explained")}
    for alert in resolved:
        outcome = current[alert.id].outcome
        if outcome in indicators:
            indicators[outcome].update({b["name"] for b in alert.breakdown or [] if b.get("name")})
    assignments = cases.owners_for(db, current)
    # Capture assignment time at closure: later administrator reassignments must not
    # rewrite historical time-to-close measurements.
    assigned_at = {}
    for event in db.scalars(select(CaseEvent).where(CaseEvent.action == "resolved",
                             CaseEvent.alert_id.in_(list(current))).order_by(CaseEvent.id)):
        if event.detail.get("assigned_at") and event.detail.get("resolution_id"):
            assigned_at[event.detail["resolution_id"]] = datetime.fromisoformat(event.detail["assigned_at"])
    durations = []
    for alert in resolved:
        row = current[alert.id]
        start = assigned_at.get(row.id)
        if start is None and alert.id in assignments:
            start = assignments[alert.id].assigned_at
        if start is not None and start <= row.resolved_at:
            durations.append((row.resolved_at - start).total_seconds() / 3600)
    what_if = []
    for threshold in (30, 40, 50, 60, 70):
        kept = [a for a in resolved if a.peak_score >= threshold]
        tp = sum(current[a.id].outcome == "true_positive" for a in kept)
        removed = [a for a in resolved if a.peak_score < threshold]
        what_if.append({"threshold": threshold, "alerts_kept": len(kept), "true_positives_kept": tp,
                        "true_positives_lost": counts["true_positive"] - tp,
                        "false_positives_removed": sum(current[a.id].outcome == "false_positive" for a in removed),
                        "benign_removed": sum(current[a.id].outcome == "benign_explained" for a in removed),
                        "resulting_precision": tp / len(kept) if kept else None})
    return {"counts_by_outcome": counts, "closed_with_outcome": len(resolved), "legacy_closed": len(alerts) - len(resolved),
            "alert_precision": counts["true_positive"] / len(resolved) if resolved else None,
            "precision_formula": "true_positive / all currently closed alerts with a current resolution (including false_positive and benign_explained)",
            "precision_by_category": by_category,
            "top_indicators": {o: [{"name": name, "count": count} for name, count in sorted(counter.items(), key=lambda x: (-x[1], x[0]))[:10]]
                               for o, counter in indicators.items()},
            "median_time_to_close_hours": round(median(durations), 4) if durations else None,
            "time_to_close_sample_count": len(durations), "what_if": what_if,
            "scope": "Latest unreopened resolution per currently closed case; historical reopened verdicts are excluded",
            "note": "Recall and F1 cannot be derived from analyst verdicts because missed attacks are never reviewed. Recall/F1 are only available from the labelled lab evaluation. These reviewed-case what-if results are descriptive, not a recommendation to change detection thresholds."}
