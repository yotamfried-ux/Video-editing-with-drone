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
print("simple RAW dispatch contract OK")
