# Mandatory resolution and case history (Task 6)

Implemented on `gen2` with a new `alert_resolutions` table and no changes to
existing table columns or dependencies. Existing closed cases remain readable.

## Verification

- `cd backend; python -m pytest -q`: **175 passed**.
- `cd frontend; npm test`: **74 passed**, across 12 files.
- `cd frontend; npm run build`: passed.
- `git diff --check`: passed.
- Detection, scoring, baseline and AI logic, the generator and the lab evaluation
  implementation remain unchanged.

Backend tests cover required/trimmed closing fields, role and owner restrictions,
atomic concurrent closes, reason-required reopening, multiple resolution cycles,
legacy closed cases, rejection of unrelated fields, outcome filtering, retained
resolution history, idempotent post-closure update events, report JSON/CSV fields,
and exact feedback numbers on a constructed four-verdict dataset plus empty data.
The feedback test proves that no `EvaluationRun` is created or changed.

Frontend tests cover close/reopen validation and workspace integration, live note
counts, retained form values on error, combined case history, legacy labels,
outcome badges/filters, report columns/chart, feedback charts/table and empty state.

Real headless Chrome exercised the actual Vite UI and FastAPI backend against an
isolated temporary SQLite backup on port 8002. It verified:

- Empty operational feedback before any resolutions.
- Immediate transition to Under investigation without a dialog.
- Disabled Close until an outcome and sufficiently long note were supplied.
- Reopening with a reason and closing a second time with a different outcome.
- Two retained resolution rows, with only the current verdict counted in feedback.
- Administrator edit denial and read-only history on `/alerts/:id`.
- New synthetic telemetry merged into the closed incident, producing the
  Updated after closure marker while preserving the verdict.
- Operational feedback charts and Owner/Outcome report filters.
- No browser runtime errors. A rendered history screenshot was visually inspected.

The recorded checks are in `browser-verification.json`. Browser test mutations
were confined to the temporary database copy, not the live lab database.

## Transition and feedback semantics

- Only the owner analyst can close/reopen. The three case statuses are unchanged.
- Close notes must be 15–4000 trimmed characters; reopen reasons 5–4000.
- Non-null outcome/note on a non-closing transition, or reason on a non-reopening
  transition, returns 422. Null optional values are treated as absent.
- A repeated status without extra fields creates no resolution/history entry.
  A closed verdict must be reopened before it can be replaced by a new resolution.
- Resolution history is immutable except for stamps on reopening. The newest
  unreopened row is current only while its case is closed.
- Feedback counts current closed verdicts, not all historical resolution rows.
  It uses current peak scores/evidence, including changes recorded after closure.
- Alert precision is true positives divided by all current resolved alerts,
  including false positives and benign/explained. No kept rows means null precision.
- Median closure time uses assignment time captured at resolution. Older rows
  without a captured event can use a valid assignment time; missing/negative
  durations are excluded and coverage is reported separately.
- Reports' no_outcome bucket includes unresolved and legacy closed cases. Report
  summaries include every matching row, independently of the detail/CSV limit.
- Analyst verdicts cannot reveal missed attacks, so operational recall/F1 are not
  calculated. Threshold what-if results never modify actual detection rules.

## Manual checklist

1. As an owner analyst in My cases, choose Closed. Confirm an outcome and a note
   of at least 15 trimmed characters are required before Close case is enabled.
2. Reopen with a reason of at least five characters. Confirm the old note/outcome
   remain in Case history, then close again with a new verdict.
3. View `/alerts/<id>` read-only and check Owner, status, outcome badge, all history
   entries, and legacy Closed (no outcome recorded) for a case without a verdict.
4. Add test telemetry or recompute a closed incident so peak/last activity changes.
   Confirm one Updated after closure marker; repeat unchanged re-scoring and confirm
   no duplicate marker. The case and its resolution must remain intact.
5. In Reports, combine Owner and Outcome filters; compare JSON/table, CSV columns
   and the outcome chart. Verify summaries still cover all matches with Top N = 1.
6. In Evaluation, compare the separate lab and operational sections. Check outcome
   counts, precision, time to close, indicator chart, threshold table and recall/F1
   note. A reopened case should leave current operational feedback until reclosed.
7. As an administrator or another analyst, verify close/reopen requests are denied.
