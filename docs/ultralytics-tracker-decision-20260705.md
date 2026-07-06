# Ultralytics tracker decision — 2026-07-05

This file records the official-doc basis for the next production perception step.

Decision:
- Use the existing `scripts/generate_perception_sidecar.py` entrypoint with `--backend ultralytics`.
- Default tracker: `botsort.yaml`.
- Reason: Ultralytics official tracking docs list BoT-SORT as the default tracker and recommend it for handheld, drone, or moving-camera footage because it adds camera-motion compensation.
- Required output evidence remains the existing SportReel sidecar contract: `bbox_xyxy`, `confidence`, class evidence, and `track_id`.

Status:
- Code path added by PR #125.
- Not real-run validated.
- Not a claim that Ultralytics is installed or configured in production.
