# Requirements traceability matrix — Annotation Studio (Precision Studio V2)

Living qualification record required by [spec §22.4](../../specs/ground-truth-annotation-studio.md). One row per normative requirement. A row is `PASS` only if an **executed** test/evidence on the commit listed in [CI-AND-SECURITY](CI-AND-SECURITY.md) proves it. Code alone, or an unexecuted test file, is never `PASS`.

**Statuses:** `PASS` / `FAIL` / `BLOCKED` (needs an authorization or the operator's environment) / `NOT_TESTED` / `NOT_IMPLEMENTED`.
**Data:** `syn` = synthetic ffmpeg media or fixtures; `stub` = real H.264 media behind an S3-compatible stub; `real` = real DJI footage (none here, see CATALOG-READINESS).
**Severity of the remaining gap:** P0 blocks real cataloging; P1 is required for the approved V2 experience; P2 is required for FULL_SPEC.
**Reviewer:** Claude Code (agent) plus an independent review agent. **Date:** 2026-11-02.

Test files live under `annotation-studio/tests/`. Browser suites are `tests/e2e/{run,workflow,cloud,v2}.mjs`.

## A. Catalog ownership, roles and OCC (§21.1)

| ID | Requirement | Code | Proof (executed) | Data | Status | Remaining gap | Sev |
|---|---|---|---|---|---|---|---|
| OWN-1 | Nullable manual owner, default Unassigned, never inferred | `server/catalog_owner.mjs`, migration 0004 | `owner_catalog.test` (9), `owner_http.test` (6) | syn | PASS | — | — |
| OWN-2 | "שייך לגולש" on the Library card, works with zero events; quick-create surfer | `web/js/library.js` | `e2e/v2` "assign a video with NO events…" at 1440 and 1920 | syn | PASS | Cloud-row and header path covered by `e2e/cloud` and the unit tests; no browser test for the bulk dialog | P2 |
| OWN-3 | Surfer Workspace lists zero-event videos immediately | `web/js/others.js`, `listAthleteSources` | `e2e/v2` workspace scenario; `owner_http` "assignment without events…" | syn | PASS | — | — |
| OWN-4 | Owner ≠ visible ≠ performer ≠ edit target; never auto-propagated | `annotations.mjs addAppearance`, `annotate.js` performer picker | `owner_http` "three independent roles", `owner_catalog` "three-way independence" | syn | PASS | Edit-target role not modelled separately (see EVAL rows) | P2 |
| OWN-5 | Reassignment needs explicit confirmation; audited with reason; undo = compensating action | `catalog_owner.mjs` `confirm_reassign/confirm_overwrite` | `owner_http` "reassigning an owned video requires explicit confirmation…" | syn | PASS | — | — |
| OWN-6 | OCC: missing/malformed version → 400; stale → 409; truly parallel requests → exactly one wins | `catalog_owner.mjs` CAS update | `owner_http` "two parallel assignments…", "malformed or missing…" | syn | PASS (SQLite) | PG parity: see PG rows | — |
| OWN-7 | Bulk: preview, conflicts listed, stale → full rollback, overwrite needs confirmation | `bulkSetCatalogOwner` | `owner_http` bulk test; `owner_catalog` bulk OCC | syn | PASS | — | — |
| OWN-8 | Link by immutable source identity (sha256), not path; restart persistence | `sources` identity triggers | `owner_http` restart; `ingest.test` identity tests; `e2e/cloud` #5 | syn/stub | PASS | Real R2 identity on DJI sources | P0 → BLOCKED (real) |
| OWN-9 | Migration never promotes segment performers to owners | 0004 (no backfill) | `owner_catalog` #1 | syn | PASS | — | — |

## B. BOX truthfulness and track QA (§21.2, §22.2 P0-1)

| ID | Requirement | Code | Proof | Data | Status | Remaining gap | Sev |
|---|---|---|---|---|---|---|---|
| BOX-1 | A verification is bound to the exact frame, segment, performer and geometry | `server/trackqa.mjs validateBoxEvidence` | `box_truth` R1/R2 (evidence elsewhere in segment refused, another segment's box refused, out of range, malformed) | syn | PASS | — | — |
| BOX-2 | Cannot verify a box that does not exist or is invalid at that frame | same | `box_truth` R1/R2, R10 over HTTP (`BOX_NOT_AT_FRAME`) | syn | PASS | — | — |
| BOX-3 | Drawing ≠ verifying | `annotate.js putKeyframe`, keyframe flags must match log | `box_truth` R3; `e2e/v2` "drawn != verified" | syn | PASS | — | — |
| BOX-4 | Geometry change invalidates the earlier decision | append-only log + `reconcileVerifications` | `box_truth` R4; `e2e/v2` drag scenario | syn | PASS | — | — |
| BOX-5 | Performer change invalidates identity decisions; no verify without a performer | `validateBoxEvidence`, `setSegmentAthlete` | `box_truth` R5; `box_qa` #3 | syn | PASS | — | — |
| BOX-6 | Interpolation is never verification | origin stays `interpolated`; log is the authority | `box_truth` R6/R7; `box_qa` #2 | syn | PASS | — | — |
| BOX-7 | One frame never verifies a track; checked range and event-span share shown | `segmentTrackQa` (≥2 positive frames, all checkpoints, gap policy) | `box_truth` R6/R7, R7b; `e2e/v2` "verified-one-frame" = partially_checked | syn | PASS | — | — |
| BOX-8 | Risk checkpoints: crossings, occlusion, fast motion, exit/return | `requiredCheckpoints` | `box_truth` R8 | syn | PASS (logic) | Detection is geometric on the operator's boxes, not on the image; real crossing footage not tested | P0 → BLOCKED (real) |
| BOX-9 | Evidence kept: reviewer, time, corrections, history | append-only `box_verifications` | `box_truth` R9 | syn | PASS | — | — |
| BOX-10 | Direct API cannot create a false verification or approval | server validation + blocking gate | `box_truth` R10 (HTTP); independent review agent | syn | PASS | — | — |
| BOX-11 | Box coordinates and frames refer to the ORIGINAL source when viewed via the 640px proxy | normalized source coords; frame = source index | `box_truth` "4K source…low-resolution proxy"; `qualify_script` PSNR frame mapping (63 dB exact vs 33 dB neighbours) | syn/stub | PASS | Variable fps, rotation and real 4K DJI not tested | P1 → BLOCKED (real) |
| BOX-12 | Distinct visual styles for verified / interpolated / unverified / wrong (text and icon, not colour only) | `annotate.js paintOverlay`, kflist pills | `e2e/run` "interpolated boxes are visually distinct"; screenshots reviewed | syn | PASS | AI-suggested origin has no dedicated style yet (no suggestions exist) | P2 |
| BOX-13 | Wrong surfer creates Needs Correction and blocks approval | `unresolved().blocking` | `box_truth` R10; `e2e/v2` "approval blocked" | syn | PASS | No separate review-task object (the flag is the task) | P2 |
| BOX-14 | Legacy unbound verifications are neutralized on read; approved revisions untouched | `upgradeLegacyBoxQA` | `box_truth` legacy test | syn | PASS | — | — |

## C. Labels, defaults and approval semantics (§21.3, §22.2 P0-3, P1-4)

| ID | Requirement | Code | Proof | Data | Status | Remaining gap | Sev |
|---|---|---|---|---|---|---|---|
| LBL-1 | New event: usability=uncertain, decision=uncertain | `annotate.js createSegment` | `e2e/v2` I/O scenario; `box_truth` "new events…" | syn | PASS | — | — |
| LBL-2 | Historical labels and decisions are not reinterpreted | no migration of stored values; legacy shown as undecided, not "usable" | code review; `annotations.test` | syn | PASS | — | — |
| LBL-3 | Usability classes + structured reasons; partial/unusable need a reason | `USABILITY`, `REASON_CODES`, `unresolved.missing_reason_codes` | `box_truth` "new events…" | syn | PASS | Reason-code taxonomy is not versioned per guideline v1 §usability | P2 |
| LBL-4 | Key moments (takeoff/peak/landing/inflections) within the event | `validateContent` | `box_qa` #1 | syn | PASS | — | — |
| LBL-5 | Independent state axes, never one pill | `sourceStates`, states panel | `box_truth` R3, R10; `e2e/v2` reopened-states | syn | PASS | — | — |
| LBL-6 | Video-level "needs review" without segments | `review_request` | `e2e/v2` (panel present); `annotationStatus` | syn | PASS | — | — |
| LBL-7 | Blocking items cannot be acknowledged; others need an audited acknowledgement | `approve()` | `box_truth` R10 and the "acknowledged approvals…" test | syn | PASS | — | — |
| LBL-8 | Approval records scope and caveats; never upgrades frames to verified | `approval_caveats` in audit | `box_truth` "acknowledged approvals…" | syn | PASS | Interval/segment scope is recorded as a note only; the revision is always the whole document (stated in the UI) | P2 |
| LBL-9 | Save/load, undo/redo, local draft recovery, conflict surfaced | `annotate.js` | `e2e/run` (offline→recover, conflict), `e2e/v2` undo/redo + reload | syn | PASS | — | — |
| LBL-10 | Existing video opens with a selected event | `renderAnnotate` | `e2e/v2` reload → segform visible | syn | PASS | — | — |

## D. Backup and recovery (§3, §22.2 P0-2)

| ID | Requirement | Code | Proof | Data | Status | Remaining gap | Sev |
|---|---|---|---|---|---|---|---|
| BAK-1 | Every artifact on the medium encrypted (DB export, SQLite snapshot, footage) | `backupcrypto.mjs`, `offsite.mjs runEncrypted` | `offsite.test` "nothing readable on the medium" (byte scan for footage, SQLite header, hashes, key) | syn | PASS | — | — |
| BAK-2 | Key never written; weak key refused; plaintext only with device-encryption attestation | same | `offsite.test` "encryption is mandatory…" | syn | PASS | Key escrow is the operator's (password manager) | — |
| BAK-3 | Wrong key, missing key, tampering → clear failure; never a partial restore | GCM auth + verify-before-restore | `offsite.test` "wrong key, missing key and tampering…" | syn | PASS | — | — |
| BAK-4 | Full restore into an isolated empty home: surfers, videos, owners, history, events, boxes, revisions | `restoreFromOffsite` | `offsite.test` "ENCRYPTED RESTORE DRILL…" (table-by-table equality), `e2e/workflow` #13 | syn | PASS | Real restore from the operator's physical disk | P0 → BLOCKED |
| BAK-5 | Separate physical device, not only a different volume | `physicalDiskOf` (Linux sysfs, Windows Get-Partition) | `offsite.test` "same physical disk…" (injected) | syn | PASS (logic) | Windows `Get-Partition` path not executed here | P0 → BLOCKED |
| BAK-6 | Scheduled automatic backup actually runs | `scripts/install-backup-schedule.ps1` | — | — | NOT_TESTED | Run on the operator's Windows machine and confirm a logged run | P0 → BLOCKED |
| BAK-7 | Alert when the last backup is stale, missing, failed or unencrypted | `backupStatus`, `ui.js backupBanner` | `offsite.test` status; `e2e/run` banner; `e2e/workflow` #13 | syn | PASS | — | — |

## E. Security, isolation and raw protection (§3, §14, §16)

| ID | Requirement | Code | Proof | Data | Status | Remaining gap | Sev |
|---|---|---|---|---|---|---|---|
| SEC-1 | Token auth, Host/Origin checks, HttpOnly cookie, no secrets in the browser | `app.mjs` | `api.test` #8–#11; `e2e/cloud` #6 | syn/stub | PASS | — | — |
| SEC-2 | R2 connector GET/HEAD only | `cloud.mjs CloudBucket` | `cloud.test`; `e2e/cloud` #6 (stub request log); `qualify_script` (no non-GET/HEAD) | stub | PASS | Real token permissions: run `--probe-delete-permission` | P0 → BLOCKED |
| SEC-3 | Immutable revisions, datasets, audit and owner history (DB triggers) | `db.mjs`, PG roles | `annotations.test`, `e2e/workflow` #12, `pg/isolation.test` | syn | PASS (SQLite); PG see below | — | — |
| SEC-4 | Production pipeline never references the Studio or its credentials | — | `api.test` #16/#17 (now uses git's file list) | repo | PASS | — | — |
| SEC-5 | Raw archive protection (write-once, no delete method) | `archive.mjs`, `r2archive.mjs` | `r2archive.test`, `ingest.test` | stub | PASS | Live bucket lock probe needs approval (`probe-archive-protection.mjs`) | P1 → BLOCKED |

## F. UI / UX (§21.4)

| ID | Requirement | Proof | Status | Remaining gap | Sev |
|---|---|---|---|---|---|
| UX-1 | 1440×900 and 1920×1080: library, large central player, right inspector, multitrack timeline visible, no horizontal scroll | `e2e/v2` layout and visibility scenarios; screenshots reviewed by eye | PASS (syn) | Pixel comparison with `precision-studio-v2-approved.html` not automated; visual review only | P1 |
| UX-2 | Hebrew RTL, LTR timecodes | `e2e/v2` dir=rtl; screenshots | PASS | — | — |
| UX-3 | Mouse + keyboard actually perform the actions (not just DOM presence) | `e2e/v2` (mouse draw/drag, I/O/B/E/Ctrl+Z), `e2e/run` keyboard-only tab order | PASS | — | — |
| UX-4 | Basic before advanced; one obvious next action | inspector tabs + states panel | NOT_TESTED (no usability study) | Needs an operator walkthrough | P1 |
| UX-5 | Accessibility (labels, focus, not colour-only) | partial checks in `e2e/run`; text and icon status pills | PARTIAL → NOT_TESTED | No axe/contrast audit | P2 |
| UX-6 | Per-event sport override; Settings to add sports or event types (regressed in V2, restored) | `e2e/workflow` #5, #7 | PASS | — | — |
| UX-7 | Evaluation report lists every error and sport-separated metrics (regressed in V2, restored) | `e2e/run` evaluations; `e2e/workflow` #10 | PASS | — | — |

## G. PostgreSQL parity

| ID | Requirement | Proof | Status |
|---|---|---|---|
| PG-1 | Full unit/integration suite on real PostgreSQL 16 | `STUDIO_TEST_DB_URL=… npm test` (see CI-AND-SECURITY for counts) | see CI-AND-SECURITY |
| PG-2 | Role isolation / authorization denial | `npm run test:pg` | see CI-AND-SECURITY |

## H. Advanced normative Ground Truth (addendum v1, system design) — FULL_SPEC

| ID | Requirement | Status | Note | Sev |
|---|---|---|---|---|
| ADV-1 | `AnnotationSet` / `AnnotationAssignment` independent annotation streams | NOT_IMPLEMENTED | Drafts are keyed by source only | P2 |
| ADV-2 | Review / adjudication workflow between streams | NOT_IMPLEMENTED | depends on ADV-1 | P2 |
| ADV-3 | Set-scoped identities | NOT_IMPLEMENTED | | P2 |
| ADV-4 | `PhysicalActionEntity` / `ActionOccurrence`: same physical action across videos | NOT_IMPLEMENTED | | P2 |
| ADV-5 | `PersonLineageRelation`: revisioned merge/split of identities | NOT_IMPLEMENTED | | P2 |
| ADV-6 | Raw-only boundary adjustment | NOT_TESTED | not traced | P2 |
| ADV-7 | Deterministic one-to-one event matching with a versioned config | PARTIAL | `server/evaluate.mjs` is deterministic and tested (`evaluation.test`); not checked against addendum §8 ranking/inconclusive rules | P2 |
| ADV-8 | Jaccard multi-label agreement | NOT_IMPLEMENTED | needs ADV-1 | P2 |
| ADV-9 | Unique evaluation identity / idempotency | PARTIAL | digest-identical reruns tested (`e2e/workflow` #10); addendum §10 not fully traced | P2 |
| ADV-10 | Reproducible frozen datasets | PASS | `datasets.test` / `e2e/run` datasets | — |
| ADV-11 | Blind evaluation (no label leakage) | PASS | `evaluation.test` "blind manifest…" | — |
| ADV-12 | Editing output: source vs proxy vs final reel quality | NOT_TESTED | needs a real rendered reel; the pipeline is not run without approval | P1 |
| ADV-13 | Sport suggestion with confirmation, `source_sports`, sport-stratified datasets/metrics | PARTIAL | sport-separated evaluation PASS (`e2e/workflow` #10); suggestion/stratified datasets not implemented | P2 |
