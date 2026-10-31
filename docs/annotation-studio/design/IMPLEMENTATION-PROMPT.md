# Antigravity / Claude — Implement SportReel Annotation Studio FULL specification and approved Precision Studio V2

## Goal
Continue the EXISTING SportReel repo yotamfried-ux/Video-editing-with-drone, draft PR #312, not a greenfield rebuild. Implement and qualify the **entire** Ground Truth Annotation Studio requirement set, with the operator-approved Precision Studio V2 look and flows. Main human requirement: manual assignment of an entire cloud video to a specific pseudonymous surfer, independent of events and visible by surfer; accurate human evidence that a bounding box actually follows the correct surfer.

## Authoritative sources — read first
1. docs/specs/ground-truth-annotation-studio.md (ALL sections, especially new §21)
2. docs/annotation-studio/design/PRECISION-STUDIO-V2-IMPLEMENTATION.md
3. docs/annotation-studio/design/precision-studio-v2-approved.html — interactive approved visual prototype; footage image is deliberately synthetic
4. docs/ground-truth-annotation-system-design.md
5. docs/ground-truth-annotation-guidelines-v1.md
6. docs/ground-truth-annotation-design-review-addendum-v1.md
7. docs/annotation-studio/CLOUD-QUICKSTART.md and current code/CI/reviews on PR #312.

Honor the precedence in spec §21 and explicit Local First decision where older mobile-first or separate paid cloud proposals differ. Preserve annotation correctness and blind evaluation. Respect existing code; do not recreate completed functionality.

## Agent tools and token efficiency
Locate Engineering-OS repo, its Knowledge Router/Index and relevant coding/testing/security guidelines. Discover available MCP: GitHub, terminal, Playwright, FFmpeg/ffprobe, Supabase read-only, existing R2 read-only, applicable design tooling. Check installed token-saving CLI or equivalent (e.g. RTK) and use it when available. Focus code search before full-file reads, avoid printing secrets/long logs, use concise test summaries and reuse recent evidence only if it is tied to the correct final SHA. Never trade away test coverage/security to save tokens.

## Mandatory first action
Audit actual HEAD of PR #312, not an older report. Build a requirement-by-requirement traceability matrix of the *entire* spec and the legacy normative design/guidelines: section, status PASS/FAIL/BLOCKED/NOT_TESTED, existing implementation, missing fields/API/UX, tests and risk. Distinguish documentation-only, synthetic, and genuine local R2 test evidence.

## Implement all required functionality, incrementally
A. **Video owner assignment / catalog:** Direct "שייך לגולש" action in Library, Cloud list and player header; existing surfer searchable picker + create; one manually assigned catalog owner per video with unknown/uncertain state, separate from any event performer and all appearances; works with zero events; does not infer owner automatically. A surfer's page displays all assigned videos (even without segments), *separately* from mere appearances. Owner filters, search, bulk preview+confirm, versioned/audited reassignment, local SQLite/PG parity and safe backfill.

B. **BOX correctness:** Make the BOX a first-class visual tool. Ability to select surfer, draw/rescale box, verify against actual source-mapped frames at start, middle, end and risk points (two surfers crossing, occlusion, movement, visibility loss); mark correct / incorrect-correct / occluded / uncertain. Evidence and confirmed-frame coverage with audit history and explicit "needs correction" per track. Never claim linear interpolation or model suggestion is verified tracking; a single correct frame never approves an entire track. Keep source-to-4K coordinate mapping exact.

C. **Complete annotation information:** event kind and sport, performer, important moments, exact start/end, usability usable/partial/no/uncertain with reason codes, event inclusion independently selected, confidence, unknown identities, person appearances, review tasks, physical action duplicates, video-level status, source SHA verification, Ground Truth approvals/revisions, advanced editing framing/EDL data, datasets/evaluator. Preserve original guidelines and semantics; don't silently initialize new segments as include.

D. **Approved V2 UX:** Build on existing Studio UI. Reproduce clickable V2 design: left nav/catalog, central large video/boxes, bottom filmstrip timeline with track lanes, right persistent, clear inspector. Main workflow is intelligible to a new user; explicit owner, performer, video progress, event usability, decision, BOX QA and save/approve statuses. Keyboard+mouse, desktop responsive 1440×900/1920×1080, Hebrew RTL/LTR timecodes, accessibility, visible next action, single-video continue/resume. Use the prototype file as a style/interaction reference, not API code.

E. **Quality:** Studio viewing proxy is 640px CRF38, pipeline configured separately for 4K; quality of actual final reel still needs independent measurement. Provide Quick Preview vs Inspect Original Quality, preserve source-frame coordinates. Compare DJI source -> proxy -> actual rendered reel using EDL to assess sharpness/crop/zoom/compression, or mark NOT_TESTED if real safe output is unavailable. Never change Production encoder without separate approval.

F. **Complete all remaining normative spec:** multi-sport registry and events, identity uncertainty/revisions, operator cursor and review/adjudication, multi-person/cross-video physical action lineage, frozen data, evaluator and editing QA, isolation and backups as required. Do not narrow to a cosmetic MVP. External approvals can be BLOCKED but not pretended complete.

## Safety and execution
- No R2 writes, deletes, moves, RAW recovery, cleanup, deployment or production changes.
- No paid services/resources, changes to Vercel/Supabase secrets/permissions, real pipeline runs, or GitHub merge without my approval.
- Read real R2 footage using existing local read-only token only when permitted, and never export private video or GT frames into public GitHub.
- Before ANY schema migration, make verified recoverable backup of local SQLite and test on isolated copy; preserve all previous drafts, segments, keyframes and immutable approved revisions. Do not silently change source ID, athlete identity, or dataset semantics.
- Work on a dedicated safe branch or existing PR #312 development branch with minimal risk of agent collisions; validate the actual HEAD and existing worktree before writing. Keep PR as draft and request review before any merge.
- Apply focused tests after each incremental change, then full tests; cite actual final commit/workflow runs. Add Playwright scenarios and visual screenshot diff on 1440×900 and 1920×1080, Android/pipeline tests where affected.

## Acceptance before claiming success
1. Zero-event source from existing R2 assigned to Surfer A -> survives restart -> appears in Surfer A's videos.
2. Owner Surfer A; performer Surfer B; other surfer C appears -> no forced cross-assignment.
3. Wrong-person BOX during crossing is flagged, corrected and reviewed over real frame samples; unreviewed interpolation is never called verified.
4. Full event usability/confidence/reasons/key moments/decision saved, reloaded and approved immutably.
5. UI screenshot structure matches approved V2; fast mouse/keyboard interaction, no hidden status selection and no horizontal clipping.
6. Full specs gap matrix complete and P0/P1/P2 mandatory requirements either implemented and proven or explicitly BLOCKED/NOT_TESTED (not falsely passed).
7. Original R2 video unchanged, SQLite verified backup/restoration, no production edits.
8. Studio proxy sharpness and final output sharpness are separately evaluated; do not infer quality from render settings alone.

## Deliverables
Working updated Studio and migration; docs/spec updates only as needed; screenshots, end-to-end test links, final CI, change summary, traceability matrix, concise Windows launch steps, remaining blockers requiring my decision. Keep implementation progressing independently as far as possible, no early stop after a plan or mock.

**Definition of done:** I can quickly assign a real video to a surfer, review and correct each relevant BOX with traceable human evidence, annotate all specified fields through the approved Precision Studio V2 UI, save/reload the data safely and audit it — and all normative specification requirements have honest verified statuses.
