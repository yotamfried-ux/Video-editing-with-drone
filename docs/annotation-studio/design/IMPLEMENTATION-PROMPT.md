# Claude Code / Antigravity — SportReel Annotation Studio: close all gaps, independently qualify real cataloging

**Version:** 2026-11-02 current-state handoff  
**Repo:** `yotamfried-ux/Video-editing-with-drone`  
**Verified main at review:** `ea73b8647d95f76516c71ec8b8eb61e012196327` (re-fetch HEAD before acting).  
**State:** Precision Studio V2, owner catalog, OCC, Box QA and offsite-backup mechanisms already exist in merged source code; **full operator-ready end-to-end qualification has NOT been independently established**. Prior PRs #312/#313 are merged; do not develop against their old draft heads.  
**Primary requirement:** Real operator can manually assign source video to a surfer before events exist, distinguish ownership/visible people/event performer, accurately annotate and verify a BOX *on that surfer at the exact source frame*, save/reopen safely, approve evidence honestly, and restore confidential Ground Truth after device failure — using approved V2 UX.

## A. Read first; no implementation before evidence baseline

Read fully:
1. `docs/specs/ground-truth-annotation-studio.md` §§1–22, especially the current evidence ledger §22.
2. `docs/annotation-studio/design/PRECISION-STUDIO-V2-IMPLEMENTATION.md` and `precision-studio-v2-approved.html`.
3. `docs/ground-truth-annotation-system-design.md`, `docs/ground-truth-annotation-guidelines-v1.md`, `docs/ground-truth-annotation-design-review-addendum-v1.md`.
4. `docs/annotation-studio/OPERATOR-GUIDE.md`, `CLOUD-QUICKSTART.md`, historical `STATUS-PHASE-B.md`.
5. Actual current code and test suites, especially `server/{annotations,catalog_owner,offsite,cloud,media,app,db}.mjs`, `web/js/{annotate,library,cloud,others}.js`, `tests/{box_qa,owner_catalog,offsite,api}.test.mjs`, `tests/e2e/` and CI workflows.

Inspect `git status`, `git fetch`, `origin/main` and local changes before writing. Start a **new non-destructive feature branch** from updated main. Don't reset/overwrite unsaved work. Do not trust summaries or older CI, and never mark a requirement PASS solely because a test file exists. Create requirement traceability row for every normative requirement: ID, exact section, as-built path, current gap, severity, needed proof, PASS/FAIL/BLOCKED/NOT_TESTED, SHA, test/evidence. Don't treat old superseded deployment suggestions as current, but keep all labeling/data-quality requirements.

## B. Mandatory P0 fixes (implement, test, rerun)

### B1. BOX ground-truth correctness
There is a **known server-side defect**: `server/annotations.mjs:validateContent` can accept `box_verifications[].status='verified_correct'` where the only box is a keyframe somewhere else in the segment; `web/js/annotate.js` can submit a verification without a `curBox`. Replace that broad fallback with a precise, auditable invariant:
- A verification is tied to **source ID, selected segment/track, exact source frame, athlete identity, candidate bbox, current geometry/version and independent human verification**.
- Require a real valid source-frame BOX at the inspected frame (exact manual keyframe or source-mapped interpolated candidate whose geometry at the requested frame is explicitly recorded and checked). Never accept an absent box, unrelated-frame keyframe, out-of-segment frame, mismatched performer or stale geometry revision.
- Draw/edit/resize box -> `unreviewed`. Verify click -> `verified_correct` only after actual displayed frame and geometry are available and the human explicitly confirmed. `wrong_performer` and `occluded` are not positive verification. An unverifiable segment cannot be called fully verified.
- Changing bbox/performer, splitting events or reassigning identity must invalidate only the dependent verification evidence (retain immutable history), plus re-review nearby crossing/occlusion frames. No automatic approval from linear interpolation or AI suggestions. Avoid relying on trusting client-provided timestamps/operator strings as proof; validate/inject server provenance appropriate to the single-user localhost identity model.
- Evidence sampling: begin/mid/end/inflection plus crossings, occlusion, identity switches and temporal gaps; display **reviewed points/ranges** versus inferred track. Do not confuse `3/4 checkpoints` with 75% of every frame verified.
- Add malicious direct HTTP/API tests, state/revision round trips, identity crossing and frame mapping tests; include one low-resolution proxy vs actual high-resolution frame check.

