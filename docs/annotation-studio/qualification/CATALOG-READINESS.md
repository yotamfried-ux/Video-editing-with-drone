# CATALOG_GO readiness — decision record

**Decision (2026-11-02): `NO-GO` (BLOCKED).** The code-side P0 gaps found in the §22 audit are fixed and tested. The decision is still NO-GO because the gate in [spec §22.3](../../specs/ground-truth-annotation-studio.md) requires **direct evidence on real DJI sources and on the operator's own machine and backup disk**. None of that could be produced from the cloud development container: it has no R2 credentials and no access to the operator's computer.

This is not a judgment that the software is unfit. **No code P0 gap is open.** Every remaining item is an evidence step that only the operator's environment can supply. The operator converts this to `CATALOG_GO` by running the three steps in "How to close the gate" below and recording the results here.

## Gate checklist (spec §22.3)

| Gate condition | Status | Evidence / what is missing |
|---|---|---|
| Owner/video catalog works end to end | **PASS (syn/stub)** | `e2e/v2` (both viewports), `e2e/cloud`, `owner_http.test`. Real DJI run pending (step 1). |
| GT data saved reliably (save/close/reopen/restart) | **PASS (syn)** | `e2e/run` persistence + offline/conflict, `e2e/workflow` #8, `owner_http` restart, `e2e/v2` reload. |
| BOX never approved by mistake | **PASS (syn)**. Code P0 closed. | `box_truth.test` R1–R10 incl. hostile HTTP documents; `e2e/v2` drag-invalidates and wrong-blocks. |
| Per-frame surfer verification is exact | **PASS (logic)**, **BLOCKED (real)** | Exact-frame binding proven; proxy↔original frame mapping proven on stub media (63 dB exact vs 33 dB neighbours). Real 4K/variable-fps DJI pending (step 1). |
| No concurrent overwrite of assignments | **PASS (syn)** | Truly parallel HTTP requests: exactly one 200 and one 409; bulk rollback; confirmation for reassignment. |
| R2 sources protected from unauthorized read/write | **PASS (code/stub)**, **BLOCKED (real token)** | Connector refuses non-GET/HEAD; stub request log shows GET/HEAD only. Real token permission probe pending (step 1, `--probe-delete-permission`). |
| Secure backup + proven restore | **PASS (syn)**, **BLOCKED (real disk)** | All artifacts encrypted; wrong key/tamper refused; isolated table-by-table restore drill. Real separate disk + Windows schedule + restore from it pending (step 2). |
| Interface usable for real work | **PASS (syn E2E)**, **NOT_TESTED (operator walkthrough)** | Mouse/keyboard journeys at 1440×900 and 1920×1080; screenshots reviewed. A real operator session on 4K footage is still needed (step 3). |
| Mandatory tests pass | **PASS locally**. CI: see [CI-AND-SECURITY](CI-AND-SECURITY.md). | Fresh runs, real counts, not prior reports. |
| No open P0 gap | **Code: none open.** Evidence P0s: BLOCKED (below). | |

## Fixed in this branch (were P0/P1 in the §22 audit or found during this work)

1. **BOX truthfulness (P0):** a verification is bound to the exact frame, segment, performer and geometry. Stale, empty, out-of-range and cross-segment claims are rejected, including via the HTTP API. One checked frame never verifies a track.
2. **Approval honesty (P0):** "wrong surfer" cannot be acknowledged away. Open items are approved only with an audited acknowledgement, recorded as caveats. Independent state axes are exposed and displayed.
3. **Backup confidentiality (P0):** the SQLite snapshot and the footage were plaintext on the backup disk. Every artifact is now AES-256-GCM, plaintext is refused unless the operator attests full-disk encryption, and same-physical-disk detection is added.
4. **New-event defaults (P1):** usability and dataset decision both start `uncertain`.
5. **Performer picker crashed (P0 UX, newly found):** `setSegmentAthlete` was undefined, so choosing "מי ביצע" threw.
6. **Browser regressions on `main` (newly found):** the existing E2E suites were red on `main` (run 11/17, workflow 4/14, cloud partly). V2 had dropped the per-event sport override and Settings editing. The evaluation report told the operator "no discrepancies" at 33% precision. Sport change was impossible after any edit. All are repaired, and the suites are now 17/17, 14/14, 7/7, plus the new V2 journey at 19/19.
7. **Reassignment without confirmation (P1):** the API now requires explicit confirmation to replace or remove an owner.
8. **Visible-surfer role (P1):** a surfer can be recorded as visible without an event and without becoming owner or performer.

## How to close the gate (operator, Windows workstation)

1. **Real-footage qualification** on an isolated copy. It is read-only on R2, never opens your live Studio data, and keeps frames private:
   ```powershell
   cd annotation-studio
   node --env-file=.studio-cloud.env scripts\qualify-real-footage.mjs --evidence "$env:USERPROFILE\sportreel-qualification" `
     --case single=raw/<key> --case multi=raw/<key> --case crossing=raw/<key> --case occlusion=raw/<key> `
     --case 4k_fast=raw/<key> --case quality_issue=raw/<key> --case no_events=raw/<key> --probe-delete-permission
   ```
   Expect `automated_verdict: PASS_AUTOMATED_PART_ONLY` and `token cannot delete: PASS`. Then open the same isolated home in the Studio (`STUDIO_HOME=<evidence>\isolated-gt-…`). For each case, do the `HUMAN` items in the UI: draw and verify boxes at start, middle and end; at the crossing, occlusion and fast-motion checkpoints use Wrong / Occluded where true; save, close, reopen. Record the per-case result in the table below.
2. **Backup:** create the key file, run `scripts\install-backup-schedule.ps1` to an external disk, run `schtasks /Run …`, confirm the log, then restore into `%TEMP%\restore-drill` and open it. Record the disk number, run time, `verify` result and restore result below. Do not record the key.
3. **Operator walkthrough:** catalog 3 real videos in your live Studio: assign owner, events, usability, boxes. **Do not approve.** Note anything slow or unclear.

| Case | Source key | Automated (script) | Human box check | Result |
|---|---|---|---|---|
| single surfer | | | | NOT_TESTED |
| ≥2 surfers | | | | NOT_TESTED |
| crossing | | | | NOT_TESTED |
| occlusion | | | | NOT_TESTED |
| 4K fast motion | | | | NOT_TESTED |
| quality issue / uncertainty | | | | NOT_TESTED |
| no events | | | | NOT_TESTED |
| backup to separate disk + restore | | | | NOT_TESTED |
| scheduled backup ran | | | | NOT_TESTED |

When every row is PASS and CI is green on the final head, change the decision above to `CATALOG_GO` with the date. Re-read this record before converting the first real label from draft to approved.

## Not covered by CATALOG_GO

Tracking-AI accuracy, any uninspected frame, and the quality of the final published reels are not part of this gate. Reel quality stays `NOT_TESTED`: no real rendered reel was available, and the pipeline is not run without approval.
