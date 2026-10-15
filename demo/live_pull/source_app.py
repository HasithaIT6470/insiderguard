"""Acme FileVault - a FICTIONAL file-sharing app used only to demonstrate live pulling.

It plays the role of "another app" in the company (like a file server or cloud drive).
It does three things:
  1. Generates synthetic activity for 5 employees in the background (normal work).
  2. Exposes a read-only audit-log API that InsiderGuard's connector pulls from:

       GET /api/v1/audit-logs?cursor=<last id seen>&limit=100
       Authorization: Bearer <read-only token>

  3. Serves a live console at http://localhost:9000/ with the simulation controls
     (Pause, Pull every, InsiderGuard offline, Reset) and the attack buttons.

The controls travel to the connector through a small DEMO-ONLY control channel
(/demo/control and /demo/connector-status). A real source app would not have these;
a real connector keeps its settings in its own configuration.

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
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

READ_TOKEN = os.getenv("FILEVAULT_READ_TOKEN", "demo-readonly-token")
SPEED = float(os.getenv("FILEVAULT_SPEED", "60"))  # simulated seconds per real second
TICK_SECONDS = float(os.getenv("FILEVAULT_TICK", "2"))  # real seconds between normal events
SHIFT_SECONDS = (3 * 60 + 40) * 60  # simulated shift 09:50 -> 13:30
POLL_CHOICES = (3, 5, 10)

# Employees that already have a 14-day baseline in the InsiderGuard seed data (python -m app.seed).
EMPLOYEES = {
    "u006": {"dept": "Finance", "device": "LT-U006", "types": ["finance_report", "ledger", "invoice", "general"]},
    "u007": {"dept": "HR", "device": "LT-U007", "types": ["hr_record", "policy_doc", "payroll_sheet", "general"]},
    "u008": {"dept": "Engineering", "device": "LT-U008", "types": ["source_code", "design_doc", "build_artifact", "general"]},
    "u009": {"dept": "Sales", "device": "LT-U009", "types": ["crm_record", "proposal", "price_list", "general"]},
    "u010": {"dept": "IT", "device": "LT-U010", "types": ["config_file", "log_archive", "runbook", "general"]},
}

_lock = threading.Lock()
_rng = random.Random(7)
_SIM_START = datetime.now(timezone.utc).replace(hour=9, minute=50, second=0, microsecond=0)

# ---- simulation state (all guarded by _lock)
LOG: list[dict] = []  # the app's own audit log (append-only within a run)
ATTACK_IDS: set[int] = set()  # entries created by attack buttons (shown in red on the console only)
_logged_in: set[tuple[str, str]] = set()
_sim_elapsed = 0.0  # simulated seconds since _SIM_START (only advances while running)
_since_normal = 0.0
CONTROL = {"paused": False, "poll_seconds": 5, "ig_offline": False, "epoch": int(time.time())}
CONNECTOR: dict = {}  # last status reported by the connector


def sim_now() -> datetime:
    """Demo clock: a simulated shift from 09:50 to 13:30, then the next day starts at 09:50.
    (A short shift keeps normal daily volumes inside the seeded baselines however long the demo runs.)"""
    day, offset = divmod(_sim_elapsed, SHIFT_SECONDS)
    return _SIM_START + timedelta(days=day, seconds=offset)


def record(user: str, action: str, path: str | None = None, classification: str | None = None,
           device: str | None = None, outcome: str = "allowed", size_bytes: float = 0, at: datetime | None = None,
           attack: bool = False) -> dict:
    """Append one entry to the audit log, in Acme FileVault's OWN format (not InsiderGuard's). Caller holds _lock."""
    emp = EMPLOYEES[user]
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
    if attack:
        ATTACK_IDS.add(entry["id"])
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
    """Advances the demo clock and adds normal work, but only while the simulation is running."""
    global _sim_elapsed, _since_normal
    last = time.monotonic()
    while True:
        await asyncio.sleep(0.25)
        now = time.monotonic()
        dt, last = now - last, now
        with _lock:
            if CONTROL["paused"]:
                continue
            _sim_elapsed += dt * SPEED
            _since_normal += dt
            if _since_normal >= TICK_SECONDS:
                _since_normal -= TICK_SECONDS
                normal_event()


# --------------------------------------------------------------------------- attack scenarios
def scenario_exfiltration():
    """u008 opens a restricted file, then downloads three very large source-code archives."""
    t = sim_now()
    record("u008", "file.view", "/restricted/m_and_a_pipeline_q4.docx", "restricted", at=t, attack=True)
    for i, mb in enumerate((720, 810, 690), start=1):
        record("u008", "file.download", f"/engineering/source_code/full_repo_export_{i}.zip", "source_code",
               size_bytes=mb * 1024 * 1024, at=t + timedelta(minutes=2 * i), attack=True)


def scenario_honeytoken():
    """u010 opens a decoy file that no legitimate job needs (registered as a honeytoken in InsiderGuard)."""
    t = sim_now()
    record("u010", "file.view", "/it/decoy/domain_admin_credentials.txt", "config_file", at=t, attack=True)
    record("u010", "file.download", "/it/decoy/domain_admin_credentials.txt", "config_file",
           size_bytes=4096, at=t + timedelta(minutes=1), attack=True)


def scenario_account_takeover():
    """Someone guesses u007's password, logs in from an unknown laptop, probes payroll and takes a copy."""
    t = sim_now()
    for i in range(6):
        record("u007", "auth.login", device="LT-UNKNOWN-77", outcome="failure", at=t + timedelta(seconds=20 * i),
               attack=True)
    t += timedelta(minutes=3)
    record("u007", "auth.login", device="LT-UNKNOWN-77", outcome="success", at=t, attack=True)
    for i in range(3):
        record("u007", "file.view", f"/hr/restricted_payroll/salaries_{i}.xlsx", "payroll_sheet",
               device="LT-UNKNOWN-77", outcome="denied", at=t + timedelta(minutes=1 + i), attack=True)
    record("u007", "file.download", "/hr/payroll_sheet_master.xlsx", "payroll_sheet", device="LT-UNKNOWN-77",
           size_bytes=160 * 1024 * 1024, at=t + timedelta(minutes=6), attack=True)


