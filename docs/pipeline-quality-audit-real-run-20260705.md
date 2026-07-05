# Pipeline quality audit addendum — real run 2026-07-05

Status: addendum to `docs/pipeline-quality-audit.md`.

Run inspected:

- GitHub Actions run: `28728468624`
- Job: `85189984969`
- Result: success
- Checked out commit: `ec89e99f41fefb379a2e0de6300afebb9fa9f419`
- Artifacts in GitHub Actions: none

## Why this addendum exists

A real operator review of the run produced multiple normal review drafts with quality failures:

1. Mixed athletes in `DRAFT_surfer in a dark long-sleeved one-piece swimsuit...`.
2. Early wave cut and repeated segment in `DRAFT_surfer in black swim trunks on a pink longboard...`.
3. Mixed athletes in `DRAFT_surfer in dark shorts on a light green longboard...`.

This means the PQ-001..PQ-010 infrastructure improved traceability and guardrails, but the product still does not have a track-backed identity invariant.

## Official references

Use these references before implementing any repair loop for the gaps below:

- Google Cloud Video Intelligence object tracking: object tracking provides labels for individual object instances with bounding boxes and time offsets; label detection alone does not provide bounding boxes. Multiple instances of the same object type are represented as separate `ObjectTrackingAnnotation` instances, each keeping its own object track.
  - `https://cloud.google.com/video-intelligence/docs/object-tracking`
- MediaPipe Object Detector Python guide: video mode processes frame/timestamp pairs through `detect_for_video`, so video perception should be frame/time based rather than one global natural-language description.
  - `https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector/python`
- Roboflow Supervision detections core: detection structures expose bbox/confidence/class/tracker metadata suitable for local normalized track schemas.
  - `https://supervision.roboflow.com/latest/detection/core/`
- NVIDIA DeepStream Python sample apps: sample pipelines show detector/tracker/analytics metadata flowing through the pipeline instead of being inferred only after render.
  - `https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_Python_Sample_Apps.html`

## REAL-ID-001 — Mixed athletes still reach normal review drafts

Severity: critical.

Area:

- `pipeline/stages/identity.py`
- `pipeline/identity_failsafe.py`
- `pipeline/stages/editor.py`
- `pipeline/qa_gate_policy.py`
- `pipeline/draft_diagnostics.py`

Problem:

- The latest real run generated multiple normal review drafts that visibly mix different surfers/athletes.
- The job succeeded and the drafts were presented with normal `Approve` actions.
- GitHub Actions had no downloadable artifact for the run, so the operator cannot reconstruct identity decisions directly from the Actions page.

Root cause hypothesis to verify in code before changing behavior:

- Identity is still description/focused-thumbnail based rather than track-backed.
- The existing fail-safe can split uncertain clusters in some synthetic cases, but it still allows normal drafts when track evidence is missing rather than requiring proof.
- QA only sees the rendered reel after the identity decision; if the model does not detect the mismatch, the draft remains normal.

Target invariant:

```text
No stable track/evidence for a single athlete across all events => no normal review draft.
```

Required behavior:

1. A multi-event/person draft must include stable identity evidence: `track_id`, verified bbox/thumbnail continuity, or a trusted same-athlete cluster reason.
2. If identity evidence is missing for a multi-event draft, mark it `identity_uncertain` / `manual_review` and block normal approval.
3. If conflicting identity evidence exists, set QA defect `IDENTITY_MISMATCH` as blocking.
4. Diagnostic artifact must explain the identity evidence used for every draft.
5. Re-edit should receive an explicit reason: `mixed_athletes` or `identity_uncertain`.

Repair loop:

1. Inspect `pipeline/stages/identity.py`, `pipeline/identity_failsafe.py`, `pipeline/stages/editor.py`, `pipeline/qa_gate_policy.py`, and `pipeline/draft_diagnostics.py`.
2. Add a track-backed identity policy module that evaluates the final event list before normal draft upload.
3. Fail closed for multi-event drafts without stable identity evidence.
4. Attach `qa_gate` diagnostics with `IDENTITY_MISMATCH` or `IDENTITY_UNCERTAIN` before upload metadata is saved.
5. Add `scripts/test_real_identity_gate_contract.py` proving:
   - mixed track ids cannot produce a normal draft;
   - missing track evidence on multi-event drafts is manual-review/blocked;
   - single-event draft can still pass when no cross-event identity decision is needed;
   - diagnostics preserve event id, source, track id, and decision.
6. Wire the test into focused CI.
7. Run a real pipeline and inspect drafts before declaring this solved.

## REAL-CUT-001 — Wave still can be cut before outcome

Severity: high.

Problem:

- A real draft showed a wave that felt cut too early.
- PQ-007 protects outcome only when `outcome_end` / `peak_time` / action-window metadata exists.

Target invariant:

- If action-window metadata is absent, the system must not silently trust the Gemini end timestamp for a normal draft when the sport is surf and the event is near a cap/trim boundary.

Follow-up after REAL-ID-001:

- Require action-window evidence for surf drafts, or flag `window_uncertain` for manual review.
- Add post-render QA check that maps early-cut defects back into `qa_gate` diagnostics.

## REAL-DUP-001 — Repeated segment still appears twice

Severity: high.

Problem:

- A real draft repeated one segment twice.
- Existing dedup does not catch every duplicate generated after selection/order/render.

Target invariant:

- The same physical segment must not appear twice in the same normal review draft, even if the duplication is introduced after event selection.

Follow-up after REAL-ID-001:

- Add final ordered-event duplicate guard using event id, source, time window overlap, fingerprint when available, and output segment timing.
- Add QA defect `DUPLICATE_MOMENT` with blocking status.

## Repair priority

1. REAL-ID-001 — Track-backed identity gate. This is first because mixed identity can also cause wrong cuts and duplicate-looking narrative structure.
2. REAL-DUP-001 — Final duplicate segment guard.
3. REAL-CUT-001 — Stronger action-window evidence / early-cut guard for surf.
