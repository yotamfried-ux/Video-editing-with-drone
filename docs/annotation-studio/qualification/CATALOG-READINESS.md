# CATALOG_GO readiness — decision record

**Decision (2026-11-03): `NO-GO`.** The operator ran the qualification on the Windows workstation against 7 real DJI 4K/59.94 sources (report `qualification-2026-11-03T09-25-03-974Z.json`, 60 PASS / 0 FAIL / 11 NOT_TESTED, plus a manual UI pass on all 7). That evidence closes most of the gate. Four items keep it NO-GO:

1. **P0 found in real use: saving failed in a loop (fixed in code, needs re-verification on the workstation).** A key moment could be set at a frame outside the selected event (playhead at f0, event `[20,100)`). The server then refused every save of that draft. The UI showed only a short toast, and after a reload the local draft was restored and failed again. Fixed: key moments can only be set inside the event, moving or trimming an event removes values that fall outside it, a draft already stuck this way is repaired automatically on the next save (with a visible note), and a refused save now shows a persistent banner with the reason and "retry" / "load server version". Regression: `e2e/v2` scenario "key moment outside the event…" at both viewports.
2. **R2 token permission not probed.** The run omitted `--probe-delete-permission`, so "token cannot delete" is NOT_TESTED.
3. **Backup is on the same physical disk** (`D:` shares a disk with Windows; run with the same-disk override). Encryption, the key check and the scheduled run are proven. Protection against disk failure is not, and no restore drill was reported.
4. **Operator walkthrough: cataloguing is too hard to follow (P1, open).** The operator reports that the instructions are hard to understand and the catalog flow is too complicated in practice.

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
| Mandatory tests pass | **PASS**: CI green on `a9a1fed` (SQLite, PostgreSQL 144/0/3-skipped, role isolation 8/8, all browser suites); see [CI-AND-SECURITY](CI-AND-SECURITY.md) | Fresh runs, real counts, not prior reports. |
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

Operator run of 2026-11-03 (Windows 11 22631, Node 22.18.0; catalog sync 116 objects: 93 `raw/`, 23 `processed/`, 0 missing). All 7 sources are 3840×2160, 60000/1001 fps, rotation 0, from the legacy `processed/` location (original bytes; SHA-256 recomputed from R2). Proxy↔original mapping: frame N is closer to original N than to N±1 at all 21 sampled frames. The proxy is lossy (≈22–31 dB), and the smallest margin was 0.7 dB (single, f73).

| Case | Source key | Automated (script) | Human box check (operator notes) | Result |
|---|---|---|---|---|
| single surfer | `…DJI_20260724103751_0165_D.MP4` (368 f) | PASS 10/10 | PASS. Checkpoints are crowded on a 6 s clip. | **PASS** |
| ≥2 surfers | `…DJI_20260724103701_0163_D.MP4` (864 f) | PASS 10/10 | PASS. Slow scrubbing needed where the second surfer enters the foam. | **PASS** |
| crossing | `…DJI_20260724103552_0162_D.MP4` (638 f) | PASS 10/10 | PASS. "Wrong surfer" blocked approval; the fix released it (needed an extra save, see P0 1). | **PASS** |
| occlusion | `…DJI_20260724103255_0160_D.MP4` (679 f) | PASS 10/10 | PASS. Occluded recorded. Finding the exit frame needs frame-by-frame stepping. | **PASS** |
| 4K fast motion | `…DJI_20260720164037_0142_D.MP4` (1372 f) | PASS 10/10 | PASS. First proxy ≈15 s, then instant. | **PASS** |
| quality issue / uncertainty | `…DJI_20260720164734_0151_D.MP4` (456 f) | PASS 10/10 | PASS. Glare; `uncertain` defaults were appropriate. | **PASS** |
| no events | `…DJI_20260720165153_0155_D.MP4` (476 f) | PASS 4/4 | PASS. Owner persisted across restart, 0 events. | **PASS** |
| R2 token cannot delete | — | NOT_TESTED (flag not passed) | — | **NOT_TESTED** |
| backup to separate disk + restore | `D:\sportreel-gt` | `verify` ok, encrypted, key verified, 0 objects (no labelled footage yet) | same physical disk as Windows; no restore drill reported | **FAIL (same disk)** |
| scheduled backup ran | `backup.log` 03/11/2026 21:00 | run + verify ok, exit 0 | — | **PASS** |
| save/close/reopen in real use | — | — | save failed in a loop (P0 1, fixed in code) | **FAIL → re-verify** |
| catalog flow understandable | — | — | "too complicated; instructions hard to understand" | **FAIL (P1 open)** |

To close: (a) re-run the save scenario on the workstation after pulling the fix; (b) re-run the script with `--probe-delete-permission` (one case is enough); (c) back up to a disk that is physically separate from Windows (USB disk or NAS) and run the restore drill; (d) simplify the catalog flow and repeat the walkthrough. When every row is PASS and CI is green on the final head, change the decision above to `CATALOG_GO` with the date. Re-read this record before converting the first real label from draft to approved.

## Not covered by CATALOG_GO

Tracking-AI accuracy, any uninspected frame, and the quality of the final published reels are not part of this gate. Reel quality stays `NOT_TESTED`: no real rendered reel was available, and the pipeline is not run without approval.
