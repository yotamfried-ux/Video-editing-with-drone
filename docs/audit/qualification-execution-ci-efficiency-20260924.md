# Qualification execution and CI efficiency repair — 2026-09-24

This change responds to the second blind Claude qualification experiment.

## Repairs under qualification

- Engineering-OS routing decisions must be emitted as structured execution trace records.
- Broad work with independent bounded workstreams must use qualified delegation unless an explicit allowed blocker applies.
- CI continuation prefers same-session PR/check-suite completion subscriptions and avoids timer/polling fallbacks while a subscription is live.
- Large Upload Foundation stores a success marker keyed by the tracked mobile tree plus the workflow recipe so a later docs-only push can reuse a previously successful Android native compile.

## Native compile experiment

Baseline run: GitHub Actions run `35974558296` on PR #223.
It completed successfully and created the first success marker for the current mobile tree.

This documentation-only commit intentionally leaves the mobile tree unchanged.
The follow-up run must restore the marker and skip Node/Java setup, Expo prebuild,
and `:app:compileDebugKotlin`. That follow-up is the live regression proof for
the CI optimization.
