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

### Live pull demo

The repository includes a self-contained synthetic integration demo that pulls
audit records from a fictional Acme FileVault app into InsiderGuard through a
checkpointed connector. It includes attack controls, simulated outages, and a
live source-app console. See [demo/live_pull/README.md](demo/live_pull/README.md)
for the architecture, setup commands, environment variables, and walkthrough.

Development accounts (seeded only when `INSIDERGUARD_ENV != production`; override with
`INSIDERGUARD_ADMIN_PASSWORD` / `INSIDERGUARD_ANALYST_PASSWORD`):

| Role    | Username  | Password         | Can do |
|---------|-----------|------------------|--------|
| admin   | `admin`   | `Guard#12345`    | ingestion, honeytokens, rules, audit, ownership assignment, workload, evaluation runs; read-only case work |
| analyst | `analyst` | `Review#12345`   | dashboard, alerts, reports, evaluation results; claim cases and work their own cases in My cases |

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

### Case ownership

An alert is a case, identified as **Case #<alert id>**. Ownership is separate from the
three case statuses: Open, Under investigation and Closed. On the Alerts page, click
any case tile to inspect its read-only detail view. Analysts can claim an unowned,
non-closed case with **Assign to me**; **Investigate** then opens `/my-cases/<id>`.
`/my-cases` lists the analyst's cases, summary counts, age, status and severity filters.
The sidebar badge counts Open and Under investigation cases.

Only the owner analyst can change status, add notes or request an AI explanation,
and the interactive controls appear only in the My cases workspace. Closing requires
an outcome and note; reopening requires a reason. Other status changes are immediate.
Releasing a non-closed case requires a reason of at least
three characters; Under investigation returns to Open. Closed cases cannot be
claimed or released, but their owner can still work them or change status in the
workspace. Administrators can assign/reassign any case, including closed cases,
and inspect team workload, but cannot change status, add notes or request case
explanations. The existing automatic explanation background task is unchanged.
Only administrators can run evaluation; analysts can still view the results.

All permissions are enforced by the API. Assignment uses a unique `alert_id` to
resolve concurrent claims. Existing table columns are unchanged: startup's
`create_all` adds only `alert_assignments` and `case_events`. No reseeding or manual
migration is required. Case events are written through `app.cases.record_event`;
ownership actions, status changes and detector lifecycle changes are also audited.

Owned cases and cases with event history are retained when re-scoring removes an
incident. Nearby replacement incidents within the scoring window do not create
duplicate investigations: the original case identity and evidence remain intact,
and an owned case records `no_longer_detected` once. If its original incident start
is detected again it records `redetected`. The detail page displays the detector
state as a banner without introducing another case status. Detection, baseline,
scoring and AI logic are unchanged.

Deleting an analyst releases their non-closed cases to the queue and records the
reason `owner account deleted`; closed cases retain the historical owner username.
The Accounts page shows each analyst's active case count and warns before deletion.
Workload ages use current UTC time, not the dataset's newest event. Critical/High
workload counts cover active cases. The last-seven-day closure count uses the latest
closing status event, with the alert's update time as a fallback for legacy cases.
My cases summaries cover all of the caller's cases even when the list has a status filter.

Ownership endpoints:

- `POST /api/alerts/{id}/claim` (analyst)
- `POST /api/alerts/{id}/release` with `{ "reason": "..." }` (owner analyst)
- `POST /api/alerts/{id}/assign` with `{ "owner": "analyst_username" }` (admin)
- `GET /api/my-cases?status=open` (analyst; status optional)
- `GET /api/team/workload` (admin)
- `GET /api/alerts/{id}/events` (staff; oldest first)

`GET /api/alerts` supports `owner=me`, `owner=unassigned` or an analyst username;
`sort_by=owner` and `then_by=owner` work with existing sorting. Unassigned owners
sort as empty strings, and alert ID remains the final tie-breaker. The owner filter,
other alert filters and sorting persist in the URL. Existing response keys remain
available; `owner`, `assigned_at` and `detection_state` are additive fields.

