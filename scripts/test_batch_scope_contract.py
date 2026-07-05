#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing tokens: {missing}")


def forbid(label: str, text: str, tokens: list[str]) -> None:
    found = [token for token in tokens if token in text]
    if found:
        raise SystemExit(f"{label} contains forbidden tokens: {found}")


def main() -> int:
    upload_route = read("web-api/src/app/api/operator/upload/route.ts")
    start_route = read("web-api/src/app/api/operator/pipeline/start/route.ts")
    reset_route = read("web-api/src/app/api/operator/pipeline/reset/route.ts")
    r2_lib = read("web-api/src/lib/r2-storage.ts")
    workflow = read(".github/workflows/pipeline-run.yml")
    mobile = read("mobile/src/app/(operator)/pipeline.tsx")
    contracts = read("mobile/src/features/operator/types/contracts.ts")
    scope = read("pipeline/r2_batch_scope.py")
    sitecustomize = read("sitecustomize.py")

    for text in [scope, sitecustomize, read("scripts/test_batch_scope_contract.py")]:
        ast.parse(text)

    require("r2 upload key", r2_lib, ["safeBatchId", "newBatchId", "raw/${batchId}/${storageName}", "batch_id: batchId"])
    require("upload route", upload_route, ["files?: UploadFileInput[]", "normalizeUploadFiles", "safeBatchId(requestedBatchId) || newBatchId()", "createR2UploadUrl(file.filename, batchId)", "batch_id: upload.batch_id", "uploads,"])
    require("pipeline start route", start_route, ["batch_id?: string", "safeBatchId", "client_payload", "batch_id"])
    require("pipeline reset route", reset_route, ["batch_id", "safeBatchId", "inputs", "pipeline_run_id: run.id"])
    require("pipeline workflow", workflow, ["batch_id:", "RAW_BATCH_ID", "github.event.client_payload.batch_id || inputs.batch_id || ''"])
    require("mobile batch state", mobile, ["activeBatchId", "lastBatchId", "batch_id: activeBatchId", "batch_id: lastBatchId ?? activeBatchId", "Current upload batch"])
    require("operator contracts", contracts, ["batch_id?: string | null"])
    require("python startup hook", sitecustomize, ["RAW_BATCH_ID", "pipeline.r2_batch_scope", "_install_r2_batch_scope"])
    require("r2 batch scope runtime", scope, ["scoped_prefix", "move_between_prefixes", "get_new_videos", "mark_as_processed", "restore_processed_to_raw"])
    forbid("r2 upload key legacy raw root", r2_lib, ["const key = `raw/${storageName}`"])
    forbid("upload route legacy single file R2 call", upload_route, ["createR2UploadUrl(filename, requestedBatchId)"])

    print("Batch scope contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
