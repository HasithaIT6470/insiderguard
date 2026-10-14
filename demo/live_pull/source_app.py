"""Acme FileVault - a FICTIONAL file-sharing app used only to demonstrate live pulling.

It plays the role of "another app" in the company (like a file server or cloud drive).
It does two things:
  1. Generates synthetic activity for 5 employees in the background (normal work).
  2. Exposes a read-only audit-log API that InsiderGuard's connector pulls from:

       GET /api/v1/audit-logs?cursor=<last id seen>&limit=100
       Authorization: Bearer <read-only token>

You can also trigger attacks from the console page at http://localhost:9000/

Run:   python source_app.py            (port 9000)
Clock: the demo clock starts at 09:50 UTC today and runs 60x faster than real time
       (1 real second = 1 simulated minute), so each simulated shift (09:50-13:30) lasts about 3.7 real minutes.
       All data is synthetic. No real users, files or credentials.
"""
from __future__ import annotations

import asyncio
import os
import random
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

READ_TOKEN = os.getenv("FILEVAULT_READ_TOKEN", "demo-readonly-token")
SPEED = float(os.getenv("FILEVAULT_SPEED", "60"))  # simulated seconds per real second
TICK_SECONDS = float(os.getenv("FILEVAULT_TICK", "2"))  # real seconds between normal events

# Employees that already have a 14-day baseline in the InsiderGuard seed data (python -m app.seed).
EMPLOYEES = {
    "u006": {"dept": "Finance", "device": "LT-U006", "types": ["finance_report", "ledger", "invoice", "general"]},
    "u007": {"dept": "HR", "device": "LT-U007", "types": ["hr_record", "policy_doc", "payroll_sheet", "general"]},
    "u008": {"dept": "Engineering", "device": "LT-U008", "types": ["source_code", "design_doc", "build_artifact", "general"]},
    "u009": {"dept": "Sales", "device": "LT-U009", "types": ["crm_record", "proposal", "price_list", "general"]},
    "u010": {"dept": "IT", "device": "LT-U010", "types": ["config_file", "log_archive", "runbook", "general"]},
}

LOG: list[dict] = []  # the app's own audit log (append-only)
_lock = threading.Lock()
_rng = random.Random(7)
_real_start = datetime.now(timezone.utc)
_sim_start = _real_start.replace(hour=9, minute=50, second=0, microsecond=0)
_logged_in: set[tuple[str, str]] = set()


def sim_now() -> datetime:
    """Demo clock: a simulated shift from 09:50 to 13:30, then the next day starts at 09:50.
    (A short shift keeps normal daily volumes inside the seeded baselines however long the demo runs.)"""
    elapsed = (datetime.now(timezone.utc) - _real_start).total_seconds() * SPEED
    day_len = (3 * 60 + 40) * 60  # 09:50 -> 13:30
    day, offset = divmod(elapsed, day_len)
    return _sim_start + timedelta(days=day, seconds=offset)


def record(user: str, action: str, path: str | None = None, classification: str | None = None,
           device: str | None = None, outcome: str = "allowed", size_bytes: int = 0, at: datetime | None = None):
    """Append one entry to the audit log, in Acme FileVault's OWN format (not InsiderGuard's)."""
    emp = EMPLOYEES[user]
    with _lock:
        entry = {
            "id": len(LOG) + 1,
            "occurredAt": (at or sim_now()).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "actor": {"employeeId": user, "email": f"{user}@acme.example", "department": emp["dept"]},
            "action": action,
            "target": {"path": path, "classification": classification} if path else None,
            "client": {"deviceName": device or emp["device"], "ip": f"10.20.{int(user[1:])}.14"},
            "outcome": outcome,
            "bytes": int(size_bytes),
        }
        LOG.append(entry)
    return entry


# --------------------------------------------------------------------------- normal activity
def normal_event():
    user = _rng.choice(list(EMPLOYEES))
    emp = EMPLOYEES[user]
    day = sim_now().date().isoformat()
    if (user, day) not in _logged_in:  # first activity of the day is a login
        _logged_in.add((user, day))
        return record(user, "auth.login", outcome="success")
    rtype = _rng.choice(emp["types"])
    path = f"/{emp['dept'].lower()}/{rtype}_{_rng.randint(100, 999)}.docx"
    if _rng.random() < 0.08:
        return record(user, "file.download", path, rtype, size_bytes=_rng.uniform(0.5, 3) * 1024 * 1024)
    return record(user, "file.view", path, rtype)


async def background_activity():
    while True:
        normal_event()
        await asyncio.sleep(TICK_SECONDS)


# --------------------------------------------------------------------------- attack scenarios
def scenario_exfiltration():
    """u008 opens a restricted file, then downloads three very large source-code archives."""
    t = sim_now()
    record("u008", "file.view", "/restricted/m_and_a_pipeline_q4.docx", "restricted", at=t)
    for i, mb in enumerate((720, 810, 690), start=1):
        record("u008", "file.download", f"/engineering/source_code/full_repo_export_{i}.zip", "source_code",
               size_bytes=mb * 1024 * 1024, at=t + timedelta(minutes=2 * i))