### B2. Default/event/approval accuracy
- New events currently default `decision='uncertain'` (good) but `usability='usable'` (unsafe). New usability should default `uncertain` until human decides. Do not silently rewrite legitimate historic records; any migration must preserve approved revisions.
- Validate usable/partially_usable/unusable/uncertain and all reason codes, unknown identity, partial-action boundaries, key moments and source frames; labels must round-trip and exports must preserve uncertainty.
- Evaluate `approve()` and `unresolved()`: current checks focus on undecided segments/missing performer, not complete box/identity/temporal evidence. Implement explicit scope-aware review readiness rules matching the normative spec. "Draft saved", "source belongs to surfer", "verified a frame", "eligible for dataset", "approved GT revision", and "frozen dataset" MUST remain independent.
- If the operator can explicitly approve limited/unresolved scope, record precisely what is waived and never label uninspected frames "verified". Tests must demonstrate reject/allow boundaries without adding an impossible requirement to label every frame.

### B3. Confidential, recoverable independent backup
- Existing offsite tool uses AES-256-GCM for the logical JSON export **only**; `VACUUM INTO` SQLite file and any locally copied original video remain plaintext in backup destination. Fix this privacy exposure by encrypting all sensitive backup artifacts before leaving the trusted source or proving an operator-authorized encrypted destination with verified device encryption; avoid unencrypted temporary files. Maintain versioned manifests, SHA hashes and independent integrity check.
- Device `st_dev`/volume ID alone is not proof of a separate physical disk; confirm Windows physical disk/volume mapping or use other provable independent hardware/network storage, and report uncertain cases honestly. Do not assume C: and D: are physically different.
- Secure key lifecycle and disaster recovery: no secrets in args/logs/PR/screenshots, test loss of key (fail closed), tampered ciphertext, wrong key, corrupted archive, previous snapshot survival. Verify actual isolated restore from independent destination for database, owner history, approved GT, BOX QA, local footage that is in selected backup scope and preview regeneration.
- Inspect Windows Task Scheduler; if not configured, add a safe operator-approved recurring schedule or explicitly BLOCK as requiring operator action. Provide stale/failed backup alert proof. Never claim a green status solely because a backup ran once.
- No new paid services, no uploads of raw private video to public GitHub or another cloud provider.

### B4. Owner OCC and source/cloud consistency
- Most strict OCC is now in code (`expected_version` required for single, bulk, cloud), but test every entry point: Library, Cloud, Workbench, zero-event owner, multi-source preview/commit, reassign, unassign, direct API with missing/wrong version, SQLite and PostgreSQL. Validate true 400/409 and atomic rollback with no history mutation on failure.
- Explicitly exercise linked cloud object/source versions when they diverge due to prior independent edits; guarantee one authoritative logical owner and no silent loss. Reconciliation must be reversible/audited and preserve approved event performer/visible appearances.

## C. All remaining normative requirements; do not stop at P0

Inspect and implement all needed requirements in §§1–22 and all normative design/guidelines/addendum documents, including:
- Single-video catalog owner chosen manually before an event; surfer library with assigned-vs-visible filters, bulk/individual actions, search, continue/reopen, future uploads and duplicate-source lineage.
- V2 dark desktop interface exactly matching approved layout in **1440×900 and 1920×1080**: left catalog, large player, right inspector, multitrack timeline/filmstrip, identity-labeled BOX and clear Basic/Advanced flow, Hebrew RTL, accessible keyboard/mouse, intuitive status and progress. Prefer real screenshots/video and operator journey, not DOM-only checks.
- Full labeling fields: sport-aware event taxonomy, important moments, event-scoped performer, visible/unknown identities, confidence/versioning, usability/reasons, inclusion decision, original-frame coordinates, editing labels and reviewed coverage; no silent certainty or automatic include.
- Independent `AnnotationSet`/`AnnotationAssignment` streams when required, blind evaluation, immutable approval, reviewed revisions, adjudication/reviewer disagreements, `PhysicalActionEntity`/`ActionOccurrence` duplicate lineage, person merge/split version history, deterministic event matching, reproducible multi-label agreement, dataset freeze acceptance and editing-quality evaluation. Do not use "future" as a blanket excuse for requirements that the specification marks normative. Document any truly operator-deferred product change explicitly.
- Multi-sport backlog declared in §20.1 (e.g. sport suggestions requiring confirmation, `source_sports`, sport-stratified datasets, sport-specific quality metrics): inspect exact mandatory scope, implement what normative contract requires or retain as FULL_SPEC_GO blocker with reason.
- Real video QA: R2 read-only source, real original DJI frame vs 640px proxy vs actual rendered reel; exact time/EDL lineage, rotation/VFR/59.94 fps and crop, sharpness/subject placement/box tracking. Never claim final output quality from CRF/4K settings; if a real rendered reel cannot be safely obtained without pipeline runs, mark NOT_TESTED, not PASS.

## D. Mandatory qualification: no simulated success claim

Run under a fresh **isolated STUDIO_HOME and disposable GT copy**, while R2 access is GET/HEAD only; never overwrite the live operator database, history or existing labels. Start from a verified backup/restore and record source counts without posting private data.

