"""AI layer (3.8): turns a deterministic, anonymized evidence breakdown into an analyst-friendly
explanation. The model never sees real identifiers and never influences the score."""
from __future__ import annotations

import hashlib
import logging

import httpx

from . import config

log = logging.getLogger("insiderguard.ai")

DISCLAIMER = (
    "AI-generated supporting explanation. It is not the source of the risk score, which is computed "
    "deterministically from the evidence shown, and it is not proof of malicious intent."
)

SYSTEM_PROMPT = (
    "You assist a security analyst reviewing an insider-risk alert from a prototype UEBA system. "
    "Using ONLY the structured evidence provided, write a short explanation (max 120 words) of why the "
    "alert was raised and what an analyst might check first. Do not change or re-estimate the score, do not "
    "speculate about motives, do not accuse the user, and state that the evidence is an investigative lead only."
)


def ai_configured() -> bool:
    return bool(config.AI_API_KEY)


def pseudonym(user_id: str) -> str:
    return "SUBJECT-" + hashlib.sha256(f"ig:{user_id}".encode()).hexdigest()[:6].upper()


def anonymize_alert(alert, department_hint: bool = False) -> dict:
    """Structured, anonymized summary (REQ-08-01): no user id, resource names or device ids."""
    indicators = []
    for item in alert.breakdown or []:
        d = item.get("detail") or {}
        safe = {k: v for k, v in d.items()
                if k in ("observed", "baseline_mean", "baseline_std", "z", "metric", "volume_mb", "threshold_mb",
                         "daily_total_mb", "failures", "denials", "hour", "distinct_categories", "event_type")
                and not (k == "observed" and d.get("metric") in ("device_usage", "resource_type"))}
        indicators.append({"category": item["category"], "indicator": item["name"], "source": item["source"],
                           "weight": item["weight"], "facts": safe})
    return {
        "subject": pseudonym(alert.user_id),
        "risk_score": alert.peak_score,
        "risk_category": alert.category,
        "incident_duration_minutes": int((alert.last_time - alert.start_time).total_seconds() // 60),
        "start_hour_of_day": alert.start_time.hour,
        "indicators": indicators,
    }


def generate_explanation(summary: dict) -> tuple[str | None, str | None]:
    """Returns (text, error). Never raises."""
    if not ai_configured():
        return None, "AI API key not configured"
    try:
        resp = httpx.post(
            config.AI_API_URL,
            headers={"x-api-key": config.AI_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model": config.AI_MODEL,
                "max_tokens": 400,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": f"Evidence (JSON):\n{summary}"}],
            },
            timeout=config.AI_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if not text:
            return None, "empty response from AI API"
        return text, None
    except Exception as exc:  # noqa: BLE001 - AI is optional; any failure degrades gracefully
        log.warning("AI explanation failed: %s", exc)
        return None, f"{type(exc).__name__}: {exc}"[:200]


def explain_alert(db, alert) -> bool:
    """Request + attach a narrative. Returns True if a narrative was stored (REQ-08-04: failures only log)."""
    from .models import utcnow

    text, err = generate_explanation(anonymize_alert(alert))
    if text:
        alert.narrative, alert.narrative_status = text, "generated"
    else:
        alert.narrative_status = "unavailable"
        log.warning("alert %s: no narrative (%s)", alert.id, err)
    alert.updated_at = utcnow()
    db.commit()
    return bool(text)
