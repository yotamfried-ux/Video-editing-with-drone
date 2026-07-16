# Runtime bootstrap wiring gap — 2026-07-15

Status: addendum to `docs/app-pipeline-audit.md` and `docs/pipeline-quality-audit.md` (PQ-004).

## What this addendum is

A cross-check of every quality/safety patch module against the actual entrypoints that
run them (not just the docs claiming a gap is "closed") found that several patches were
either double-wired with no single source of truth, or — in one case — never actually
active in the real GitHub Actions production run despite being fully implemented and
tested in isolation.

## Finding — PQ-004 (R2 batch/session isolation) was not active in production

`pipeline/r2_batch_scope.py` and its conditional install (`STORAGE_BACKEND=r2` and a
batch id set) existed and had a passing contract test (`scripts/test_batch_scope_contract.py`),
but that install was only ever called from the root `sitecustomize.py`. Python's
automatic `sitecustomize` import resolves against `sys.path` at interpreter startup,
and for `python scripts/run_tracked.py` (the actual GitHub Actions "Run pipeline" step,
via `scripts/run_pipeline_with_diagnostics.sh`), the script's own directory
(`scripts/`) lands on `sys.path`, not the repository root — so root `sitecustomize.py`
never loaded, and `pipeline.r2_batch_scope.install()` never ran in the real production
pipeline. Separately, `scripts/test_batch_scope_contract.py` — which does correctly
exercise `pipeline/r2_batch_scope.py`'s internal logic — was never wired into any CI
workflow, so this had zero live verification in either direction.

## Finding — the documented local/manual entrypoints bypassed nearly the entire patch stack

`run.py` (the command `scripts/upload_test_video.py` prints as "now run: python run.py")
and `run_surf.py` called `pipeline.orchestrator.main()` with no quality/safety patches
installed beyond whatever root `sitecustomize.py` narrowly applies (surf editor policy
gated to `sys.argv[0] == "run.py"`, and `r2_batch_scope` per the same gap above).
`scripts/reset_and_rerun.py`'s inline pipeline mode (`_run_pipeline_inline`, reachable
when invoked without `--reset-only`) was missing the same set. None of PQ-001 through
PQ-010's runtime patches — perception, identity fail-safe, cross-source dedup, QA gate
policy, diagnostics, candidate ledger, athlete canonicalization, primary-actor
continuity, surf ride segmentation — were active on these paths.

## Fix

- Added `pipeline/bootstrap.py`: a single ordered `install_pre_orchestrator_patches()` /
  `install_post_orchestrator_patches()` pair, reproducing the exact composite order
  already proven in the real production path (`scripts/sitecustomize.py` +
  `scripts/usercustomize.py`, auto-imported before `scripts/run_tracked.py`'s own body
  runs), plus the previously-missing `r2_batch_scope` conditional install.
- `run.py`, `run_surf.py`, and `scripts/reset_and_rerun.py`'s inline mode now call
  `pipeline.bootstrap` before/after importing `pipeline.orchestrator`, so a local or
  manual run gets the same protections as the GitHub Actions production run.
- `scripts/run_tracked.py` itself was left with its existing hand-rolled `_install_*`
  list intact (11 pre-existing contract tests pin its literal source/order), but gained
  one new function, `_install_r2_batch_scope()`, called right after
  `_install_storage_backend_alias()` — this is the actual production fix for the
  PQ-004 gap above.
- Wired `scripts/test_batch_scope_contract.py` (pre-existing, previously never run in
  CI) and the new `scripts/test_bootstrap_parity_contract.py` into Operator Smoke Check.

## Regression coverage

`scripts/test_bootstrap_parity_contract.py`:
- proves `scripts/run_tracked.py` defines and calls `_install_r2_batch_scope()`;
- proves `run.py` / `run_surf.py` / `scripts/reset_and_rerun.py` call
  `pipeline.bootstrap.install_pre_orchestrator_patches()` /
  `install_post_orchestrator_patches()`;
- exercises `pipeline.bootstrap._install_r2_batch_scope()` directly against a faked
  `integrations.r2_storage` module, proving it scopes listing to the batch id when set
  and does not install when no batch id is present.

## Still open

This addendum only fixes wiring/activation. It does not change PQ-007, PQ-008, or the
self-detection-metrics gaps (`BUG_DUPLICATE_ATHLETE_LIKELY`, `BUG_QA_GATE_BYPASSED`)
tracked elsewhere. A real GitHub Actions run with `RAW_BATCH_ID` set on the R2 backend
is still needed to confirm `r2_batch_scope` behaves correctly against real Drive/R2
state end-to-end, per this repo's standing rule that static contracts prove code paths,
not real footage outcomes.