### Case resolution and operational feedback

Closing a case in My cases opens a dialog requiring one of **True positive** (real
threat or policy violation), **False positive** (wrong or noisy detection), or
**Benign/explained** (unusual but legitimate activity with context), plus a closing
note of 15–4000 characters after trimming whitespace. Reopening to Open or Under
investigation requires a reason of 5–4000 trimmed characters. Only the owner analyst
can close or reopen; administrators remain read-only on case work. Moving between
Open and Under investigation requires no dialog or extra fields.

`PATCH /api/alerts/{id}` accepts `{status, outcome?, note?, reason?}`. Send `outcome`
and `note` only when transitioning into Closed, and `reason` only when transitioning
out of Closed. Non-null fields supplied for an unrelated transition are rejected
with 422. A repeated status with no extra fields is a no-op for resolution history;
changing a verdict requires reopening and closing again. Concurrent close/reopen
requests use a status compare-and-set as well as ownership checks.

The new `alert_resolutions` table retains every verdict and its closing note.
Reopening stamps `reopened_at`, `reopened_by` and `reopen_reason`; it never deletes
or overwrites the old verdict. The current resolution is the latest unreopened row
on a currently closed case. Alert responses add `resolution` and `outcome`; detail
responses also include `resolution_history`. The Alerts and My cases pages show
outcome badges separately from status and owner. Older closed cases remain valid
and display **Closed (no outcome recorded)** or **No outcome** without fabricated
verdicts. Startup adds the new table automatically; no existing columns change.

Case history combines events and resolution rows, including analyst, timestamp,
outcome, closing note, reopen reason and detector updates. Re-scoring preserves
resolutions and closed cases. A real change to a closed incident's peak score or
last activity adds one `updated_after_closure` event; reprocessing identical values
does not add another. Resolution and reopening actions are audited; resolution
audit detail contains only outcome and note length, never the closing note text.

`GET /api/alerts` adds an `outcome` filter accepting comma-separated outcome keys.
`GET /api/reports/risk` accepts the same filter plus `owner=<username>` or
`owner=unassigned`. JSON rows and CSV gain owner/outcome columns, and the report
summary adds `alerts_by_outcome` across all matching alerts before the detail limit.
The report's `no_outcome` bucket includes both unresolved and legacy closed cases.

`GET /api/evaluation/feedback` is staff-readable and completely separate from
labelled lab evaluation and `EvaluationRun`. Its Evaluation-page section is titled
**Operational feedback (analyst verdicts)**. It uses one current resolution per
currently closed case; reopened and superseded historical verdicts are excluded.
It returns counts by outcome, closed-with-outcome and legacy closed counts,
`alert_precision = true_positive / all resolved alerts` (including false positive
and benign/explained in the denominator), precision by severity category, top
indicators in false-positive/benign cases, and median assignment-to-resolution time.
Assignment time is captured in the resolution event so later reassignment cannot
rewrite closure duration. Rows lacking a usable assignment time are omitted from
the median, with `time_to_close_sample_count` reporting coverage.

The feedback what-if table tests current peak-score thresholds 30, 40, 50, 60 and
70 using `score >= threshold`. It reports alerts and true positives kept/lost,
false positives and benign cases removed, and resulting reviewed-case precision.
Undefined precision and closure time are null. Recall and F1 cannot be derived
from analyst verdicts because missed attacks are never reviewed: those metrics
remain available only from the labelled lab evaluation. Feedback never changes
detection thresholds, scores, baselines, AI logic or lab results.

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

These are historical results from before the registered-honeytoken correction below. Regenerate and rerun evaluation for current figures; the 15-user demo's actual metrics are in [DEMO_GUIDE.md](docs/DEMO_GUIDE.md).

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
cd backend && python -m pytest -q       # backend regressions, including both seeds
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

