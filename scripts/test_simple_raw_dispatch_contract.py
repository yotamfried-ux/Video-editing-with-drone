from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
route = (ROOT / "web-api/src/app/api/operator/pipeline/start-raw/route.ts").read_text()
mobile = (ROOT / "mobile/src/app/(operator)/pipeline.tsx").read_text()
workflow = (ROOT / ".github/workflows/pipeline-run.yml").read_text()

assert "requireOperator(req)" in route
assert "enforceRateLimit(req" in route
assert "pipeline-run.yml/dispatches" in route
assert "batch_id: ''" in route and "pipeline_run_id: ''" in route
assert "start-raw" in mobile[mobile.index("  const runPipeline = async"):mobile.index("  const confirmReset = () => {")]
assert "batch_id: dispatchBatchId" not in mobile[mobile.index("  const runPipeline = async"):mobile.index("  const confirmReset = () => {")]
assert "frozen-input preflight skipped: untracked legacy run without a batch id" in (ROOT / "scripts/preflight_frozen_inputs.py").read_text()
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

print("simple RAW dispatch contract OK")
