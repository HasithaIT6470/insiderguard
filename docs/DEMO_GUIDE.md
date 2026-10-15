# InsiderGuard: 15-user demonstration guide

Generated from seed **7**, 60 days, ending **2026-10-09 at 00:00 UTC**.
All names and supervisors are fictional, emails use example.com, and phones use the reserved fictional 202-555-01xx range. Never call or email them.
Only one seed is active in a database. `--reset` irreversibly replaces the selected database. Run verification before making live demo changes.

## Accounts (demo credentials only)

| Account | Role | Password |
|---|---|---|
| admin | admin | Guard#12345 |
| analyst | analyst | Review#12345 |
| analyst2 | analyst | DemoReview#23456 |
| analyst3 | analyst | DemoReview#34567 |

Environment-configured admin/primary analyst credentials above are from this actual run. Do not use production credentials to generate a publicly shared guide.

## Personas and actual cases

| User ID | Fictional name | Department | Story | Actual alerts (peak) | Case state | Owner | Outcome |
|---|---|---|---|---|---|---|---|
| u001 | Nira Vale | Finance | Treasury Analyst: Honeytoken snooping | Case #1 (50, High) | under_investigation | analyst | — |
| u002 | Oren Fable | Finance | Ledger Analyst: Weekend after-hours collection | Case #2 (70, High) | open | Unassigned | — |
| u003 | Tavi Quill | Finance | Reporting Specialist: Approved month-end reporting spike | Case #3 (30, Medium) | closed | analyst3 | false_positive |
| u004 | Mira Venn | HR | People Operations Analyst: Credential attack followed by success | Case #4 (65, High) | closed | analyst | true_positive |
| u005 | Lio Fern | HR | Benefits Coordinator: One week of holiday without events |  |  |  |  |
| u006 | Sera Wisp | HR | Policy Coordinator: Quiet regular policy work |  |  |  |  |
| u007 | Arlo Flint | Engineering | Design Engineer: After-hours hoarding of restricted designs | Case #5 (67.9, High) | closed | analyst2 | true_positive |
| u008 | Ena Rook | Engineering | Software Engineer: Privilege probing, then a separate bulk incident | Case #6 (45, Medium); Case #7 (55, High) | closed; open | analyst3; analyst3 | true_positive; — |
| u009 | Kian Moss | Engineering | Build Engineer: Approved large build-artifact downloads | Case #8 (52, High); Case #9 (30, Medium) | closed; open | analyst; Unassigned | benign_explained; — |
| u010 | Vela Reed | Sales | Sales Operations Analyst: Bulk customer exfiltration, currently Critical | Case #10 (77, Critical) | open | Unassigned | — |
| u011 | Daro Pike | Sales | Account Operations Analyst: New-device customer export | Case #11 (70, High) | under_investigation | analyst2 | — |
| u012 | Fia Lark | Sales | Proposal Coordinator: Approved laptop replacement and file restore | Case #12 (42, Medium) | closed | analyst2 | benign_explained |
| u013 | Noa Brim | IT | Infrastructure Analyst: Five-day low-and-slow exfiltration | Case #13 (30, Medium); Case #14 (30, Medium); Case #15 (30, Medium); Case #16 (30, Medium); Case #17 (30, Medium) | closed; closed; closed; closed; closed | analyst; analyst; analyst; analyst; analyst | true_positive; true_positive; true_positive; true_positive; true_positive |
| u014 | Zuri Cove | IT | On-call Systems Administrator: Legitimate scheduled night work |  |  |  |  |
| u015 | Ivo Dawn | IT | Junior Support Engineer: New hire, pending baseline, legitimate large download | Case #18 (30, Medium) | open | analyst3 | — |

Case #6 is the documented exception: an initial false-positive verdict was corrected after reopening; its current outcome is true positive. u008 has a later, separate bulk incident.
u005 has a seven-calendar-day holiday with no events. u015 started ten days before the cutoff and has a pending baseline: its large legitimate download is a rule alert, not an anomaly.
u016 has neither logs nor a profile; create a pre-registered profile for it live. Profiles have no department column; the UI obtains department only from logs.

## Expected numbers from this run

