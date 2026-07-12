# Run 29194242123 repair plan

This branch repairs four production findings from workflow run `29194242123`:

1. Recover `MM.SS` timestamps only when decimal seconds are unusable and the minute-second interpretation is valid inside the real chunk.
2. Make FFprobe duration caching sensitive to file rewrites so QA iterations cannot reuse stale clip durations.
3. Preserve the original selector window across every QA re-edit iteration while recording previous and final windows separately.
4. Reconcile mixed-subject telemetry with final-cut windows, frame-level concurrency, and the explicit primary-actor gate.

Merge requires all existing workflows, focused regression contracts, and review threads to pass on the final head. A new production run is required after merge to validate footage-level improvement.