## Personal data handling

Employee profiles and contact records are available only through administrator-only endpoints and tabs. Both administrators and analysts receive the same PII-free user activity overview; lists, case links and reports use log user IDs, while AI inputs use pseudonyms. Departments come from ingested logs, never from the employee directory. Analysts cannot access the directory API.

Profile, directory and contact-log views are audited. Changes record field names or counts in audit details, never personal field values or contact summaries. Collect only the contact information needed for investigations. Profiles can be registered before logs arrive, and offboarding preserves their history; there is no delete endpoint.

The demo SQLite database is **not encrypted at rest**. Protect database files, backups and directory CSV files, and check applicable local data-protection law before using real employee data.

Directory CSV imports use the downloadable template, UTF-8 encoding, a 2 MB limit and at most 1,000 rows. Each valid row creates or updates a profile; invalid rows are reported by row number without echoing personal values. Omitted update fields are preserved. Blank CSV fields clear their corresponding values. Employment status must be one of the four directory statuses; case statuses remain unchanged. Profile and contact text rejects control characters, including newlines.

User activity charts use UTC and dataset-relative windows: the last 30 calendar days for the heatmap and the last seven for recent daily averages, including zero-activity days. Device and event-type summaries cover all recorded activity. Pre-registered IDs have an empty activity overview until logs arrive. Completeness measures monitored IDs with a profile; pre-registrations do not inflate that percentage.

## Escalations

An owning analyst can escalate a case, including a closed case, to an administrator. Only one open escalation per case is allowed; its filing snapshot is retained even if the case is later rescored. Escalations have a separate workflow and do not change the three case statuses, ownership, detection or risk scores.

The handling administrator acknowledges the request, may ask for more information or log contact, then selects **Mark as handled** with a note of at least ten characters. Acknowledge before taking handling actions. Only that handling administrator may manage the request; another admin receives a conflict naming the handler. Analysts may withdraw their own request only while it is submitted. Completed and withdrawn requests retain their timeline and messages and cannot be changed; a new escalation can then be filed for the case.

The states are submitted → acknowledged → contacted → completed, with needs_info available after acknowledgement or contact. An analyst reply to needs_info returns it to acknowledged. A submitted request can instead be withdrawn. Repeated contact logs are supported. All status changes and actions are audited through a central history hook. Submitted, acknowledged and needs_info requests older than 24 hours are overdue. Contacted requests remain open but are not overdue.

Recommendations are **advisory text only**: the application cannot disable accounts or perform access reviews, HR actions or other enforcement. Admins can export the filtered queue to CSV; analysts can list and open only requests they filed. User overviews show a limited, PII-free escalation history to both roles, but full escalation details remain restricted to the filing analyst and administrators, including after case reassignment.

Keep contact details out of escalation summaries, recommendations, messages and handling notes. Contact summaries are stored only in the admin-only employee contact log, linked to the escalation, and are excluded from escalation responses, CSV and audit details. Contact can be logged before a directory profile exists; administrators can view those records on the user's Contact log tab. No personal directory fields are joined into escalation responses.

## Notifications

The bell opens the Notifications page directly, with no dropdown. A red dot indicates unread items; the accessible label includes the count. Desktop and mobile share one unread-count poll every 30 seconds, paused while the tab is hidden. Inbox actions refresh the count immediately.

Notifications are delivered to existing accounts at event time: analysts receive ownership and escalation handling updates; admins receive case activity, escalation submissions/replies/withdrawals, and unassigned High/Critical live alerts. Copy uses fixed text and case/escalation IDs, never employee profiles, case notes, contact summaries, messages or closing/reopening notes.

Case and escalation delivery runs through their central event hooks. Delivery keys suppress duplicate observation of the same event while allowing distinct later reassignments and reopenings. Dismissal and 30-day retention do not reset those keys. Account deletion removes both the inbox and its delivery keys.