SCENARIOS = {
    "honeytoken": (scenario_honeytoken, "Honeytoken touch",
                   "u010 opens a decoy credentials file, then downloads it."),
    "exfiltration": (scenario_exfiltration, "Bulk exfiltration",
                     "u008 opens a restricted file, then downloads three huge source-code archives."),
    "account_takeover": (scenario_account_takeover, "Account takeover",
                         "Someone guesses u007's password, logs in from an unknown laptop, probes payroll and copies it."),
}


# --------------------------------------------------------------------------- API used by the connector
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


# --------------------------------------------------------------------------- demo-only control channel
@app.get("/demo/control")
def get_control():
    """Read by the connector before every pull: pause, pull interval, simulated outage, and the run number."""
    with _lock:
        return dict(CONTROL)


@app.post("/demo/control")
def set_control(body: dict = Body(...)):
    with _lock:
        if "paused" in body:
            CONTROL["paused"] = bool(body["paused"])
        if "ig_offline" in body:
            CONTROL["ig_offline"] = bool(body["ig_offline"])
        if "poll_seconds" in body:
            if int(body["poll_seconds"]) not in POLL_CHOICES:
                raise HTTPException(422, f"poll_seconds must be one of {POLL_CHOICES}")
            CONTROL["poll_seconds"] = int(body["poll_seconds"])
        return dict(CONTROL)


