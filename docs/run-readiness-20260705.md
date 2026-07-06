# Run readiness — 2026-07-05

PR #125 added the Ultralytics tracker backend wiring.

PR #127 added the dedicated Ultralytics tracker contract and wired it into Operator Smoke.

This is not real-run validation. Before a real run, configure `SPORTREEL_PERCEPTION_COMMAND` with `--backend ultralytics` and a model path. Use `SPORTREEL_REQUIRE_PERCEPTION=1` when perception evidence is required.