1. Unit and full integration tests: `cd annotation-studio && npm run check && npm test && npm run test:e2e`, then PostgreSQL parity and isolation with supported test DB, and all relevant repo-level security/raw-protection checks. Capture exact commands, stdout summaries, exit codes, final SHA, and job URLs. Improve tests until representative edge cases fail before fix and pass after (red-green-refactor).
2. Browser acceptance for **real DJI 4K** video with owner assignment with ZERO events, dedicated surfer listing, event performer different from catalog owner, missing identity case, BOX on correct surfer, wrong-surfer/crossing, occlusion, editing verified box invalidation, start/mid/end/inflection samples, source-quality selection and frame-accurate seek, draft save, browser restart, server restart and immutable approval under correct conditions. Prefer multiple real source categories, not one easy frame.
3. Explicitly verify R2 raw/processed inventory and that the client cannot write/delete/modify `raw/`; don't use destructive tests to prove read-only. Historical 116/93/23 inventory is a **reported snapshot**, not a fixed expected count. Differentiate 24 original DJI and other fixtures; do not publish frames or cloud tokens in GitHub.
4. Operator usability: the user must be able to discover how to assign a video, inspect own videos, mark events, verify correct BOX, see reviewed-vs-unreviewed, understand partial/unusable/uncertain, recover from a 409, save safely and resume. Check visual fidelity and keyboard/accessibility at both resolutions. Record time/click friction and operator-visible failure messages.
5. Fault injection: R2 temporary outage, low disk space, DB interrupted save, stale browser draft, source change, corrupted backup, wrong key, colliding surfer assignments and stale box evidence. Prove no silent loss or false approval.
6. Final-source comparison: run three-way source/proxy/actual reel where safe; otherwise clearly `NOT_TESTED`. Don't launch production pipeline to manufacture evidence without permission.
7. GitHub Actions: studio workflow currently triggers for **PR changes**, not necessarily on merge `push`; open implementation PR, run full matched CI at PR HEAD, preserve screenshots/logs, check no cancellation/skip of mandatory jobs and all security checks. Vercel green by itself is not proof.
8. Independent review agent / read-only verification: inspect actual code and artifacts, catch untested claims, and rerun representative acceptance tests independently.

## E. Two gate outputs; finish full spec while permitting a safe pilot only if warranted

Create/update:
- `docs/annotation-studio/qualification/REQUIREMENTS-MATRIX.md` — all requirements and direct evidence, no invented PASS.
- `docs/annotation-studio/qualification/CATALOG-READINESS.md` — `CATALOG_GO` or `NO-GO` for starting real manual cataloging, with explicit checklist, backup/restore and real-video evidence.
- `docs/annotation-studio/qualification/FULL-SPEC-READINESS.md` — `FULL_SPEC_GO` or `NO-GO` for *all* normative research/evaluation/UX capabilities.
- `docs/annotation-studio/qualification/CI-AND-SECURITY.md` — exact SHA, commands, CI and security status, data integrity and blocked actions.

`CATALOG_GO` requires all high-risk manual cataloging and data correctness P0 items, actual UI proof, safe R2 source access and confidentiality/recoverability, plus an operator-reviewed report before approving the first actual label. `FULL_SPEC_GO` additionally requires all remaining normative feature/data/evaluation requirements to be independently proven. A failed or unrun requirement must remain `FAIL`/`NOT_TESTED`/`BLOCKED`, not green.

**Continue to implement through the full specification** instead of ending as soon as the pilot is safe. If a real external dependency or permission blocks further work, finish everything reversible and safe first, then report exactly which action requires authorization; do not promise asynchronous work.

## F. Scope and approval

Allowed: isolated branch/PR, code fixes, backwards-compatible migrations on copies, tests and screenshots using synthetic or locally isolated real source/GT, read-only R2, secure independent backups to already-approved destination, local app startup and tool discovery. Preserve cost/efficiency (Engineering-OS, available MCP, FFmpeg, Playwright and focused terminal output).

**Not allowed without additional explicit authorization:** write/delete/move/restore any R2 object, any production run/deploy, overwrite approved GT or active local DB, create cloud-paid services, change production keys/permissions, publish actual footage or raw GT, merge implementation PR to main, or mark uncertain labels as human verified. Stay on branch and give the operator reviewable PR/evidence.

**Final response:** list actual implemented diffs, PASS/FAIL/BLOCKED/NOT_TESTED per normative requirement, GitHub CI and local proof, backup encryption scope and physical-device proof, approved V2 UI comparison, sampled real-video truth test, explicit `CATALOG_GO` and `FULL_SPEC_GO`, remaining blockers, and exact Windows start steps. Do not call the system fully complete based only on `104/104` unit tests, a historical report, or one 4K screenshot.

**Success:** a human can confidently and quickly catalog a DJI source to its owner, inspect/correct exact-frame BOX on the right surfer, label complete events, save/reload/restore Ground Truth and use frozen data without false confidence. Both readiness gates must have honest verifiable dispositions.
