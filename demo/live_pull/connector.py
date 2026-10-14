"""InsiderGuard pull connector for Acme FileVault (demo).

Every few seconds it:
  1. PULLS   new audit entries from the source app    GET  {source}/api/v1/audit-logs?cursor=N
  2. MAPS    each entry into InsiderGuard's event schema (timestamp, user_id, event_type, ...)
  3. PUSHES  the batch into InsiderGuard                 POST {insiderguard}/api/events
  4. SAVES   the cursor (checkpoint) so the next pull starts where this one ended
  5. SHOWS   any new or changed alerts                  GET  {insiderguard}/api/alerts

Run:   python connector.py
Env:   SOURCE_URL (default http://127.0.0.1:9000)   SOURCE_TOKEN (default demo-readonly-token)
       IG_URL (default http://127.0.0.1:8000)       IG_USER / IG_PASSWORD (default admin / Admin#12345)
       POLL_SECONDS (default 5)                     STATE_FILE (default connector_state.json)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

SOURCE_URL = os.getenv("SOURCE_URL", "http://127.0.0.1:9000").rstrip("/")
SOURCE_TOKEN = os.getenv("SOURCE_TOKEN", "demo-readonly-token")
IG_URL = os.getenv("IG_URL", "http://127.0.0.1:8000").rstrip("/")
IG_USER = os.getenv("IG_USER", "admin")
IG_PASSWORD = os.getenv("IG_PASSWORD", "Admin#12345")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "5"))
STATE_FILE = Path(os.getenv("STATE_FILE", "connector_state.json"))
MAX_LOOPS = int(os.getenv("MAX_LOOPS", "0"))  # 0 = run forever (used by tests)

# Acme FileVault action  ->  InsiderGuard event_type
ACTION_MAP = {
    "auth.login": "auth",
    "file.view": "file_access",
    "file.download": "download",
}
OUTCOME_MAP = {"success": "success", "allowed": "success", "failure": "fail", "denied": "denied"}


def to_insiderguard(entry: dict) -> dict | None:
    """Field mapping: the source app's format on the left, InsiderGuard's schema on the right."""
    event_type = ACTION_MAP.get(entry["action"])
    if event_type is None:
        return None  # an action InsiderGuard does not monitor (e.g. settings changes): skip it
    result = OUTCOME_MAP.get(entry["outcome"], "success")
    if result == "denied":
        event_type = "denied_access"
    target = entry.get("target") or {}
    return {
        "timestamp": entry["occurredAt"],
        "user_id": entry["actor"]["employeeId"],
        "department": entry["actor"].get("department"),
        "event_type": event_type,
        "resource": target.get("path"),
        "resource_type": target.get("classification"),
        "device_id": entry["client"]["deviceName"],
        "result": result,
        "volume_mb": round(entry.get("bytes", 0) / (1024 * 1024), 3),
    }


def load_cursor() -> int:
    try:
        return int(json.loads(STATE_FILE.read_text())["cursor"])
    except (FileNotFoundError, KeyError, ValueError):
        return 0


def save_cursor(cursor: int) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"cursor": cursor, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    tmp.replace(STATE_FILE)  # atomic: never leaves a half-written checkpoint


class InsiderGuard:
    def __init__(self, client: httpx.Client):
        self.c, self.token = client, None

    def login(self):
        r = self.c.post(f"{IG_URL}/api/auth/login", data={"username": IG_USER, "password": IG_PASSWORD})
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def call(self, method: str, path: str, **kw):
        for attempt in (1, 2):
            if not self.token:
                self.login()
            r = self.c.request(method, f"{IG_URL}{path}", headers={"Authorization": f"Bearer {self.token}"}, **kw)
            if r.status_code == 401 and attempt == 1:  # JWT expired (60 min): log in again and retry once
                self.token = None
                continue
            r.raise_for_status()
            return r.json()


def main():
    client = httpx.Client(timeout=60)
    ig = InsiderGuard(client)
    cursor = load_cursor()
    while True:  # wait until InsiderGuard is up, then remember which alerts already exist
        try:
            seen_alerts = {a["id"]: a["peak_score"] for a in ig.call("GET", "/api/alerts", params={"limit": 1000})}
            break
        except httpx.HTTPError as exc:
            print(f"waiting for InsiderGuard at {IG_URL} ({exc.__class__.__name__}), retrying in {POLL_SECONDS:g}s")
            if MAX_LOOPS:
                return
            time.sleep(POLL_SECONDS)
    print(f"connector started · source={SOURCE_URL} · insiderguard={IG_URL} · resuming from cursor {cursor}")
    loops = 0
    while True:
        loops += 1
        try:
            pulled, batch, next_cursor = 0, [], cursor
            while True:  # follow pagination until the source says there is nothing more
                r = client.get(f"{SOURCE_URL}/api/v1/audit-logs", params={"cursor": next_cursor, "limit": 200},
                               headers={"Authorization": f"Bearer {SOURCE_TOKEN}"})
                r.raise_for_status()
                page = r.json()
                pulled += len(page["data"])
                batch += [m for e in page["data"] if (m := to_insiderguard(e))]
                next_cursor = page["next_cursor"]
                if not page["has_more"]:
                    break
            if batch:
                res = ig.call("POST", "/api/events", json={"events": batch})
                print(f"[pull] cursor {cursor}->{next_cursor}: {pulled} new entries, sent {len(batch)} · "
                      f"InsiderGuard accepted {res['accepted']}, rejected {res['rejected']} · users {res['affected_users']}")
            else:
                print(f"[pull] cursor {cursor}: nothing new")
            cursor = next_cursor
            save_cursor(cursor)  # checkpoint only AFTER InsiderGuard accepted the batch

            for a in ig.call("GET", "/api/alerts", params={"limit": 1000}):
                old = seen_alerts.get(a["id"])
                if old is None or a["peak_score"] > old:
                    kind = "NEW ALERT" if old is None else "ALERT UPDATED"
                    reasons = ", ".join(f"{b['name']}(+{b['weight']:g})" for b in a["breakdown"])
                    print(f"  >>> {kind} #{a['id']} {a['user_id']} score {a['peak_score']} {a['category']}: {reasons}")
                    seen_alerts[a["id"]] = a["peak_score"]
        except httpx.HTTPError as exc:
            print(f"[pull] error, will retry next cycle: {exc}", file=sys.stderr)  # cursor not advanced
        if MAX_LOOPS and loops >= MAX_LOOPS:
            break
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
