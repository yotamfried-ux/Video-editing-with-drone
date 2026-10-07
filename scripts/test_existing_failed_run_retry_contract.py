#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")

def main() -> int:
    route = read("web-api/src/app/api/operator/pipeline/retry/route.ts")
    mobile = read("mobile/src/app/(operator)/pipeline.tsx")
    preflight = read("scripts/preflight_frozen_inputs.py")

    required_route = [
        "run.status !== 'failed'",
        "batch.state !== 'failed'",
        "String(batch.pipeline_run_id ?? '') !== pipelineRunId",
        "JSON.stringify(runManifest) !== JSON.stringify(batchManifest)",
        "Number(batch.expected_file_count) !== runManifest.length",
        "reset: 'false'",
        "full_clean: 'false'",
        "pipeline_run_id: pipelineRunId",
        "batch_id: batchId",
    ]
    for token in required_route:
        assert token in route, f"missing fail-closed retry contract: {token}"

    assert "'/api/operator/pipeline/retry'" in mobile
    assert "latestRun?.status === 'failed'" in mobile
    assert "pipeline_run_id: latestRun.id" in mobile
    assert 'row["state"] not in {"running", "failed"}' in preflight
    print("existing failed-run retry contract: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
