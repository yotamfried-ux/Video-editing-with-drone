#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing tokens: {missing}")


def fake_r2() -> types.SimpleNamespace:
    moves: list[tuple[str, str]] = []
    listed: list[str] = []

    def list_objects(prefix: str) -> list[dict]:
        listed.append(prefix)
        return [
            {"Key": f"{prefix}clip.mp4"},
            {"Key": f"{prefix}note.txt"},
        ]

    def move_object(source: str, dest: str) -> None:
        moves.append((source, dest))

    module = types.SimpleNamespace(
        RAW_PREFIX="raw/",
        PROCESSED_PREFIX="processed/",
        list_objects=list_objects,
        move_object=move_object,
        delete_object=lambda key: None,
        download_video=lambda key, filename: f"/tmp/{filename}",
        _is_video_key=lambda key: key.endswith(".mp4"),
        _object_to_video=lambda obj: {"key": obj["Key"], "id": obj["Key"], "name": obj["Key"].split("/")[-1]},
        _sportreel_r2_batch_scope_installed=False,
        moves=moves,
        listed=listed,
    )
    sys.modules["integrations.r2_storage"] = module
    return module


def run_scope_probe() -> None:
    os.environ["RAW_BATCH_ID"] = "session one"
    module = fake_r2()
    dedup_calls: list[list[str]] = []

    def prepare_canonical_sources(videos: list[dict], download_one, **kwargs) -> list[dict]:
        dedup_calls.append([video["id"] for video in videos])
        if kwargs.get("storage_backend") != "r2":
            raise SystemExit("batch scope must explicitly activate R2 exact dedup")
        if kwargs.get("delete_source") is not module.delete_object:
            raise SystemExit("batch scope must pass the active R2 delete implementation")
        return videos

    sys.modules["pipeline.source_upload_dedup"] = types.SimpleNamespace(
        prepare_canonical_sources=prepare_canonical_sources
    )

    import pipeline.r2_batch_scope as batch_scope

    batch_scope.install()
    videos = module.get_new_videos()
    if module.listed != ["raw/session_one/"]:
        raise SystemExit(f"expected scoped listing, got {module.listed}")
    if [video["key"] for video in videos] != ["raw/session_one/clip.mp4"]:
        raise SystemExit("expected only the scoped video object")
    if dedup_calls != [["raw/session_one/clip.mp4"]]:
        raise SystemExit(f"expected exact dedup admission gate, got {dedup_calls}")

    module.mark_as_processed("raw/session_one/clip.mp4")
    module.requeue_video("processed/session_one/clip.mp4")
    module.restore_processed_to_raw()
    expected = {
        ("raw/session_one/clip.mp4", "processed/session_one/clip.mp4"),
        ("processed/session_one/clip.mp4", "raw/session_one/clip.mp4"),
    }
    if not expected.issubset(set(module.moves)):
        raise SystemExit(f"expected scoped moves, got {module.moves}")


def main() -> int:
    upload_route = read("web-api/src/app/api/operator/upload/route.ts")
    start_route = read("web-api/src/app/api/operator/pipeline/start/route.ts")
    reset_route = read("web-api/src/app/api/operator/pipeline/reset/route.ts")
    r2_lib = read("web-api/src/lib/r2-storage.ts")
    workflow = read(".github/workflows/pipeline-run.yml")
    mobile = read("mobile/src/app/(operator)/pipeline.tsx")
    contracts = read("mobile/src/features/operator/types/contracts.ts")
    scope = read("pipeline/r2_batch_scope.py")
    bootstrap = read("pipeline/bootstrap.py")
    dedup = read("pipeline/source_upload_dedup.py")

    for text in [scope, bootstrap, dedup, read("scripts/test_batch_scope_contract.py")]:
        ast.parse(text)

    require("r2 upload key", r2_lib, ["safeBatchId", "newBatchId", "raw/${batchId}/${storageName}", "batch_id: batchId"])
    require("upload route", upload_route, ["files?: UploadFileInput[]", "normalizeUploadFiles", "uploadFilename", "safeBatchId(requestedBatchId) || newBatchId()", "createR2UploadUrl(file.uploadFilename, batchId)", "batch_id: upload.batch_id", "uploads,"])
    require("pipeline start route", start_route, ["batch_id?: string", "safeBatchId", "client_payload", "batch_id"])
    require("pipeline reset route", reset_route, ["batch_id", "safeBatchId", "inputs", "pipeline_run_id: run.id"])
    require("pipeline workflow", workflow, ["batch_id:", "RAW_BATCH_ID", "github.event.client_payload.batch_id || inputs.batch_id || ''"])
    require("mobile batch state", mobile, ["activeBatchId", "lastBatchId", "batch_id: activeBatchId", "batch_id: lastBatchId ?? activeBatchId", "Current upload batch"])
    require("operator contracts", contracts, ["batch_id?: string | null"])
    require("canonical batch bootstrap", bootstrap, ["RAW_BATCH_ID", "pipeline.r2_batch_scope", "_install_r2_batch_scope"])
    require("r2 batch scope runtime", scope, ["scoped_prefix", "move_between_prefixes", "prepare_canonical_sources", "get_new_videos", "mark_as_processed", "restore_processed_to_raw"])

    if "const key = `raw/${storageName}`" in r2_lib:
        raise SystemExit("r2 storage key must include batch id")
    if "createR2UploadUrl(filename, requestedBatchId)" in upload_route:
        raise SystemExit("upload route must use normalized batch files")
    if "createR2UploadUrl(file.filename, batchId)" in upload_route:
        raise SystemExit("upload route must use unique per-file upload names")

    run_scope_probe()

    from scripts.test_exact_source_upload_dedup_contract import main as exact_dedup_main

    exact_dedup_main()
    print("Batch scope contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