def scenario_honeytoken():
    """u010 opens a decoy file that no legitimate job needs (registered as a honeytoken in InsiderGuard)."""
    t = sim_now()
    record("u010", "file.view", "/it/decoy/domain_admin_credentials.txt", "config_file", at=t)
    record("u010", "file.download", "/it/decoy/domain_admin_credentials.txt", "config_file",
           size_bytes=4096, at=t + timedelta(minutes=1))


def scenario_account_takeover():
    """Someone guesses u007's password, logs in from an unknown laptop, probes payroll and takes a copy."""
    t = sim_now()
    for i in range(6):
        record("u007", "auth.login", device="LT-UNKNOWN-77", outcome="failure", at=t + timedelta(seconds=20 * i))
    t += timedelta(minutes=3)
    record("u007", "auth.login", device="LT-UNKNOWN-77", outcome="success", at=t)
    for i in range(3):
        record("u007", "file.view", f"/hr/restricted_payroll/salaries_{i}.xlsx", "payroll_sheet",
               device="LT-UNKNOWN-77", outcome="denied", at=t + timedelta(minutes=1 + i))
    record("u007", "file.download", "/hr/payroll_sheet_master.xlsx", "payroll_sheet", device="LT-UNKNOWN-77",
           size_bytes=160 * 1024 * 1024, at=t + timedelta(minutes=6))


SCENARIOS = {"exfiltration": scenario_exfiltration, "honeytoken": scenario_honeytoken,
             "account_takeover": scenario_account_takeover}


# --------------------------------------------------------------------------- API
@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(background_activity())
    yield
    task.cancel()


app = FastAPI(title="Acme FileVault (fictional demo app)", lifespan=lifespan)


def require_read_token(authorization: str = Header(default="")):
    if authorization != f"Bearer {READ_TOKEN}":
        raise HTTPException(401, "missing or invalid API token")


@app.get("/api/v1/audit-logs", dependencies=[Depends(require_read_token)])
def audit_logs(cursor: int = Query(0, ge=0, description="return entries with id greater than this"),
               limit: int = Query(100, ge=1, le=500)):
    """Cursor-paginated audit log. The connector remembers next_cursor and asks again from there."""
    with _lock:
        page = [e for e in LOG if e["id"] > cursor][:limit]
        has_more = bool(page) and page[-1]["id"] < LOG[-1]["id"]
    return {"data": page, "next_cursor": page[-1]["id"] if page else cursor, "has_more": has_more}


@app.post("/simulate/{name}")
def simulate(name: str):
    if name not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario; choose from {sorted(SCENARIOS)}")
    before = len(LOG)
    SCENARIOS[name]()
    return {"scenario": name, "entries_added": len(LOG) - before}


@app.get("/", response_class=HTMLResponse)
def console():
    rows = "".join(
        f"<tr class='{'bad' if e['outcome'] != 'allowed' and e['outcome'] != 'success' else ''}'>"
        f"<td>{e['id']}</td><td>{e['occurredAt'][11:16]}</td><td>{e['actor']['employeeId']}</td>"
        f"<td>{e['action']}</td><td>{(e['target'] or {}).get('path') or ''}</td>"
        f"<td>{e['client']['deviceName']}</td><td>{e['outcome']}</td><td>{e['bytes'] / 1048576:.1f}</td></tr>"
        for e in reversed(LOG[-25:])
    )
    buttons = "".join(
        f"<button onclick=\"fetch('/simulate/{k}',{{method:'POST'}}).then(()=>location.reload())\">{k.replace('_', ' ')}</button>"
        for k in SCENARIOS)
    return f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=3>
<title>Acme FileVault console</title>
<style>body{{font:14px system-ui;margin:24px;background:#f6f7f9;color:#1d2330}}table{{border-collapse:collapse;width:100%;background:#fff}}
td,th{{padding:4px 8px;border-bottom:1px solid #e3e6ec;text-align:left;font-variant-numeric:tabular-nums}}
tr.bad td{{color:#b3261e}}button{{margin-right:8px;padding:6px 12px;border:1px solid #b3261e;background:#fff;color:#b3261e;border-radius:6px;cursor:pointer}}</style>
<h1>Acme FileVault <small style="color:#777">fictional demo app</small></h1>
<p>Demo clock: <b>{sim_now():%Y-%m-%d %H:%M} UTC</b> · {len(LOG)} audit entries · InsiderGuard pulls from
<code>/api/v1/audit-logs</code></p>
<p>Simulate an insider attack: {buttons}</p>
<table><tr><th>id</th><th>time</th><th>user</th><th>action</th><th>file</th><th>device</th><th>outcome</th><th>MB</th></tr>{rows}</table>"""


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("FILEVAULT_PORT", "9000")), log_level="warning")
