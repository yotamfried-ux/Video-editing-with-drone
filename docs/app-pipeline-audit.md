# SportReel operational-readiness audit

Date: 2026-07-23  
Repository: `yotamfried-ux/Video-editing-with-drone`  
Validated baseline: `main` at `f0ce8d742110a2101dd86fa37a07d54409b01bc2` (merged PR #195), plus the upload implementation under review in PR #196.  
Status: **open — the safe large-upload foundation is implemented, but live release/device evidence and the broader product gaps remain open**

This file is the authoritative, consolidated readiness audit for the operator app, R2 upload path, GitHub Actions pipeline, Supabase state, perception/tracking, 4K rendering, QA, Review, Delivery, Discover, payments, and the real-footage evidence required by the product vision.

Historical implementation details remain in focused files under `docs/audit/` and in Git history. When a focused audit conflicts with this file about whether a gap is still open, this file controls until both are reconciled in the same PR.

## 1. Product outcome and closure rule

The product source of truth remains:

> Every distinct athlete with at least one complete, visible, usable action receives a personal, silent, publishable social-media reel centered on that athlete, or an explicit evidence-backed hard rejection.

For surfing, every complete readable usable wave must appear exactly once. Other people may remain visible when the featured athlete stays identifiable, continuous, central, and owns the action. A GitHub Actions success, a rendered file, or an LLM response is not sufficient proof.

Three readiness levels are used:

1. **Foundation implemented** — code, schema, deterministic tests, and review evidence exist.
2. **Experiment entry ready** — the exact deployed API/database/storage/mobile stack can safely execute the next evidence-producing experiment.
3. **Product gap closed** — the mandatory end-to-end checklist passed with real services, an installed Android build where applicable, real footage, preserved artifacts, and visual review.

Green CI alone never closes a mobile-storage, external-service, footage-quality, identity, delivery, or payment gap.

## 2. Evidence rules

Acceptable evidence includes:

- PR number and exact commit SHA;
- final-head CI workflow/run URL and conclusion;
- Vercel Production deployment tied to the exact commit;
- EAS build/upload ID and the exact APK installed on the tested Android device;
- Supabase migration output plus read-only schema/data verification;
- R2 key, multipart upload metadata, exact part ledger, `HEAD` result, hash, size, retry, abort, and deletion evidence;
- durable `source_uploads`, `upload_batches`, `pipeline_runs`, `delivery_runs`, QA, feedback, or purchase row identifiers without secrets;
- Android physical-test record including storage before/after, network interruption, app restart, and SD/USB behavior;
- pipeline diagnostic artifacts and direct visual inspection of final videos.

Not acceptable as closure evidence:

- “the code looks correct”;
- a PR Preview when Production behavior is claimed;
- one successful HTTP response without downstream state verification;
- a screenshot without correlated API/database/storage/workflow evidence;
- a synthetic fixture standing in for a required real-device, real-service, or real-footage test;
- upload success without final object-size verification;
- dispatch acceptance without a correlated workflow run;
- any secret value in an audit, PR, screenshot, artifact, or log.

## 3. Current verified foundation

The following statements are supported by code and deterministic checks in merged PR #195 and PR #196:

- R2 source objects are scoped under immutable `raw/<batch_id>/...` keys.
- PR #195 adds durable source-upload manifests and exact byte-duplicate reconciliation using streaming SHA-256. The newest first-successfully-verified source is canonical; older exact duplicates become ineligible and their deletion result is audited.
- Android SD/USB upload no longer requires a complete phone-cache copy. A focused Expo SDK 52 local module reads bounded ranges from a seekable `content://` descriptor.
- Multipart upload records exact R2 part ETags, retries only missing parts, completes in ascending part order, and verifies final `HEAD Content-Length` before `verified`.
- A stable `client_upload_id` is persisted before multipart start, making lost-response and concurrent-retry recovery idempotent.
- AsyncStorage and Supabase preserve source identity, upload ID, batch ID, part size, completed parts, ETags, retry state, and cleanup state.
- App-owned temporary upload artifacts are removed only after durable R2 verification. The application refuses to delete the original SD/USB URI, verifies absence of deleted artifacts, and records reclaimed bytes and cleanup errors.
- `upload_batches` calculates readiness from durable server state. Pipeline admission is rejected until every intended source is present, size-matched `verified`, and any required local cleanup is confirmed.
- Gallery uploads send a stable local size where available. The legacy single-PUT fallback records weaker size evidence explicitly as `r2_head_adopted` instead of treating it as client-declared evidence.
- Expo SDK 52's official Storage Access Framework implementation persists granted directory-tree permission using `takePersistableUriPermission`.
- TypeScript checks, Expo module autolinking, Android prebuild, and Kotlin compilation cover the native upload foundation.
- `.github/workflows/upload-foundation-release.yml` is fail-closed: migrations and schema verification must pass, then a real R2 multipart/hash/cleanup probe must pass, and only then may the installable Android preview APK be built.

These statements prove **foundation implemented**. They do not yet prove the exact live Supabase/R2/Vercel/EAS/device stack.

## 4. Readiness summary

| Gap | Priority | Current state | Blocks the next production-style experiment? |
|---|---:|---|---|
| GAP-013 — Resumable multipart R2 upload | P0 | Foundation implemented; live R2/interruption evidence pending | Yes, until release/device evidence passes |
| GAP-014 — Durable Android source access and restart recovery | P0 | Native bounded reader and durable ledger implemented; installed-device evidence pending | Yes, until APK/device evidence passes |
| GAP-015 — Durable batch/session/athlete upload manifest and verified-run gate | P0 | Source/batch manifest and admission gate implemented; business grouping and real-batch evidence remain open | Yes for the full experiment |
| GAP-016 — Dispatch, workflow, run, and operator-status correlation | P0 | Dispatch acceptance is explicit; one real correlated transition is not yet proven | Yes |
| GAP-017 — Real perception/tracker quality and identity stability | P0 | Mandatory CV and diagnostics exist; difficult-footage quality/tuning remains unproven | Yes |
| GAP-018 — Cross-source athlete grouping and duplicate control | P0 | Diagnostics exist; durable reel-group lineage and real grouping proof remain open | Yes |
| GAP-019 — 4K/30 visual-quality and performance budget | P0 | Synthetic media contract passes; real quality/runtime/cost evidence is pending | Yes |
| GAP-020 — Product-vision real-run proof | P0 | Deterministic contracts exist; real visual production evidence is pending | The experiment closes it |
| GAP-021 — QA-blocked re-edit reaches a terminal verdict | P1 | App/task path exists; a current real terminal rerun is unconfirmed | Required before robust Review claim |
| GAP-022 — Review → Approve → Delivery → Discover → payment fulfillment | P1 | Components exist; full immutable/idempotent flow is unproven | Not for editing-only upload test; yes for product readiness |
| GAP-023 — Production deployment, database migration, and environment parity | P0 | Release workflow exists; exact live deployment/migration/build evidence is pending | Yes |
| GAP-024 — Durable feedback/evaluation/learning loop | P2 | Capture foundations exist; durable replay learning is incomplete | No for upload test |
| GAP-025 — API contract drift and legacy route retirement | P2 | Typed mirrors exist; automated drift detection and alias retirement remain open | No for upload test |

## 5. Entry gate for starting controlled uploads

The user may begin a controlled real upload only after all items below are evidenced:

- [ ] PR #196 is merged and the exact merge commit is recorded.
- [ ] Vercel Production is READY on that merge commit and the production domain resolves to it.
- [ ] `Upload Foundation Release` applies all upload migrations in dependency order and the schema-verification artifact contains no `false` result.
- [ ] The real R2 multipart probe succeeds: create, upload parts, repeat one part, complete with exact ETags, verify size/hash, delete, and prove absence.
- [ ] The Android preview APK containing `SportReelSourceReader` is built and published only after the database and R2 jobs pass.
- [ ] That exact APK is installed on the target Android phone. An OTA JavaScript update is not sufficient for a new native module.
- [ ] The production operator app can authenticate and reach the production upload endpoints.
- [ ] A small non-critical SD/USB video completes upload, R2 verification, local cleanup evidence, and durable batch readiness before irreplaceable footage is selected.

The first large upload is itself an evidence-producing test for GAP-013/GAP-014. It must not begin with irreplaceable footage until the small controlled smoke passes.

## 6. Detailed open gaps

### GAP-013 — Resumable multipart R2 upload

**Priority:** P0  
**Area:** mobile upload, Vercel web-api, Cloudflare R2, retry/abort/verification.

**Foundation implemented**

- [x] Tracked Supabase schema stores multipart protocol, upload ID, part size/count, exact part ETags, errors, and completion state.
- [x] Web API implements create, part URL, part record, status, complete, abort, and cleanup-confirmation endpoints.
- [x] Part URLs are limited to one raw key, upload ID, and part number and use short expiry.
- [x] Part size and count enforce R2's 5 MiB non-final minimum and 10,000-part maximum.
- [x] The client records exact returned ETags and ascending part numbers.
- [x] Successful parts are reconciled from durable server state and are not retransmitted after restart.
- [x] Completion verifies final R2 size before source status becomes `verified`.
- [x] Multipart final ETag is not treated as source MD5.
- [x] Deterministic checks cover order, ETags, size mismatch, retry, completion, cleanup, and idempotent start.
- [x] The release workflow contains a real R2 create/retry/complete/hash/delete probe and fails if cleanup fails.

**Still required for experiment entry/closure**

- [ ] The post-merge real R2 probe passes against the configured production-like bucket and its evidence artifact is retained.
- [ ] The exact installed React Native client can read the returned part `ETag`; configure R2 CORS to expose `ETag` only for any browser-based upload client.
- [ ] A real network interruption proves only missing/failed parts are resent.
- [ ] User cancellation calls abort or reconciles in-flight parts truthfully.
- [ ] A stale multipart cleanup process handles abandoned durable sessions in addition to R2's lifecycle.
- [ ] Evidence records R2 key, upload ID prefix, part ledger, retries, final size/hash, abort/cleanup result, release run, and device test.

### GAP-014 — Durable Android source access and restart recovery

**Priority:** P0  
**Area:** Expo SDK 52, Android SAF, SD/USB, process restart, memory, phone storage.

**Foundation implemented**

- [x] Compatibility decision is explicit: retain Expo SDK 52 and add a focused Expo local module rather than assuming newer `FileHandle` behavior.
- [x] The native module opens `content://` through `ContentResolver`, verifies seekability, reads from an explicit offset, and limits one read to 64 MiB.
- [x] Default upload parts are 16 MiB; the normal path has no Base64 or complete-file cache copy.
- [x] Descriptors/channels are closed through scoped `use` paths.
- [x] AsyncStorage restores upload identity, completed parts, ETags, and the next missing part.
- [x] Server state remains authoritative during reconciliation.
- [x] The official Expo SAF directory permission path persists the selected tree URI permission where the provider supports it.
- [x] Removed/unavailable/non-seekable sources fail truthfully without deleting completed remote parts.
- [x] App-owned temporary artifacts are deleted only after verification; absence and reclaimed bytes are checked, and the original source URI is preserved.
- [x] Expo autolinking, prebuild, TypeScript, and Android Kotlin compilation pass in deterministic checks.

**Still required for experiment entry/closure**

- [ ] The exact generated APK is installed on the target phone.
- [ ] A small SD/USB upload proves the selected provider grants usable persistent access.
- [ ] A representative 4K file proves phone storage does not grow by the complete source size.
- [ ] Network loss, force-close, restart, SD removal, reconnection, and completion are exercised on the installed build.
- [ ] Selecting a different file with the same name is rejected by stable size/source identity evidence.
- [ ] The physical selection retest proves unchecked external files are not uploaded.
- [ ] Memory and temporary-storage measurements are attached with device/build ID, URI class, restart log, part ledger, and final R2 size.

### GAP-015 — Durable batch/session/athlete manifest and verified-run gate

**Priority:** P0  
**Area:** upload model, Supabase, mobile session state, R2 keys, pipeline admission.

**Foundation implemented**

- [x] Every new upload has a durable `source_uploads` row with immutable storage key and server-only service-role writes.
- [x] RLS is enabled for upload, part, batch, and dedup audit tables.
- [x] `client_upload_id` prevents duplicate multipart source creation and duplicate batch membership after lost responses/concurrent retries.
- [x] `upload_batches` records intended, actual, verified, and cleanup-pending counts.
- [x] The app/server can recover a unique active/ready batch after restart instead of trusting only React state.
- [x] Pipeline start is rejected before run creation unless all intended sources are size-matched verified and cleanup-complete.
- [x] The exact input manifest is frozen before dispatch.
- [x] Dispatch carries authoritative batch and pipeline run IDs, and R2 processing remains scoped to `raw/<batch_id>/`.
- [x] Filename reuse cannot overwrite another source; generated R2 keys remain immutable.
- [x] Exact byte-identical verified sources are reconciled by SHA-256, first-successful verification time, and deterministic canonical selection.
- [x] Older exact duplicates remain pipeline-ineligible even if R2 deletion fails; the failure remains auditable.
- [x] Re-exported/recompressed/perceptually similar files are not auto-deleted by the exact-byte rule.
- [x] Gallery source size is client-declared when available; the weaker legacy fallback is explicitly labeled `r2_head_adopted`.

**Still required for experiment entry/closure**

- [ ] Live upload migrations and RPCs pass post-merge schema verification.
- [ ] A real exact-duplicate upload proves canonical retention, old-key removal, and a complete dedup audit row.
- [ ] A real two-to-three-file batch proves every intended source enters one run exactly once and an unrelated batch remains untouched.
- [ ] The business grouping contract adds optional explicit session, athlete/group, owner/operator, and purpose metadata rather than inferring identity from filenames.
- [ ] One file cannot accidentally belong to two active business sessions.
- [ ] Reset, re-edit, cleanup, and processing isolation are proven against unrelated batches.
- [ ] Evidence includes batch/source rows, size evidence, content hashes, canonical/superseded decision, R2 listing, dispatch payload, frozen input manifest, and isolation result.

### GAP-016 — Dispatch, workflow, run, and operator-status correlation

**Priority:** P0  
**Area:** Vercel endpoint, GitHub API/Actions, Supabase `pipeline_runs`, mobile status.

**Current state**

- Dispatch acceptance and `workflow_dispatched` state are implemented.
- A 204 proves GitHub accepted an event; it does not prove a workflow run reached terminal truth.

**Remaining closure bar**

- [ ] Vercel Production has the required repository/token variable names and minimum permissions.
- [ ] One controlled app action correlates app response → API → `pipeline_runs` → exact GitHub run ID/URL/attempt/commit → running/progress → terminal state → app status.
- [ ] Queueing is represented as queued, not processing.
- [ ] Forced dispatch failure and forced workflow failure surface durably and recoverably in the app.
- [ ] Stale live status falls back to durable history without rewriting it.
- [ ] Evidence contains production commit, row snapshots, Actions run, logs, and app screenshots.

### GAP-017 — Real perception/tracker quality and identity stability

**Priority:** P0  
**Area:** Ultralytics, BoT-SORT, sidecars, identity, crop authority.

**Current state**

- Production workflow requires perception and defaults to Ultralytics plus BoT-SORT.
- Synthetic schemas/fail-closed checks exist.
- Difficult real footage has not established acceptable fragmentation, identity continuity, or runtime cost.

**Remaining closure bar**

- [ ] Freeze a difficult representative surfing set: distance, spray, occlusion, same-wave surfers, camera motion, entry/exit, and similar athletes.
- [ ] Record detector/tracker model/config, thresholds, stride/input size, FPS, device, camera-motion compensation, and Re-ID setting.
- [ ] Measure raw/stiched tracks, duration distribution, lost/reacquired intervals, ID switches, false split/merge, runtime, memory, and failure rate.
- [ ] Prove one athlete is not silently split and two athletes are not merged.
- [ ] Crop authority uses measured tracker evidence, not an LLM hint alone.
- [ ] Negative real cases block unsafe identity rather than guessing.
- [ ] Evidence contains sidecars, overlays, metrics, tuning record, runtime, and final identity decisions.

### GAP-018 — Cross-source athlete grouping and duplicate control

**Priority:** P0  
**Area:** multiple clips per athlete, canonical identity, reel grouping, duplicate moments/drafts.

**Current state**

- Stable athlete IDs, candidate ledger, duplicate diagnostics, and final-manifest checks exist.
- Durable `cluster_id`/`reel_group_id` lineage and safe real grouping remain incomplete.

**Remaining closure bar**

- [ ] Write a durable run-scoped reel/group ID into draft metadata, candidate ledger, coverage report, and publishable manifest.
- [ ] Trace all source appearances contributing to one primary reel.
- [ ] Merge same-athlete clips only with strong measured evidence; never use filename/label as identity proof.
- [ ] Preserve distinct athletes with similar appearance and distinct actions by the same athlete.
- [ ] Represent the same physical action once across files.
- [ ] Distinguish intentional Parts from duplicate primary outputs.
- [ ] Positive and negative eval fixtures define expected grouping.
- [ ] Real same-athlete and multi-athlete batches prove one primary reel per eligible athlete without crossover.

### GAP-019 — 4K/30 visual-quality and performance budget

**Priority:** P0  
**Area:** FFmpeg rendering, 4K output, Actions runtime, R2 transfer.

**Current state**

- Synthetic FFmpeg checks cover vertical 2160×3840, 30 fps, H.264 High Profile, yuv420p, BT.709, silent output, and contain framing.
- Representative generation loss, emergency-crop quality, runtime/cost, output size, and transfer reliability are not measured.

**Remaining closure bar**

- [ ] Verify every final Part with `ffprobe`, including dimensions, frame rate, progressive profile, pixel/color metadata, fast-start, and no audio.
- [ ] Preserve source frame rate and default contain framing without hidden downscale.
- [ ] Record necessity and zoom cap for every tracked crop.
- [ ] Measure VMAF/SSIM or a justified equivalent for representative contain and emergency-crop cases, calibrated by visual review.
- [ ] Record per-stage time, total Actions minutes, CPU/memory, source/output sizes, transfer duration/retries, and cost.
- [ ] Prove workflow timeout headroom and real multipart reliability for large source/output files.
- [ ] Review final files at native resolution.

### GAP-020 — Product-vision real-run proof

**Priority:** P0  
**Area:** analyzer, identity, selection, editor, QA, manifest, app status, visual output.

**Remaining closure bar**

- [ ] Freeze comparison footage and expected athlete/action/wave inventory before execution.
- [ ] Use the exact production-deployed commit and record all run/batch/build/deployment identifiers.
- [ ] Every eligible athlete receives exactly one primary publishable reel or explicit evidence-backed hard rejection.
- [ ] Every complete usable surf wave appears exactly once or has an explicit hard-reject reason.
- [ ] No reel changes featured athlete, duplicates a physical action, loses a valuable detected moment silently, or cuts an action before its outcome.
- [ ] Every Part is independently understandable, silent, vertical, 4K/30, at most 90 seconds, and technically publishable.
- [ ] Final QA has real evidence and every FAIL blocks approval.
- [ ] Manifest, coverage, candidate/selection ledgers, source/draft/QA traces, media report, durable status, R2 objects, and UI agree.
- [ ] Every final video is visually inspected and all false positives/negatives, identity errors, crop errors, missed moments, and repairs are recorded.

### GAP-021 — QA-blocked re-edit reaches a terminal verdict

**Priority:** P1  
**Area:** QA task persistence, Review UI, R2 requeue, rerun, max attempts.

**Current state**

- QA-blocked tasks, approval blocking, operator notes, and R2 requeue foundations exist.
- A current real rerun has not proved a terminal PASS, another blocked iteration, or manual reject.

**Remaining closure bar**

- [ ] A final QA FAIL writes one durable blocked request with defects, reasons, source identities, attempt count, and max attempts.
- [ ] Review displays it, blocks approval, and preserves actionable operator notes.
- [ ] Sending notes promotes the same task atomically and creates one correlated pipeline run.
- [ ] Only the intended canonical source/batch is requeued and the next run consumes the request once.
- [ ] Re-edit applies a traceable repair, reruns QA, and reaches PASS, another blocked state, or explicit manual review/reject at max attempts.
- [ ] Workflow failure leaves recoverable truthful task state.
- [ ] Evidence contains keys, task rows, notes, repair trace, run, QA trace, final state, and UI screenshots.

### GAP-022 — Review → Approve → Delivery → Discover → payment fulfillment

**Priority:** P1  
**Area:** approval, immutable storage identity, delivery, Discover, Stripe.

**Remaining closure bar**

- [ ] Review authority is the exact canonical protected R2 key; missing/mismatched/QA-failed/non-publishable inputs block approval.
- [ ] Approval moves/copies the exact object and creates one durable correlated delivery run.
- [ ] Delivery creates the intended protected Discover/preview/payment state without exposing the full unpurchased reel.
- [ ] Checkout uses the correct reel/purchase identity.
- [ ] Webhook verifies the raw-body Stripe signature and fulfills only confirmed paid state.
- [ ] Fulfillment is idempotent under retries/concurrency and does not duplicate purchase, delivery, email, or sold-state transitions.
- [ ] Failed webhook/delivery remains observable/recoverable and access control prevents another user from receiving the reel.
- [ ] Stripe sandbox evidence covers checkout, webhook retries, purchase, fulfillment, protected access, and UI.

### GAP-023 — Production deployment, database migration, and environment parity

**Priority:** P0  
**Area:** Vercel Production, EAS, GitHub Actions, Supabase, configuration.

**Foundation implemented**

- [x] Upload release workflow enforces migration → schema verification → real R2 probe → Android build order.
- [x] Required upload tables use RLS and server-only service-role writes.
- [x] The workflow records schema/R2/APK artifacts without exposing secret values.

**Still required for experiment entry/closure**

- [ ] PR #196 merge commit is deployed to Vercel Production and the production domain aliases that exact deployment.
- [ ] Production API smoke tests run against the production domain.
- [ ] Required Vercel variable names and independent GitHub Actions secret/variable names exist and preflight passes.
- [ ] Every upload migration is applied in order and verified live.
- [ ] The exact Android build/upload ID and runtime/channel are recorded and installed.
- [ ] The previously planned biometric-removal migration and live no-biometric verification are completed.
- [ ] Registration, login, profile, Discover, checkout, support, and delivery work without removed biometric paths.
- [ ] Rollback steps are documented and dry-validated.

### GAP-024 — Durable feedback/evaluation/learning loop

**Priority:** P2  
**Area:** operator feedback, candidate ledger, replay evals, ranking, historical learning.

**Current state**

- Structured feedback controls, API storage, prompt injection, missed-moment report, and additive editorial scoring exist.
- Durable cross-run decision history and safe replay-driven learning remain incomplete.

**Remaining closure bar**

- [ ] Real operator feedback writes the expected row and the next run records exact normalized injected evidence.
- [ ] Feedback links to immutable draft/storage identity, run, athlete/group, and source time window.
- [ ] Candidate and selection decisions are durable/queryable across runs.
- [ ] Operator UI exposes source/track/duplicate/mixed-subject/selection evidence.
- [ ] A versioned real-run evaluation dataset and deterministic graders cover identity, coverage, duplicates, technical compliance, and status truth.
- [ ] Model graders are limited to editorial quality after deterministic gates.
- [ ] Ranking/policy changes pass offline replay with no athlete/action recall regression and have version/rollback fields.
- [ ] Monitoring records false positives/negatives, missed moments, QA bypass, duplicates, and operator corrections.

### GAP-025 — API contract drift and legacy route retirement

**Priority:** P2  
**Area:** web-api/mobile TypeScript contracts, compatibility aliases.

**Current state**

- Web API and mobile have typed mirrored contracts but no shared generated source of truth.
- `/api/operator/pipeline/run` remains a compatibility alias without complete retirement evidence.

**Remaining closure bar**

- [ ] Maintain one machine-checkable inventory of every operator route and mobile consumer.
- [ ] Success, partial, authentication, rate-limit, stale-client, and error schemas are explicit.
- [ ] Build/test detects mobile/server drift through a proportionate shared package, generated client/schema, or deterministic mirror comparison.
- [ ] Compatibility aliases have owner, callers, telemetry, and removal condition.
- [ ] Active mobile versions and no-call evidence justify retirement before alias removal.
- [ ] Negative tests cover unknown fields and unsupported old clients.

## 7. Required experiment artifact bundle

Every production-style experiment must retain one correlated bundle containing:

- repository commit, Vercel deployment, EAS build/upload, installed-app build identity, workflow run, pipeline run, and batch IDs;
- durable upload batch/source rows, source-size evidence, SHA-256, exact-duplicate audit, multipart part ledger, R2 keys, final size/hash, retry, abort, and cleanup evidence;
- frozen expected athlete/action/wave inventory;
- detector/tracker preflight, sidecars, overlays, and identity/fragmentation summary;
- candidate ledger, selection audit, cross-source group/duplicate lineage, framing decisions, source evidence, draft/repair/QA traces, coverage, and publishable manifest;
- ffprobe and visual-quality reports;
- per-stage runtime, resource, size, transfer, retry, and cost metrics;
- durable status, reprocess, delivery, Discover/payment rows when applicable;
- final videos and written visual review;
- observed defects and the next result-loop decision.

The experiment is invalid for closure claims if required artifacts are missing, stale, or cannot be tied to the same commit/run/batch.

## 8. Recommended work order after upload release

1. Complete GAP-023's post-merge release evidence and install the generated APK.
2. Execute the small controlled upload smoke, then the real GAP-013/GAP-014 interruption/restart/storage test.
3. Prove GAP-015 with exact duplicate and two-to-three-file batch/isolation evidence; add explicit session/athlete grouping metadata.
4. Prove GAP-016 with one correlated app → API → Actions → Supabase → app transition.
5. Measure/tune GAP-017, GAP-018, and GAP-019 on difficult representative footage.
6. Execute GAP-020's frozen production-style experiment and review every video/artifact.
7. Exercise GAP-021 to a real terminal QA verdict.
8. Prove GAP-022 end to end through Stripe sandbox and protected delivery.
9. Build GAP-024's durable replay/evaluation loop from reviewed runs.
10. Automate GAP-025 contract drift detection and retire legacy routes when client evidence permits.

## 9. Audit maintenance rule

Every PR that changes upload, storage, batch semantics, dispatch, status, perception, identity, selection, rendering, QA, Review, Delivery, Discover, payment, deployment, database schema, or feedback behavior must update this file in the same PR.

A gap can move to **closed** only when every mandatory item has direct evidence, final-head CI/review passed, relevant production deployment/migration is verified, required real-device/service/footage validation passed, and no contradictory audit remains open without explanation.

Do not delete closed history. Move it to a dated **Closed gaps** section with the closing PR, commit, evidence links, and remaining monitoring obligation.
