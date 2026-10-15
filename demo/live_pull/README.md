# Live pull demo

This demo shows InsiderGuard **pulling** activity from another app, with no CSV upload involved.

| Piece | What it is | Port |
|---|---|---|
| `source_app.py` | **Acme FileVault**, a *fictional* file-sharing app. It creates normal synthetic activity for 5 employees, exposes a read-only audit-log API, and serves the live simulation console with its controls. | 9000 |
| `connector.py` | The InsiderGuard connector. Every few seconds it pulls new audit entries, maps them to InsiderGuard's schema, posts them to `/api/events`, saves its checkpoint and prints any new alerts. It follows the console's controls. | – |
| InsiderGuard API | Your existing backend. **No changes are needed.** | 8000 |

```
Acme FileVault ──(1) GET /api/v1/audit-logs?cursor=N──►  connector.py  ──(3) POST /api/events──►  InsiderGuard API
   (port 9000)  ◄─(2) JSON page + next_cursor ─────────   (4) saves cursor                      (scores + alerts)
```

All data is synthetic. Do not point the connector at a real system with real employees' data.

## Run it (4 terminals)

```powershell
# 1. InsiderGuard backend (from backend/, venv active). Seed first so the demo users have baselines.
python -m app.seed --reset
python -m uvicorn app.main:app --reload

# 2. InsiderGuard web app (from frontend/)
npm run dev

# 3. The fictional source app (from demo/live_pull/, same venv)
python source_app.py           # console: http://localhost:9000/

# 4. The connector (from demo/live_pull/, same venv)
python connector.py
```

Open http://localhost:9000/ and click an attack button: **Honeytoken touch**, **Bulk exfiltration** or **Account takeover**.
Within about 5 seconds the connector prints `>>> NEW ALERT`, and the alert appears in the InsiderGuard web app.
Refresh the web app to see it, because the web app doesn't auto-refresh yet.

Expected results from a test run on the seeded data:

| Scenario | User | Score | Indicators |
|---|---|---|---|
| honeytoken | u010 | 50 High | honeytoken_interaction |
| exfiltration | u008 | 55 High | bulk_download + restricted_resource_access + correlation bonus |
| account takeover | u007 | 82 Critical | download_volume_anomaly + repeated_denied_access + unknown_device + correlation bonus |

Normal background activity raises no alerts.

## Console controls (http://localhost:9000/)

| Control | What it does | What you'll see |
|---|---|---|
| **Pause / Resume** | Freezes FileVault's demo clock and normal activity. The connector stops pulling while paused. Clicking an attack button resumes automatically. | Clock and log stop. The connector prints `[paused]` and the console shows *Connected, paused* |
| **Pull every** 3 s / 5 s / 10 s | Sets how often the connector pulls. Takes effect from the connector's next cycle. | The *next pull in* countdown and the connector's output speed change |
| **InsiderGuard offline** | Simulates an outage. The connector still pulls but treats the push as failed, so nothing is sent and the cursor doesn't move. | Red status, `InsiderGuard offline (simulated), not sent · cursor stays at N`. Untick it and the next pull delivers everything missed |
| **Reset** | Empties FileVault's log and moves the clock to a fresh simulated day. The connector notices and restarts from cursor 0. InsiderGuard keeps the alerts it already raised. | Log restarts at #1. Connector prints `FileVault was reset or restarted ... restarting from cursor 0` |

The controls travel through a **demo-only control channel**: the connector reads `GET /demo/control` before each pull
and reports its status to `POST /demo/connector-status`. A real source app wouldn't have these endpoints, and a real
connector would keep its settings in its own configuration. Set `DEMO_CONTROL=0` to make the connector ignore them and
use `POLL_SECONDS` only.

In the audit log, blue rows haven't been pulled yet, grey rows have, and red rows were created by an attack button.

## Things to point out in a demo

- **The format is the source app's own.** FileVault says `occurredAt`, `actor.employeeId`, `file.download` and `bytes`.
  `to_insiderguard()` in `connector.py` maps those to `timestamp`, `user_id`, `download` and `volume_mb`.
  Every real integration needs this mapping step.
- **The cursor / checkpoint.** `connector_state.json` stores the last entry ID the connector has seen.
  Stop the connector, wait, and start it again: it resumes exactly where it stopped, with no duplicates and no gaps.
  The cursor is saved only *after* InsiderGuard accepts a batch, so a failure means a retry rather than lost events.
- **Least privilege.** The source app gives the connector a *read-only* token.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `SOURCE_URL` / `SOURCE_TOKEN` | `http://127.0.0.1:9000` / `demo-readonly-token` | Where to pull from |
| `IG_URL` / `IG_USER` / `IG_PASSWORD` | `http://127.0.0.1:8000` / `admin` / `Guard#12345` | Where to push to |
| `POLL_SECONDS` | `5` | How often to pull when the console isn't available (otherwise the console's **Pull every** wins) |
| `DEMO_CONTROL` | `1` | `0` = ignore the console's controls |
| `STATE_FILE` | `connector_state.json` | Where the cursor checkpoint is saved |
| `FILEVAULT_SPEED` | `60` | Demo clock speed: 1 real second = 60 simulated seconds |
| `FILEVAULT_TICK` | `2` | Real seconds between normal events |
| `FILEVAULT_PORT` / `FILEVAULT_READ_TOKEN` | `9000` / `demo-readonly-token` | FileVault's port and read-only key |

## Known limitations (fine for a prototype; mention them as future work)

- The connector logs in as **admin**, because only admins can post events today. A dedicated ingest-only role would be better.
- InsiderGuard doesn't store the source entry ID, so it can't de-duplicate events if a batch is resent after a crash.
- Reset clears FileVault only. To clear InsiderGuard's alerts too, stop the backend and run `python -m app.seed --reset`.
- The demo clock runs 60× faster: each simulated shift is 09:50–13:30 UTC (about 3.7 real minutes), then the next day starts.
  This keeps login times and daily volumes in line with the seeded baselines, so normal users stay quiet.
