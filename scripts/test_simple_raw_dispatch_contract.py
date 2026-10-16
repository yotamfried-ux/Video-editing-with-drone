from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
route = (ROOT / "web-api/src/app/api/operator/pipeline/start-raw/route.ts").read_text()
mobile = (ROOT / "mobile/src/app/(operator)/pipeline.tsx").read_text()
workflow = (ROOT / ".github/workflows/pipeline-run.yml").read_text()

assert "requireOperator(req)" in route
assert "enforceRateLimit(req" in route
assert "pipeline-run.yml/dispatches" in route
assert "batch_id: ''" in route and "pipeline_run_id: run.id" in route
assert ".from('pipeline_runs').insert(" in route
assert "status: 'queued'" in route and "stage: 'dispatching'" in route
assert "status: 'dispatch_failed'" in route
assert "pipeline_run_id: run.id" in route
assert "start-raw" in mobile[mobile.index("  const runPipeline = async"):mobile.index("  const confirmReset = () => {")]
assert "batch_id: dispatchBatchId" not in mobile[mobile.index("  const runPipeline = async"):mobile.index("  const confirmReset = () => {")]
assert "frozen-input preflight skipped: batchless RAW run (tracked or legacy)" in (ROOT / "scripts/preflight_frozen_inputs.py").read_text()
assert 'if args.phase == "predispatch":' in (ROOT / "scripts/preflight_frozen_inputs.py").read_text()
assert "&& (github.event.client_payload.batch_id || inputs.batch_id || '') != ''" in workflow
assert "raw/" in (ROOT / "integrations/r2_storage.py").read_text()

# Progress visibility and run isolation contract for batchless dispatch.
status_hook = (ROOT / "mobile/src/features/operator/hooks/usePipelineStatus.ts").read_text()
status_route = (ROOT / "web-api/src/app/api/operator/pipeline/status/route.ts").read_text()
assert "setInterval(fetchStatus, 5000)" in status_hook
assert "setStatus(result.status)" in status_hook
assert "setLatestRun(result.latest_run ?? null)" in status_hook
assert "global_live_stale" in status_route
assert "global_live_stale_reason" in status_route
assert "group: pipeline-run" in workflow
assert "cancel-in-progress: false" in workflow
assert "github.event.client_payload.pipeline_run_id || inputs.pipeline_run_id || ''" in workflow
assert "Finalize operator pipeline row if the workflow failed or was cancelled" in workflow
assert "Finalize upload batch lifecycle" in workflow
assert "if: always()" in workflow

# Single-flight guard, configurable ref, and no_reviewable_drafts consistency.
assert "stage: 'run_already_active'" in route and "status: 409" in route
assert ".in('status', ['queued', 'running'])" in route and ".neq('id', run.id)" in route
assert "process.env.GITHUB_DISPATCH_REF || 'main'" in route
for path in (
    "web-api/src/app/api/operator/pipeline/status/route.ts",
    "mobile/src/app/(operator)/pipeline.tsx",
    "mobile/src/features/operator/components/PipelineRunsCard.tsx",
    "mobile/src/features/operator/types/contracts.ts",
):
    assert "no_reviewable_drafts" in (ROOT / path).read_text(), path

print("simple RAW dispatch contract OK")