```json
{
  "alerts": 18,
  "alerts_by_category": {
    "Critical": 1,
    "High": 7,
    "Medium": 10
  },
  "cases_by_state": {
    "closed": 11,
    "open": 5,
    "under_investigation": 2
  },
  "current_risk": {
    "Critical": 1,
    "High": 3,
    "Low": 9,
    "Medium": 2
  },
  "escalations": {
    "acknowledged": 1,
    "completed": 1,
    "contacted": 1,
    "needs_info": 1,
    "submitted": 1,
    "withdrawn": 1
  },
  "events": 24737,
  "unread": {
    "admin": 2,
    "analyst": 2,
    "analyst2": 2,
    "analyst3": 2
  },
  "users": 15
}
```

| Evaluation mode | Precision | Recall | F1 |
|---|---:|---:|---:|
| rule_only | 0.5556 | 0.3846 | 0.4545 |
| anomaly_only | 0.8333 | 0.7692 | 0.8000 |
| hybrid | 0.7647 | 1.0000 | 0.8667 |

The honeytoken fix removes double counting of a registered decoy as a novel resource category. A normal-hour, otherwise isolated touch now scores 50 rather than 68. Both seeds and their evaluation metrics are affected.

## Escalations

| Status | Escalation | Case |
|---|---|---|
| submitted | Escalation #1 | Case #4 |
| acknowledged | Escalation #2 | Case #5 |
| needs_info | Escalation #3 | Case #6 |
| contacted | Escalation #4 | Case #12 |
| completed | Escalation #5 | Case #13 |
| withdrawn | Escalation #6 | Case #3 |

## Ten-minute walkthrough

1. **0:00–1:00, admin:** open Alerts, filter Owner = Unassigned, and assign current Critical Case #10 (u010) to an analyst. Explain that Owner is separate from the three case statuses.
2. **1:00–3:00, analyst:** claim unassigned Case #2 (u002), open My cases, move to Under investigation, add a note, then close as true positive with a meaningful closing note. Escalate it to admin with an advisory recommendation.
3. **3:00–4:30, admin:** open that escalation, acknowledge it, follow View user profile and contact details, and inspect Personal information. Log contact on the escalation; check the linked private Contact log entry. Mark as handled with a note.
4. **4:30–5:00, both roles:** use the bell to see role-specific updates; mark read/unread and show Back to Notifications. There is no dropdown and no personal data in notification text.
5. **5:00–6:30:** open Users, compare departments/risk/activity charts, open u015 to explain cold start, and u014 to explain legitimate on-call activity. Analysts cannot see personal information or contact logs.
6. **6:30–7:00:** inspect Case #6 history and its two resolutions; show u008’s separate later incident. Use breadcrumbs and Back to return to a filtered Alerts view.
7. **7:00–8:00:** show Evaluation lab metrics separately from Operational feedback (analyst verdicts). Analyst verdicts do not establish recall or F1.
8. **8:00–9:00:** use Reports Owner and Outcome filters, outcome chart, and CSV export.
9. **9:00–10:00, admin:** Users → Add employee profile → u016, demonstrating pre-registration without log activity. Its department is read-only and absent until logs arrive.

## Reproducibility and safety

`python -m app.seed_demo --reset --seed 7 --days 60 --end 2026-10-09`
`python -m app.seed_demo --verify-only`
Supported durations are 45–120 days. The midnight end-day cutoff prevents future observed events even on a Friday. The same seed/end/duration produces identical telemetry, workflow IDs, report text and metrics; salted password hashes and runtime durations are not deterministic artifacts.
History is created silently via application endpoints/services, with backdated timestamps. A small inbox is delivered at the final checkpoint from real historical case/escalation event hooks (mostly read, two unread per account); it is a demonstration replay, not a claim that email or other external notifications were sent.
Unread numbers above describe the seeded inbox. Opening the admin bell can additionally create the normal once-per-alert reminders for High/Critical cases that have remained unassigned for 24 real hours; those runtime reminders depend on when the demonstration is opened and do not change the prepared case state.
AI narratives are never fabricated. Without --with-ai, no network call is made. With --with-ai and a configured key, real explanations may vary and network access is required.
Event SHA-256: `bd9267ceb453a0b5c883860c2bd74dac57fd1c8420541ccebd241096c701c443`