Processing defaults to `silent=True`: seeds, CLI processing, recompute and rule/baseline rescoring do not send notifications. Only live event ingestion opts in. Existing alerts changing score do not count as new alerts. A live run with up to ten newly created unassigned High/Critical alerts sends individual notifications; a larger run sends **one summary instead of individual items**. Detection, scoring, baseline and AI logic are unchanged.

Admin notification requests lazily check for open High/Critical alerts created more than 24 hours ago without an owner. Each admin receives at most one reminder per alert, even after dismissing it. Retention deletes inbox rows older than 30 days, with a database-backed checkpoint allowing the unread-count endpoint to run cleanup at most once per hour. Delivery keys are retained to preserve deduplication; these contain account usernames and event/alert identifiers, not notification text or employee data.
## Choose a seed: lab data or the 15-user live demo

Only **one seed is active at a time** in a database. Both commands below target the same `DATABASE_URL` (by default `backend/insiderguard.db`). **`--reset` drops every table and wipes the selected database**, including accounts, case history, profiles and notifications. Back up the database before switching seeds. Stop the API while replacing its database, then restart it.

From `backend/`, choose either:

```powershell
# Original labelled lab seed: unchanged generator and seed CLI
./.venv/Scripts/python.exe -m app.seed --reset

# Separate coherent 15-user demonstration; no network access needed
./.venv/Scripts/python.exe -m app.seed_demo --reset

# Reproduce a specific run, or check the active demo without resetting it
./.venv/Scripts/python.exe -m app.seed_demo --reset --end 2026-10-09 --days 60 --seed 7
./.venv/Scripts/python.exe -m app.seed_demo --verify-only
```

The new seed has exactly three monitored IDs per department, fictional `example.com` profiles, established baselines for fourteen users and one pending new hire, eight attack personas, legitimate noisy activity, all three case statuses, resolution/reopening history, all six escalation states, linked contact records and a small mostly-read inbox. It leaves u016 absent for live pre-registration. It uses the real importer, processing pipeline and case/escalation services; no scores or narratives are fabricated.

The script writes [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md) and [docs/DEMO_README.md](docs/DEMO_README.md) from the actual run, including credentials, real case numbers, metrics, persona stories and a ten-minute walkthrough. Default end is the latest Friday on or before today in UTC; the final day's cutoff is midnight, so observed events never lie in the future. Supported durations are 45–120 days. Identical seed/end/duration yields identical telemetry and demo output; password hashing remains securely salted. Verification checks integrity, privacy, ground truth, risk spread and recompute stability, and exits nonzero with every problem found. Run it before making live demonstration changes.

The primary admin and analyst use their configured development credentials; analyst2 uses `DemoReview#23456`, and analyst3 uses `DemoReview#34567`. These are demo-only passwords. The generated guide includes the configured credentials, so never generate a shared guide using production secrets. `--with-ai` requests real explanations only when an AI key is configured; it is the only mode that needs network access.

**Honeytoken scoring correction:** touching a registered honeytoken no longer also emits `novel_resource_category` solely because its decoy type was absent from the baseline. An isolated normal-hour touch now scores **50 rather than 68**. Other independently valid indicators still contribute normally. This small engine fix affects both seeds, so risk scores and lab evaluation numbers have changed; regenerate/recompute and rerun evaluation when comparing with older results. No other detection or scoring logic changed.


## Simulated activity lab

The separate [Activity Lab](simulator/README.md) sends synthetic employee events to the running InsiderGuard API. After starting the backend on port 8000 and frontend on port 5173, open a third terminal:

```powershell
cd simulator
npm.cmd start
```

Open http://localhost:5175 or select **Simulated Lab** in the sidebar. Connect with an administrator account, choose **Prepare new employee**, and select a scenario. Node.js is required; the simulator has no package dependencies. Submitted events and cases remain in the database. Use **Prepare new employee** for an independent demonstration.
