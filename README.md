# InsiderGuard

AI-assisted insider threat detection and data-exfiltration prevention — a lightweight UEBA prototype that implements the
*Software Stack Specification* (IE3092, Group 03). **Synthetic data only.** No real credentials, no automatic
enforcement, no SIEM/XDR integration.

```
insiderguard/
├── backend/    FastAPI · SQLAlchemy · pandas/NumPy · JWT+bcrypt+RBAC · pytest
└── frontend/   React · Bootstrap · Chart.js (Vite) · Vitest
```

## Quick start

```bash
# 1. Backend  (Python 3.11+)
cd backend
pip install -r requirements.txt
python -m app.seed --reset          # generates labelled synthetic data, scores it, runs the evaluation
uvicorn app.main:app --reload       # API on :8000  (docs at /docs)

# 2. Frontend (Node 18+)
cd ../frontend
npm install
npm run dev                         # UI on http://localhost:5173 (proxies /api to :8000)
```

Development accounts (seeded only when `INSIDERGUARD_ENV != production`; override with
`INSIDERGUARD_ADMIN_PASSWORD` / `INSIDERGUARD_ANALYST_PASSWORD`):

| Role    | Username  | Password         | Can do |
|---------|-----------|------------------|--------|
| admin   | `admin`   | `Guard#12345`    | everything: ingest, honeytokens, rule thresholds, audit log |
| analyst | `analyst` | `Review#12345`   | dashboard, alerts, cases/notes, AI explanation, reports, evaluation |

**Change these before exposing the service anywhere.** In production, set `INSIDERGUARD_ENV=production`
and `INSIDERGUARD_SECRET_KEY` (the app refuses to start without it), and set `DATABASE_URL` for PostgreSQL
(e.g. `postgresql+psycopg://user:pw@host/insiderguard`; install `psycopg[binary]`).

### Production Administrator Bootstrap

From `backend`, with the production `DATABASE_URL`, `INSIDERGUARD_ENV=production` and
`INSIDERGUARD_SECRET_KEY` configured, run `python -m app.create_admin`. Enter the username,
password, and password confirmation at the hidden prompts. Existing usernames are rejected
case-insensitively. Production startup and data seeding do not create default accounts.

Passwords require at least 10 characters, at most 72 UTF-8 bytes, a letter and a digit, and
must not contain the username (case-insensitive). The new development defaults above apply
only to freshly seeded accounts; existing passwords are unchanged.

Administrators manage accounts at `/accounts`. Password resets invalidate the target's
existing sessions. The token fingerprint also requires users to sign in again after upgrading
from tokens issued before this feature. All users must sign in once after this deploy because
tokens now require the `pwv` password fingerprint claim. Every user can change their own
password at `/profile`; the current browser receives a fresh token while all older tokens
for that user stop working. Incorrect current-password attempts are limited to five per
15 minutes per user, independently of login attempts (in memory per server process).
The last administrator and your own account cannot
be deleted; your own password cannot be reset through administrator account management.

### Optional Generative AI explanations
Set `AI_API_KEY` (and optionally `AI_API_URL`, `AI_MODEL`). Defaults target the Anthropic Messages API. Only an
**anonymized, structured** summary is sent (pseudonymous subject ID, indicator names, weights, numeric facts — no
user IDs, resource paths or device IDs). Without a key, or if the call fails, everything still works and the alert
shows the deterministic evidence with no narrative.

### Feeding your own telemetry
```bash
python -m app.generator --out events.csv                       # CSV + ground-truth files
python -m app.generator --post http://localhost:8000 --user admin --password '…'   # via REST
```
or use **Telemetry & Honeytokens → Import** in the UI (CSV/JSON). Field aliases, mixed timestamp formats and
bytes→MB are normalized; bad rows are rejected with structured per-field errors and logged for the administrator.

## How it works

1. **Ingest / normalize** (`normalize.py`, `pipeline.ingest_records`) → standard event schema, validation, error log.
2. **Baseline** (`engine.compute_baseline`) — per user, from the first `baseline_days` (14) of history: circular
   login-hour mean/σ, daily file-access and download-volume mean/σ, known devices and resource types. Users with too
   little history are `baseline pending` (rules still apply, anomaly engine does not).
3. **Rule engine** — bulk download (per-file and daily total), failed-logon bursts, repeated denied access, off-hours
   activity, restricted-resource access. Thresholds and weights are editable by admins (`/api/rules`).
