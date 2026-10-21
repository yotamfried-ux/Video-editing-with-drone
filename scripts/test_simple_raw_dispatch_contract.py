from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Dispatch logic is shared by start-raw and reset-raw; assert on the route plus the shared service.
route = (ROOT / "web-api/src/app/api/operator/pipeline/start-raw/route.ts").read_text()
reset_route = (ROOT / "web-api/src/app/api/operator/pipeline/reset-raw/route.ts").read_text()
service = (ROOT / "web-api/src/lib/pipeline-dispatch-core.ts").read_text()
glue = (ROOT / "web-api/src/lib/pipeline-dispatch.ts").read_text()
route_all = route + service + glue
mobile = (ROOT / "mobile/src/app/(operator)/pipeline.tsx").read_text()
workflow = (ROOT / ".github/workflows/pipeline-run.yml").read_text()

assert "requireOperator(req)" in route
assert "enforceRateLimit(req" in route
assert "pipeline-run.yml/dispatches" in route_all
assert "batch_id: ''" in route_all and "pipeline_run_id: runId" in route_all
assert ".from('pipeline_runs').insert(" in route_all
assert "status: 'queued'" in route_all and "stage: 'dispatching'" in route_all
assert "status: 'dispatch_failed'" in route_all
assert "pipeline_run_id: run.id" in route_all
assert "dispatchOperatorPipelineRun('process')" in route and "dispatchOperatorPipelineRun('reset_and_rerun'" in reset_route
assert "requireOperator(req)" in reset_route and "enforceRateLimit(req" in reset_route
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
assert "'run_already_active'" in service and "status: 409" in service
assert ".in('status', ['queued', 'running'])" in glue and ".neq('id', excludeId)" in glue
assert "process.env.GITHUB_DISPATCH_REF || 'main'" in glue

# Reset and rerun must be tracked exactly like Run pipeline (run 38914592559 was untracked).
for source in (route, reset_route):
    assert "pipeline_run_id: ''" not in source and "fetch(" not in source, "routes must not dispatch directly"
assert "reset_requested" in service and "full_clean_requested" in service
assert "onRunDispatched(" in mobile and "setRunsRefreshKey" in mobile
reset_fn = mobile[mobile.index("  const resetAndRerun = async"):mobile.index("  const resetAndRerun = async") + 1400]
assert "PipelineResetResponse" in reset_fn and "result.pipeline_run_id" in reset_fn
assert "Follow progress in GitHub Actions" not in mobile
for path in (
    "web-api/src/app/api/operator/pipeline/status/route.ts",
    "mobile/src/app/(operator)/pipeline.tsx",
    "mobile/src/features/operator/components/PipelineRunsCard.tsx",
    "mobile/src/features/operator/types/contracts.ts",
):
    assert "no_reviewable_drafts" in (ROOT / path).read_text(), path

print("simple RAW dispatch contract OK")