@app.post("/demo/reset")
def reset():
    """Clear FileVault's log and start a fresh simulated day. The new run number tells the connector to restart
    from cursor 0. InsiderGuard keeps the alerts it already raised (reseed the backend to clear those)."""
    global _sim_elapsed, _since_normal
    with _lock:
        LOG.clear()
        ATTACK_IDS.clear()
        _logged_in.clear()
        day = int(_sim_elapsed // SHIFT_SECONDS) + 1  # next day, so InsiderGuard's daily totals start from zero
        _sim_elapsed, _since_normal = day * SHIFT_SECONDS, 0.0
        CONTROL.update(paused=False, ig_offline=False, epoch=CONTROL["epoch"] + 1)
        CONNECTOR.clear()
        return {"reset": True, **CONTROL, "clock": sim_now().strftime("%Y-%m-%d %H:%M")}


@app.post("/demo/connector-status")
def connector_status(body: dict = Body(...)):
    with _lock:
        CONNECTOR.clear()
        CONNECTOR.update(body, seen_at=time.time())
    return {"ok": True}


@app.post("/simulate/{name}")
def simulate(name: str):
    if name not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario; choose from {sorted(SCENARIOS)}")
    with _lock:
        before = len(LOG)
        CONTROL["paused"] = False  # an attack needs the clock running
        SCENARIOS[name][0]()
        return {"scenario": name, "entries_added": len(LOG) - before, "description": SCENARIOS[name][2]}


@app.get("/demo/state")
def state():
    """Everything the console needs, refreshed about once a second."""
    with _lock:
        conn = dict(CONNECTOR)
        if conn:
            conn["age_seconds"] = round(time.time() - conn.pop("seen_at"), 1)
        return {
            "clock": sim_now().strftime("%Y-%m-%d %H:%M"),
            "total": len(LOG),
            "control": dict(CONTROL),
            "connector": conn or None,
            "entries": [{**e, "attack": e["id"] in ATTACK_IDS} for e in LOG[-40:]][::-1],
            "scenarios": {k: {"label": v[1], "description": v[2]} for k, v in SCENARIOS.items()},
        }


# --------------------------------------------------------------------------- console page
CONSOLE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Acme FileVault console</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600;700&display=swap">
<style>
:root{--bg:#f3f5f8;--surface:#fff;--sunken:#eaeef4;--ink:#18202e;--muted:#5a6577;--line:#d9dfe8;--accent:#2b55c9;--accent-soft:#e4ebfb;
--code-bg:#f0f3f8;--ok:#217a4b;--crit:#b0201a;--crit-soft:#fbe0de;--warn:#9a6400;
--body:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0e1219;--surface:#161c26;--sunken:#1d2531;--ink:#e5e9f0;--muted:#98a2b3;--line:#2a3342;
--accent:#84a6ff;--accent-soft:#1f2b47;--code-bg:#121822;--ok:#5cc98f;--crit:#ff7b72;--crit-soft:#431c1b;--warn:#e7b24f;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--body);padding:28px max(16px,env(safe-area-inset-left)) 48px}
.wrap{max-width:1100px;margin:0 auto;display:grid;gap:18px}
h1,h2{margin:0;line-height:1.2}h1{font-size:1.5rem}h2{font-size:1.25rem}
.eyebrow{font:500 .74rem var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.muted{color:var(--muted)}p{margin:0;max-width:72ch}code{font-family:var(--mono);font-size:.86em}
.toolbar{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.spacer{flex:1}.clock{font:.9rem var(--mono);font-variant-numeric:tabular-nums}
button,select{font:inherit;font-size:.9rem;border-radius:6px;padding:6px 12px;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer}
select{padding:5px 8px}button:hover{border-color:var(--accent)}
button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button.primary{background:var(--accent);border-color:var(--accent);color:var(--surface);font-weight:600}
button.attack{border-color:var(--crit);color:var(--crit);background:transparent}button.attack:hover{background:var(--crit-soft)}
label.inline{display:inline-flex;gap:6px;align-items:center;font-size:.9rem}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px;display:grid;gap:12px;min-width:0}
.sub{font:.72rem var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.attacks{display:flex;flex-wrap:wrap;gap:8px}
.status{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;font-size:.88rem}
.dot{width:9px;height:9px;border-radius:50%;background:var(--muted);flex:none}.dot.ok{background:var(--ok)}.dot.down{background:var(--crit)}.dot.warn{background:var(--warn)}
.meta{font:.78rem var(--mono);color:var(--muted)}
.bar{height:6px;border-radius:3px;background:var(--sunken);overflow:hidden;flex:1;min-width:120px}.bar>i{display:block;height:100%;width:0;background:var(--accent)}
.feed{font:.78rem var(--mono);font-variant-numeric:tabular-nums;border:1px solid var(--line);border-radius:6px;background:var(--code-bg);max-height:460px;overflow:auto}
.row{display:grid;grid-template-columns:3.4em 3.4em 3.4em minmax(0,1fr);gap:8px;padding:5px 10px;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:0}.row .what{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row.pulled{color:var(--muted)}.row.fresh{background:var(--accent-soft)}.row.bad{color:var(--crit)}
.legend{font-size:.78rem;color:var(--muted);display:flex;gap:14px;flex-wrap:wrap}
.legend span::before{content:"";display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.l-new::before{background:var(--accent-soft);border:1px solid var(--accent)}.l-old::before{background:var(--code-bg);border:1px solid var(--line)}.l-bad::before{background:var(--crit)}
.note{font-size:.84rem;color:var(--muted)}
</style></head><body><div class="wrap">

<header style="display:grid;gap:4px">
  <span class="eyebrow">Fictional demo app · synthetic data only</span>
  <h1>Acme FileVault</h1>
</header>

<section style="display:grid;gap:12px">
  <h2>Live simulation</h2>
  <p class="muted">Everything here runs locally on synthetic data. <strong>Acme FileVault</strong> is a fictional file-sharing app standing in for any company system. Its demo clock runs <span id="speed">60</span>× faster than real time. Trigger an attack and watch the next pull carry it into InsiderGuard.</p>

  <div class="toolbar" role="group" aria-label="Simulation controls">
    <button id="btnRun" class="primary" type="button">Pause</button>
    <label class="inline" for="selPoll">Pull every
      <select id="selPoll"><option value="3">3 s</option><option value="5">5 s</option><option value="10">10 s</option></select>
    </label>
    <label class="inline" for="chkDown"><input id="chkDown" type="checkbox"> InsiderGuard offline</label>
    <button id="btnReset" type="button" title="Clears FileVault's log and starts a fresh simulated day">Reset</button>
    <span class="spacer"></span>
    <span class="clock" id="clock">connecting…</span>
  </div>
</section>

<div class="panel">
  <span class="sub">Connector</span>
  <div class="status"><span class="dot" id="dot"></span><strong id="connState">Waiting for the connector</strong><span class="meta" id="connMeta">Start it with: python connector.py</span></div>
  <div class="status"><span class="meta" id="nextPoll">next pull in —</span><div class="bar"><i id="pollBar"></i></div></div>
</div>

<div class="panel">
  <span class="sub">Simulate an insider attack</span>
  <div class="attacks" id="attacks"></div>
  <p class="note" id="scMsg">Normal work by five employees is logged automatically.</p>
</div>

<div class="panel">
  <span class="sub">Audit log (newest first)</span>
  <div class="feed" id="feed"></div>
  <div class="legend"><span class="l-new">waiting for next pull</span><span class="l-old">already pulled</span><span class="l-bad">simulated attack</span></div>
</div>

<p class="note">The controls reach the connector through a demo-only control channel (<code>/demo/control</code>). Reset clears FileVault and starts a fresh simulated day. InsiderGuard keeps the alerts it already raised; reseed the backend to clear them.</p>
</div>

<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let S = null, attacksDrawn = false, busy = false;

async function post(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
  return r.json();
}
async function control(change) { busy = true; try { await post('/demo/control', change); } finally { busy = false; refresh(); } }

$('btnRun').onclick = () => control({paused: !S.control.paused});
$('selPoll').onchange = (e) => control({poll_seconds: Number(e.target.value)});
$('chkDown').onchange = (e) => control({ig_offline: e.target.checked});
$('btnReset').onclick = async () => { const r = await post('/demo/reset'); $('scMsg').textContent = `Reset: FileVault's log is empty and the clock moved to ${r.clock} UTC (a fresh simulated day).`; refresh(); };

function drawAttacks(sc) {
  $('attacks').innerHTML = Object.entries(sc).map(([k, v]) => `<button class="attack" type="button" data-sc="${k}">${esc(v.label)}</button>`).join('');
  document.querySelectorAll('[data-sc]').forEach((b) => b.onclick = async () => {
    const r = await post('/simulate/' + b.dataset.sc);
    $('scMsg').textContent = `${r.description} ${r.entries_added} audit entries added. Watch the next pull.`;
    refresh();
  });
  attacksDrawn = true;
}

function render() {
  const c = S.control, conn = S.connector;
  $('btnRun').textContent = c.paused ? 'Resume' : 'Pause';
  if (document.activeElement !== $('selPoll')) $('selPoll').value = String(c.poll_seconds);
  $('chkDown').checked = c.ig_offline;
  $('clock').textContent = `Demo clock ${S.clock} UTC · ${S.total} log entries${c.paused ? ' · paused' : ''}`;
  if (!attacksDrawn) drawAttacks(S.scenarios);

  const stale = !conn || conn.age_seconds > c.poll_seconds * 3 + 5;
  let cls = '', state = 'Waiting for the connector', meta = 'Start it with: python connector.py';
  if (!stale) {
    meta = `cursor ${conn.cursor} · ${conn.ingested_total} events ingested · last pull ${Math.round(conn.age_seconds)}s ago`;
    if (c.paused) { cls = 'warn'; state = 'Connected, paused'; }
    else if (conn.result === 'offline') { cls = 'down'; state = 'InsiderGuard offline (simulated), connector retrying'; }
    else if (conn.result === 'error') { cls = 'down'; state = 'Connector error: ' + conn.message; }
    else { cls = 'ok'; state = 'Connected to InsiderGuard'; }
  }
  $('dot').className = 'dot ' + cls; $('connState').textContent = state; $('connMeta').textContent = meta;
  const left = stale || c.paused ? null : Math.max(0, c.poll_seconds - conn.age_seconds);
  $('nextPoll').textContent = c.paused ? 'paused' : left == null ? 'next pull in —' : `next pull in ${Math.ceil(left)} s`;
  $('pollBar').style.width = left == null ? '0%' : `${Math.min(100, (1 - left / c.poll_seconds) * 100)}%`;

  const cursor = stale ? 0 : conn.cursor;
  $('feed').innerHTML = S.entries.map((e) => {
    const size = e.bytes >= 104858 ? `${(e.bytes / 1048576).toFixed(e.bytes > 10485760 ? 0 : 1)} MB` : `${Math.max(1, Math.round(e.bytes / 1024))} KB`;
    const what = e.action + (e.target ? ' ' + e.target.path : '') + (e.bytes ? ` (${size})` : '')
      + (e.outcome !== 'allowed' && e.outcome !== 'success' ? ` · ${e.outcome}` : '') + (e.client.deviceName.includes('UNKNOWN') ? ` · ${e.client.deviceName}` : '');
    const rc = ['row', e.id > cursor ? 'fresh' : 'pulled', e.attack ? 'bad' : ''].join(' ');
    return `<div class="${rc}"><span>#${e.id}</span><span>${e.occurredAt.slice(11, 16)}</span><span>${e.actor.employeeId}</span><span class="what" title="${esc(what)}">${esc(what)}</span></div>`;
  }).join('') || '<div class="row"><span></span><span></span><span></span><span class="what">no activity yet</span></div>';
}

async function refresh() {
  if (busy) return;
  try { S = await (await fetch('/demo/state')).json(); render(); }
  catch { $('clock').textContent = 'FileVault is not responding'; }
}
refresh(); setInterval(refresh, 1000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def console():
    return CONSOLE_HTML.replace('id="speed">60<', f'id="speed">{SPEED:g}<')


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("FILEVAULT_PORT", "9000")), log_level="warning")