4. **Anomaly engine** — z-score vs the user's *own* baseline for login time, access volume, download volume, plus
   unknown device and novel resource category. The baseline values used are stored in each indicator.
5. **Honeytoken engine** — any access to an active registered decoy fires the highest-weight indicator (50).
6. **Risk scoring** — strongest indicator per category (time, volume, resource, denied, device, honeytoken) within a
   rolling window, summed, plus a correlation bonus (+10/+20/+25 for 2/3/4+ categories inside 60 min), capped at 100.
   Low < 25 ≤ Medium < 50 ≤ High < 75 ≤ Critical. Fully deterministic; the per-indicator breakdown is stored.
7. **ATT&CK mapping:** fired indicators carry technique IDs; the API resolves names, tactics and links
   from the bundled Enterprise catalog. This is analyst context only and never changes scoring,
   categories, incident grouping or evaluation. Alert details show each technique ID once in the MITRE ATT&CK mapping section;
   the alert queue supports local technique search and tactic filtering without displaying technique IDs.
8. **AI layer** — explanation only; clearly labelled as not the source of the score.
9. **Dashboard / cases / reports / audit** — ranked users, evidence timeline, department trends, case status + notes,
   period/department reports (JSON, CSV, print), audit log of analyst actions.
10. **Evaluation** — precision, recall, F1, FPR, FNR and detection latency for Rule-Only, Anomaly-Only and Hybrid on the
   labelled data set (unit: user-day after each user's learning window; latency = scenario start → first alert).

## API (Table 12 + supporting endpoints)

`POST /api/events` · `POST /api/events/import` · `GET /api/users/{id}/risk` · `GET /api/users/{id}/timeline` ·
`GET /api/alerts` · `GET /api/dashboard/summary` · `POST /api/honeytokens` · `GET /api/evaluation/results`
— plus auth, users list, alert detail/status/notes/explain, honeytoken list/revoke, rules, reports, audit,
parse-errors, evaluation run. Interactive docs at `/docs`.

`GET /api/mitre/mapping` (administrator or analyst) exposes the catalog version, attribution and
the complete indicator mapping, including conditional branches and confidence levels.

### ATT&CK mapping

The offline Enterprise ATT&CK v20.0 catalog contains all 706 active techniques and subtechniques.
Its names, tactic memberships and URLs come from the official versioned
[MITRE STIX bundle](https://github.com/mitre-attack/attack-stix-data/blob/master/enterprise-attack/enterprise-attack-20.0.json).
Revoked and deprecated techniques are excluded. No runtime network requests or database migrations
are needed. Confidence describes the mapping heuristic, not a probability of malicious activity.

| Indicator | Technique IDs and mapping confidence |
|---|---|
| `failed_logon_burst` | T1110 Brute Force (high) |
| `repeated_denied_access` | T1083 File and Directory Discovery (medium) |
| `restricted_resource_access` | T1039 Data from Network Shared Drive (medium) |
| `bulk_download` | T1039 (medium); T1074.001 Local Data Staging (low) |
| `download_volume_anomaly` | T1039 (medium); T1074.001 (low), against the personal baseline |
| `access_volume_anomaly` | T1039 (medium); T1083 (low) |
| `novel_resource_category` | T1083 (low) |
| `off_hours_activity` | T1078 Valid Accounts (low); ATT&CK has no off-hours technique |
| `anomalous_login_time` | T1078 (medium) |
| `unknown_device` | T1052.001 Exfiltration over USB (medium) for removable-device IDs; otherwise T1078 (low) |
| `honeytoken_interaction` | T1083 (medium); also T1039 (high) for file access, download or honeytoken events whose result is not denied |
| `correlated_indicators` | None: this is a scoring bonus, not a behaviour |

Removable-device matching uses the environment variable `REMOVABLE_DEVICE_PATTERN`, default
`^(USB|EXT|RMV)[-_]` (case-sensitive), matching synthetic IDs such as `USB-EXT-1234`.
This configuration is separate from numeric detection rules. Full per-indicator rationales are
available from `/api/mitre/mapping` and the alert breakdown.

To regenerate the catalog from the official versioned bundle, run from `backend`:

```bash
python scripts/build_mitre_catalog.py https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack-20.0.json
# A local downloaded STIX JSON path is also accepted as the first argument.
```

The build script uses only Python's standard library. It derives the ATT&CK version from
`x-mitre-collection`, tactic order from the Enterprise matrix and IDs/URLs from MITRE external
references. Output keys are sorted; `generated_at` records the build time. Review and commit the
generated `backend/app/data/mitre_attack_enterprise.json` when updating the version.
Persisted alerts and risk points pick up stored tags after authenticated
`POST /api/admin/recompute`, or `python -m app.seed --reset` (which deletes existing lab data).
Older alerts are mapped at read time in the meantime. Stored technique IDs take precedence;
unknown IDs display as Unknown technique without a link. Resolved links use a trailing slash.

Mapping is analyst context derived from indicator type; it does not affect the score and is not
proof a technique was used. Mappings are indicator-level heuristics: an unfamiliar host does not
establish account compromise, and a decoy hit does not establish intent. Exfiltration channels
other than removable media are not observed, so most volume indicators map to Collection rather
than Exfiltration. Multiple indicators contributing the same technique are combined in the alert
summary, with the strongest mapping confidence and all contributing indicator names.

Future work: administrator-editable mappings, ATT&CK filters and charts on Reports or Dashboard,
a full matrix heat map, and MITRE D3FEND/Engage integration. ATT&CK-driven scoring changes are
outside this feature's scope.

© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation.
MITRE ATT&CK and ATT&CK are registered trademarks of The MITRE Corporation.
See [MITRE ATT&CK Terms of Use](https://attack.mitre.org/resources/legal-and-branding/terms-of-use/).

### Report Filters

`/api/reports/risk` accepts date-only `start` / `end` values (`YYYY-MM-DD`); the end day is
included in full, using an exclusive next-day UTC boundary. Category and status accept
comma-separated lists. Score range, exact user ID, indicator, sorting, grouping, and top-N
filters apply equally to JSON and CSV. Summaries, charts, and groups cover all matching
alerts; `limit` caps the detail rows and CSV only. `/api/reports/range` exposes the dataset's
event dates for presets, and `/api/reports/indicators` lists available indicator names.

## Reference result (seed 42, 30 users, 49 days, 20 labelled scenarios)

| Mode         | Precision | Recall | F1   | FPR   | Scenarios caught | Median latency |
|--------------|-----------|--------|------|-------|------------------|----------------|
| Rule-Only    | 0.71      | 0.34   | 0.47 | 0.6 % | 10 / 20          | 17 min         |
| Anomaly-Only | 0.88      | 0.72   | 0.79 | 0.4 % | 12 / 20          | 14 min         |
| Hybrid       | 0.85      | 1.00   | 0.92 | 0.7 % | 20 / 20          | 6 min          |

Caveat: the generator and detectors were built together, and the data includes "rule-evasive" (low-and-slow,
new-device) and "baseline-aware" scenarios by design. These numbers demonstrate the comparison harness and the
value of combining signals; they are **not** a claim about real-world accuracy.

## Tests
```bash
cd backend && python -m pytest -q       # 15 tests: normalization, engines, scoring, API, RBAC, audit, cases
cd frontend && npm test                 # component tests
```

## Spec traceability
REQ-01 ingestion → `api.post_events/import_events`, `pipeline.ingest_records` · REQ-02 → `normalize.py` ·
REQ-03 → `engine.compute_baseline` · REQ-04 → `engine.detect_user`, `/api/rules` · REQ-05 → anomaly section of
`detect_user` · REQ-06 → honeytoken registry + engine · REQ-07 → `engine.score_window/build_series` ·
REQ-08 → `ai.py` · REQ-09 → dashboard, `/api/reports/risk`, case endpoints · REQ-10 → `AuditLog`, `evaluation.py`.

## Design notes and known limitations
- **"Maximum sum" (REQ-07-01)** is implemented as the sum of per-category maxima, capped at 100.
- **Safety:** the system never blocks or disables accounts; every score view carries the "investigative lead, not proof"
  notice.
- **Baseline recalculation (REQ-03-03):** baselines are recomputed from the user's stored history on every ingest
  batch, but the learning window is the user's first 14 days, so established baselines do not drift (this prevents an
  attacker from slowly training the baseline). A rolling/adaptive baseline would be a future extension.
- Processing is synchronous per ingest batch (fine for the prototype's ~40k events; use a queue for larger loads).
- Login throttling is in-memory per process; use a shared store behind multiple workers. Token is kept in
  `sessionStorage`; put the API behind HTTPS in any deployment.
