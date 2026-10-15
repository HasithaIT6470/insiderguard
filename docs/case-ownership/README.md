# Case ownership (Task 5)

Implemented on the current `gen2` branch. Cases remain alerts, with only the three
statuses `open`, `under_investigation`, and `closed`. Ownership is a separate value.

## Behavior

- Analysts claim unowned, non-closed cases from Alerts. Claims preserve status and
  are serialized by the assignment's unique alert ID. A competing claim returns 409.
- Alerts and `/alerts/:id` are read-only for case work. Only the owner analyst can
  edit in `/my-cases/:id`; the backend independently enforces ownership on every edit.
- Administrators can assign/reassign ownership, including on closed cases, and view
  team workload. They cannot change case status, add notes, or request explanations.
- Releasing a non-closed case requires a reason. Under investigation returns to Open.
- Deleting an analyst releases non-closed cases and retains historical closed-case owners.
- Only administrators can run evaluation. Analysts can view evaluation results.
- Cases with assignments or events survive detector reprocessing. A nearby shifted
  incident within the configured scoring window is associated with the retained case
  instead of creating a duplicate investigation. Its original identity and evidence
  are retained, with one `no_longer_detected` event. Detection of the original incident
  start again adds one `redetected` event. Neither is a new case status.

Startup adds the new `alert_assignments` and `case_events` tables through the existing
`create_all` path. No existing table columns, detection logic, scoring logic, baseline
logic, AI logic, or generator scenarios changed. No new dependencies were introduced.

## Verification

- Final backend suite: `python -m pytest -q` — 156 passed.
- Frontend suite: `npm test` — 64 passed across 11 test files.
- Final production build: `npm run build` — passed.
- `git diff --check` — passed.
- Backend coverage includes competing claims, ownership/role denials, closed-case
  restrictions, admin assignment, owner filtering/sorting, summaries/workload, release,
  disappearance/shift/redetection retention, account-deletion handoff, events/audit,
  and creating the new tables alongside an existing schema.
- Frontend coverage includes actions by role/state, workload-aware assignment,
  URL owner filters, My cases sorting/filtering and route guards, read-only details,
  owner workspace edits and release, evaluation roles, and account-deletion warnings.
- Real headless Chrome exercised the Vite app against a temporary SQLite backup on
  API port 8002, preserving the live lab's data. It verified admin workload and ownership
  controls, analyst claim, workspace note/status changes, release with a reason,
  subsequent read-only detail controls, sidebar count, and analyst evaluation view.
  No browser runtime errors occurred. Results are in `browser-verification.json`.
- A rendered workspace screenshot was visually inspected.

## Manual test checklist

1. Sign in as an analyst. In Alerts, claim an unowned, non-closed case. Confirm Owner
   changes independently of status, then open it with Investigate.
2. In My cases, check the active sidebar count, severity/age ordering, and filters.
   Change status with confirmation, add a note, and request an AI explanation.
3. Release a case with a reason. Confirm it returns to the queue, Under investigation
   becomes Open, and the case timeline records the release. Confirm closed cases
   offer View and cannot be claimed/released.
4. As a different analyst, inspect that case read-only. Try opening another owner's
   `/my-cases/<id>` URL and verify the redirect/message. Confirm evaluation results
   are visible without a Run evaluation button.
5. As an administrator, check Team workload and assign/reassign an open or closed case.
   Confirm case status remains unchanged and no case-edit controls are available.
6. On Accounts, delete a test analyst with active cases. Confirm the count warning,
   returned active cases, historical closed-case owner, release events, and audit count.
7. Recompute an owned case after changing a relevant rule so its incident disappears
   or shifts. Confirm the retained case, one lifecycle event/banner, no duplicate,
   and redetection when the original incident returns. Restore the test rule afterward.
