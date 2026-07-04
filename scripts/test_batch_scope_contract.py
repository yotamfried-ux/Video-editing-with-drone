#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} is missing contract tokens: {missing}")


def require_no_tokens(label: str, text: str, tokens: list[str]) -> None:
    present = [token for token in tokens if token in text]
    if present:
        raise SystemExit(f"{label} contains forbidden tokens: {present}")


def install_fake_r2() -> types.SimpleNamespace:
    moves: list[tuple[str, str]] = []
    listed: list[str] = []

    def list_objects(prefix: str) -> list[dict]:
        listed.append(prefix)
        return [
            {"Key": f"{prefix}a.mp4"},
            {"Key": "raw/other/b.mp4"},
            {"Key": f"{prefix}notes.txt"},
        ]

    def move_object(source: str, dest: str) -> None:
        moves.append((source, dest))

    fake = types.SimpleNamespace(
        RAW_PREFIX="raw/",
        PROCESSED_PREFIX="processed/",
        list_objects=list_objects,
        move_object=move_object,
        _is_video_key=lambda key: key.endswith(".mp4"),
        _object_to_video=lambda obj: {"key": obj["Key"], "id": obj["Key"], "name": obj["Key"].split("/")[-1]},
        _sportreel_r2_batch_scope_installed=False,
        moves=moves,
        listed=listed,
    )
    sys.modules["integrations.r2_storage"] = fake
    return fake


def main() -> int:
    upload_route = _read("web-api/src/app/api/operator/upload/route.ts")
    start_route = _read("web-api/src/app/api/operator/pipeline/start/route.ts")
    reset_route = _read("web-api/src/app/api/operator/pipeline/reset/route.ts")
    r2_lib = _read("web-api/src/lib/r2-storage.ts")
    workflow = _read(".github/workflows/pipeline-run.yml")
    mobile = _read("mobile/src/app/(operator)/pipeline.tsx")
    contracts = _read("mobile/src/features/operator/types/contracts.ts")
    scope = _read("pipeline/r2_batch_scope.py")
    sitecustomize = _read("sitecustomize.py")

    for label, text in {
        "batch scope": scope,
        "sitecustomize": sitecustomize,
        "batch scope contract": _read("scripts/test_batch_scope_contract.py"),
    }.items():
        ast.parse(text)

    require_tokens("r2 upload key", r2_lib, ["safeBatchId", "newBatchId", "raw/${batchId}/${storageName}", "batch_id: batchId"])
    require_tokens("upload route", upload_route, ["batch_id?: string", "requestedBatchId", "createR2UploadUrl(filename, requestedBatchId)", "batch_id: upload.batch_id"])
    require_tokens("pipeline start route", start_route, ["batch_id?: string", "safeBatchId", "client_payload", "batch_id"])
    require_tokens("pipeline reset route", reset_route, ["batch_id", "safeBatchId", "inputs", "pipeline_run_id: run.id"])
    require_tokens("pipeline workflow", workflow, ["batch_id:", "RAW_BATCH_ID", "github.event.client_payload.batch_id || inputs.batch_id || ''"])
    require_tokens("mobile batch state", mobile, ["activeBatchId", "lastBatchId", "batch_id: activeBatchId", "batch_id: lastBatchId ?? activeBatchId", "Current upload batch"])
    require_tokens("operator contracts", contracts, ["batch_id?: string | null"])
    require_tokens("python startup hook", sitecustomize, ["RAW_BATCH_ID", "pipeline.r2_batch_scope", "_install_r2_batch_scope"])
    require_tokens("r2 batch scope runtime", scope, ["scoped_prefix", "move_between_prefixes", "get_new_videos", "mark_as_processed", "restore_processed_to_raw"])
    require_no_tokens("r2 upload key legacy raw root", r2_lib, ["const key = `raw/${storageName}`"])

    os.environ["RAW_BATCH_ID"] = "session/unsafe id"
    import pipeline.r2_batch_scope as batch_scope
    fake = install_fake_r2()
    batch_scope.install()
    videos = fake.get_new_videos()
    if fake.listed != ["raw/session_unsafe_id/"]:
        raise SystemExit(f"expected scoped raw listing, got {fake.listed}")
    if [v["key"] for v in videos] != ["raw/session_unsafe_id/a.mp4", "raw/other/b.mp4"]:
        raise SystemExit("fake list should expose only video keys returned from scoped listing")
    fake.mark_as_processed("raw/session_unsafe_id/a.mp4")
    fake.requeue_video("processed/session_unsafe_id/a.mp4")
    fake.restore_processed_to_raw()
    if ("raw/session_unsafe_id/a.mp4", "processed/session_unsafe_id/a.mp4") not in fake.moves:
        raise SystemExit("mark_as_processed must preserve batch path")
    if ("processed/session_unsafe_id/a.mp4", "raw/session_unsafe_id/a.mp4") not in fake.moves:
        raise SystemExit("requeue_video must preserve batch path")

    print("Batch scope contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
