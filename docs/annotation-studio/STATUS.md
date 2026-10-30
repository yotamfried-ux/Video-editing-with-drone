# Annotation Studio — milestone status (evidence-based)

Branch: `ccr-5ce1d535-e7mo2b`. Nothing here touches production storage, credentials, Supabase, the pipeline, or deployments.

PASS/PARTIAL/NOT DONE are stated per item. "PASS" means executed with the evidence listed.

## M0 — Investigation: PASS
[`M0-gap-analysis.md`](M0-gap-analysis.md). Key findings: `source_uploads` is path-keyed and *deletes* the older duplicate (unusable as identity);
cleanup service deletes everything under `raw/ processed/ review/ approved/ pending_payment/ pending_uploads/ previews/`;
**pipeline emits no per-frame EDL** (only event-level framing mode + rendered offsets).

## M1 — Local interactive prototype: PASS (see screenshots/)
Precision Studio workbench (video, frame-exact stepping, zoomable multitrack timeline with overlapping events, bbox draw/move/resize,
inspector, shortcuts, speeds 0.25–2x, save-state pill, revision list, approval) + Library, Athletes, Datasets, Evaluations, Editing Review.
Evidence: `npm run test:e2e` -> Playwright scenarios (list below), screenshots in `docs/annotation-studio/screenshots/`.

## M2 — Durable catalog: PASS (local archive adapter) / NOT DONE (real R2 + Supabase)
13 tests in `tests/catalog.test.mjs`: identity by sha256+size, duplicate bytes -> one source + occurrences, same name/different bytes -> distinct,
generated prefixes refused, raw->processed move and full operational wipe keep identity and playable archive, 50-file batch w/ 10 duplicates,
truncated upload fails visibly then recovers, lost event discovered by reconcile, archive outage -> `archive_error` then repaired, hash-mismatch
copy never published, corruption detected by audit, DB triggers block identity rewrites and deletes.

## M3 — Annotation system: PASS
7 tests (`annotations.test.mjs`) + E2E: optimistic concurrency, validation (INVALID_INTERVAL/INVALID_BBOX), immutable chained revisions,
unresolved-item acknowledgement, overlapping events/multiple surfers, restart persistence, approval blocked without verified archive.
E2E: offline -> pending queue -> recovery, version conflict UI, reload keeps exact frames.

## M4 — Evaluation: PASS (engine) / PARTIAL (no real pipeline predictions imported)
`evaluation.test.mjs`: freeze immutability, group-consistent deterministic splits, permanent held-out test, matcher (hit/miss/duplicate/wrong athlete/
FP/excluded/unreviewed), repeat-run identical digest, blind manifest has no label fields, training export only from frozen approved revisions.
**Limitation:** the pipeline does not yet produce a prediction file in the `PredictionImport` shape; an adapter from `diagnostics` artifacts is future work.
Pipeline athlete keys are mapped to GT athletes by deterministic co-occurrence (documented assumption).

## M5 — Editing quality: PASS (math/metrics on synthetic EDL) / BLOCKED (real pipeline EDL)
`edl.test.mjs` (13): analytic contain/crop/rotation/pad transforms, centering error vs lead-room, contain not penalised, clipped frames with exact
output+source frame, crop jump, identity swap, missing/visual-match EDL -> `NOT_EVALUABLE`, unreviewed denominator, proposal-only crop.
**Blocked:** real pipeline runs have no EDL; emitting one changes the production pipeline and needs operator approval.
Heuristic "wave context" scoring is intentionally NOT implemented (spec: do not present unvalidated heuristics as truth).

## Known gaps / decisions needing the operator
1. Real protected R2 bucket + separate Supabase project (cost + credentials) — not created.
2. Pipeline EDL emission + prediction export — pipeline change, not made.
3. CV tracking proposals: only linear interpolation between manual keyframes (visually distinct, never auto-approved). Real detector/tracker proposals not wired.
4. Variable-frame-rate sources: frames are indexed by nominal constant fps; VFR PTS table not implemented (flagged, not silently handled).
5. Rotated sources: rotation recorded; overlay assumes proxy is already displayed upright (ffmpeg autorotate). Verified only with 0°.
6. Multi-annotator sets, athlete merge, and cross-video identity linking beyond explicit per-source confirmation are out of scope.
7. `node:sqlite` is experimental in Node 22.
