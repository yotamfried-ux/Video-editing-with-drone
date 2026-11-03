# CI and security record (spec §22.4-4)

**Code head qualified:** `a9a1fede1e6c15100e494d7b8f3af7ce5555723f` (branch `claude/focused-pasteur-16w1dp`, PR #314).
Later commits on the branch that change only documentation are covered by the CI run on their own head.

## GitHub Actions on `a9a1fed`: all green

| Check | Result | Link |
|---|---|---|
| Annotation Studio Check (`check`): syntax, SQLite suite, PostgreSQL suite + role isolation, browser E2E | **success** (5 min 21 s) | [run 41595881294](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/41595881294/job/125783003493) |
| Secrets, dependencies and configuration (gitleaks + Trivy) | success | run 41595881207 |
| CodeQL (javascript-typescript), CodeQL (python) | success | run 41595881207 |
| OSV dependency visibility, MobSF mobile source scan, Security regression contracts | success | run 41595881207 |
| contract, validate (×4) | success | — |
| OWASP ZAP production baseline, OpenSSF Scorecard | skipped by their workflow conditions (not run for PRs) | — |

Real counts from the `check` job log:

| Suite | Result |
|---|---|
| `npm run check` | 0 syntax errors |
| `npm test` on PostgreSQL 16 | 147 tests: **144 pass, 0 fail, 3 skipped** |
| `npm run test:pg` (roles, isolation, authorization denial, migrations) | **8/8** |
| Browser E2E | run 17/17 · workflow 14/14 · cloud 7/7 · V2 journey (1440×900 + 1920×1080) 19/19 · full-spec 6/6 |

The 3 PostgreSQL skips are intentional: the SQLite-file tamper test, the restart test that reopens the same SQLite home, and the workstation qualification script, which runs on the local SQLite backend.

Local run on the same head (cloud container, Node 22.23.4, ffmpeg 6, Chromium via Playwright): `npm test` (SQLite) **147/147**, exit 0, 119 s; `npm run test:e2e` exit 0 with the same browser counts as CI.

## Before this work (for comparison, on `main`)

- PostgreSQL backend could not be installed. Migration 0004 called the undefined `reject_immutable()`, so every PG test failed, and in CI the PG step hung until the 30-minute timeout (runs cancelled).
- Browser E2E was red: run 11/17, workflow 4/14, cloud failing.
- `npm test` (SQLite): 103/104 in this environment.

## Security boundaries and findings

| Area | State |
|---|---|
| Ground Truth confidentiality on backup media | Every artifact is AES-256-GCM encrypted with scrypt-derived keys. Object names are blinded. The manifest carries a keyed MAC against re-pointing. Plaintext is refused unless the operator attests full-disk encryption. |
| Direct-API hostile documents (BOX evidence, approval gates) | Rejected server-side (`box_truth.test`, including the independent-review regressions) |
| R2 | GET/HEAD only in code; the stub request log shows no writes. The real token's permissions are checked by the operator script (`--probe-delete-permission`). |
| Studio ↔ pipeline separation | The pipeline holds no Studio or Ground Truth credentials (`api.test`). The annotation workbench never loads pipeline outputs (§7 test). |
| Independent review | A separate review agent found 4 P1 and 6 P2 issues. All were fixed with regression tests (commit `13e8b0a`). |
| Open | Real token, real disk and real-footage evidence are the operator's to run (see CATALOG-READINESS). No open code finding is known. |
