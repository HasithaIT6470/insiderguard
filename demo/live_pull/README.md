# Live pull demo

This demo shows InsiderGuard **pulling** activity from another app, with no CSV upload involved.

| Piece | What it is | Port |
|---|---|---|
| `source_app.py` | **Acme FileVault**, a *fictional* file-sharing app. It creates normal synthetic activity for 5 employees and exposes a read-only audit-log API. | 9000 |
| `connector.py` | The InsiderGuard connector. Every 5 s it pulls new audit entries, maps them to InsiderGuard's schema, posts them to `/api/events`, saves its checkpoint and prints any new alerts. | – |
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

Open http://localhost:9000/ and click an attack button: **honeytoken**, **exfiltration** or **account takeover**.
Within about 5 seconds the connector prints `>>> NEW ALERT`, and the alert appears in the InsiderGuard web app.
Refresh the web app to see it, because the web app doesn't auto-refresh yet.

Expected results from a test run on the seeded data:

| Scenario | User | Score | Indicators |
|---|---|---|---|
| honeytoken | u010 | 50 High | honeytoken_interaction |
| exfiltration | u008 | 55 High | bulk_download + restricted_resource_access + correlation bonus |
| account takeover | u007 | 82 Critical | download_volume_anomaly + repeated_denied_access + unknown_device + correlation bonus |

Normal background activity raises no alerts.

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
| `IG_URL` / `IG_USER` / `IG_PASSWORD` | `http://127.0.0.1:8000` / `admin` / `Admin#12345` | Where to push to |
| `POLL_SECONDS` | `5` | How often to pull |
| `FILEVAULT_SPEED` | `60` | Demo clock speed: 1 real second = 60 simulated seconds |

## Known limitations (fine for a prototype; mention them as future work)

- The connector logs in as **admin**, because only admins can post events today. A dedicated ingest-only role would be better.
- InsiderGuard doesn't store the source entry ID, so it can't de-duplicate events if a batch is resent after a crash.
- The demo clock runs 60× faster: each simulated shift is 09:50–13:30 UTC (about 3.7 real minutes), then the next day starts.
  This keeps login times and daily volumes in line with the seeded baselines, so normal users stay quiet.
