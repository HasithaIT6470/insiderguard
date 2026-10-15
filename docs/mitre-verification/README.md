# ATT&CK mapping verification

Verified on 2026-10-15 on `feature/mitre-attack-mapping`, based on
`origin/gen2` at `b17f06865514d1bc702ad4dabf15f2d3feaa9fba`.

## Catalog provenance

- Official Enterprise ATT&CK v20.0 STIX bundle:
  https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/enterprise-attack/enterprise-attack-20.0.json
- Downloaded bundle SHA-256:
  `81113ba98afa2928f3dcff62022539f7ce30c315c32e14422f11ff95ce534352`.
- Generated catalog: 706 active techniques, 175,492 bytes before checkout newline conversion.
- Independently compared every catalog ID with every non-revoked, non-deprecated
  `attack-pattern` in the downloaded official bundle: the sets match exactly.
- Catalog URLs preserve the official external reference; resolved UI links append a trailing slash.
- The copyright and trademark notice follows MITRE's current Terms of Use; the license
  accompanies the catalog in `backend/app/data/MITRE_LICENSE.txt`.

## Score and evaluation invariance

Before modifying application code, ran `python -m app.seed --reset` with defaults,
then saved the authenticated `GET /api/evaluation/results` modes block and the
complete alert count. Repeated the same seed command after implementation and
queried the same endpoints after restarting the API.

`evaluation-before.json` and `evaluation-after.json` are byte-for-byte identical:

```text
Evaluation modes diff: empty
Alert count: 36 -> 36
```

The model schema, pipeline, generator scenarios, evaluation implementation and
`backend/.secret_key` have no changes. Engine changes only add the mapping import
and technique IDs to the existing breakdown dictionaries. The scoring regression
also makes catalog loading raise if scoring tries to consult it.

## Automated checks

- Exact final `python -m pytest -q`: 145 passed (including 21 mapping tests).
- `npm test`: 42 passed in 9 test files, including all existing cases unchanged.
- `npm run build`: passed.
- `git diff --check`: passed.

The sandbox initially prevented pytest from reading old cache folders and creating
its test database, and prevented Vite from spawning esbuild. Checks were rerun
outside the sandbox; no dependencies or test configuration were changed.

## Running application verification

Started the updated FastAPI API on port 8000 and used the Vite app on port 5173.
Used a real headless Chrome browser through DevTools Protocol, authenticated with
the freshly seeded development administrator, and inspected the rendered pages.
`browser.json` records the observed technique links, tactic labels and link attributes.

| Scenario | Page | Observed mapping |
|---|---|---|
| `credential_attack` | `/alerts/2` | T1110 Brute Force, Credential Access, high confidence in the evidence timeline |
| `new_device_exfil` | `/alerts/3` | T1052.001 Exfiltration over USB under Exfiltration |
| `honeytoken` | `/alerts/7` | T1083 under Discovery and T1039 under Collection |

Confirmed technique links point to the corresponding `attack.mitre.org/techniques/`
pages with `target="_blank"` and `rel="noopener noreferrer"`. Verified the analyst
context notice, catalog version and attribution in the mapping section. Inspected
a rendered screenshot. At a 390-pixel mobile viewport the document width remained
390 pixels, and technique chips remained present.

## Deviations and interpretation

- Browser verification was automated in real headless Chrome rather than performed
  through a manual interactive browser session. URLs and link attributes were
  inspected; external technique pages were not clicked in that session.
- In the default seeded `credential_attack` alerts, `repeated_denied_access` has a
  greater weight than `failed_logon_burst` in the same denied category. The existing
  scoring logic therefore excludes the failed-logon indicator from the peak breakdown.
  T1110 appears in the evidence timeline with Credential Access in its accessible
  label, but not in the peak mapping section. This preserves the requested score
  composition and the rule that the summary derives from the stored peak breakdown.
- The build timestamp changes when regenerating the otherwise sorted catalog.
