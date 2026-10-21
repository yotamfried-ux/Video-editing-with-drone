#!/usr/bin/env python3
from __future__ import annotations

import ast
import base64
import json
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


def _entry(key: str, size: int = 10) -> dict:
    return {
        "upload_id": key,
        "storage_key": key,
        "source_filename": key.rsplit("/", 1)[-1],
        "source_size_bytes": size,
        "verified_size_bytes": size,
    }


class _Store:
    """In-memory R2 for the frozen-input reconcile step."""

    def __init__(self, objects: dict[str, int]) -> None:
        self.objects = dict(objects)

    def head(self, key):
        return {"ContentLength": self.objects[key]} if key in self.objects else None

    def list(self, prefix):
        return [{"Key": k, "Size": v} for k, v in self.objects.items() if k.startswith(prefix)]

    def copy(self, src, dst):
        self.objects[dst] = self.objects[src]

    def delete(self, key):
        del self.objects[key]

    def sha256(self, key):
        raise AssertionError("sha256 not expected here")


def fake_r2() -> types.SimpleNamespace:
    moves: list[tuple[str, str]] = []
    listed: list[str] = []

    def list_objects(prefix: str) -> list[dict]:
        listed.append(prefix)
        return [
            {"Key": f"{prefix}clip.mp4"},
            {"Key": f"{prefix}foreign.mp4"},
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
    os.environ["SPORTREEL_INPUT_MANIFEST_JSON"] = json.dumps([_entry("raw/session_one/clip.mp4")])
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

    # Frozen input is currently under processed/ (previous attempt): the scoped
    # read must restore it first, leaving unrelated processed objects alone.
    store = _Store({"processed/session_one/clip.mp4": 10, "processed/other_batch/x.mp4": 5})
    batch_scope._store_factory = lambda: store
    batch_scope.install()
    # fake_r2 lists a static raw view; real listing is exercised by the store above.
    videos = module.get_new_videos()
    if store.objects != {"raw/session_one/clip.mp4": 10, "processed/other_batch/x.mp4": 5}:
        raise SystemExit(f"expected exact restore and untouched foreign object, got {store.objects}")
    if module.listed != ["raw/session_one/"]:
        raise SystemExit(f"expected scoped listing, got {module.listed}")
    if [video["key"] for video in videos] != ["raw/session_one/clip.mp4"]:
        raise SystemExit("expected only the scoped video object")
    if dedup_calls != [["raw/session_one/clip.mp4"]]:
        raise SystemExit(f"expected exact dedup admission gate, got {dedup_calls}")

    module.mark_as_processed("raw/session_one/clip.mp4")
    module.requeue_video("processed/session_one/clip.mp4")
    expected = {
        ("raw/session_one/clip.mp4", "processed/session_one/clip.mp4"),
        ("processed/session_one/clip.mp4", "raw/session_one/clip.mp4"),
    }
    if not expected.issubset(set(module.moves)):
        raise SystemExit(f"expected scoped moves, got {module.moves}")
    store.objects = {"processed/session_one/clip.mp4": 10, "processed/other_batch/x.mp4": 5}
    if module.restore_processed_to_raw() != 1 or "raw/session_one/clip.mp4" not in store.objects:
        raise SystemExit("batch restore must be manifest-driven and restore exactly the frozen input")
    if "processed/other_batch/x.mp4" not in store.objects:
        raise SystemExit("batch restore must never touch another batch")




def run_flat_raw_admission_probe() -> None:
    """Batchless mode processes everything in the first folder, at any depth under raw/.

    The app uploads into raw/<batch>/, so root-only admission would find nothing and every
    "Run pipeline" would end as no_input. Non-video objects are still ignored, and duplicate
    candidates are excluded without deleting any source footage.
    """
    import importlib
    os.environ.pop("RAW_BATCH_ID", None)
    os.environ.pop("BATCH_ID", None)
    os.environ.pop("SPORTREEL_INPUT_MANIFEST_JSON", None)
    os.environ.pop("SPORTREEL_INPUT_MANIFEST_B64", None)
    module = fake_r2()
    candidates = [
        "raw/flat.mp4", "raw/old_batch/nested.mp4",
        "raw/old_batch/deeper/hidden.mp4", "raw/note.txt",
    ]
    module.list_objects = lambda prefix: [
        {"Key": key} for key in candidates if key.startswith(prefix)
    ]
    sys.modules["integrations.r2_storage"] = module
    admitted = []
    def prepare_canonical_sources(videos, download_one, **kwargs):
        admitted.extend(video["id"] for video in videos)
        assert kwargs.get("preserve_sources") is True
        return videos
    sys.modules["pipeline.source_upload_dedup"] = types.SimpleNamespace(
        prepare_canonical_sources=prepare_canonical_sources
    )
    import pipeline.r2_batch_scope as batch_scope
    batch_scope = importlib.reload(batch_scope)
    batch_scope.install()
    result = module.get_new_videos()
    expected = ["raw/flat.mp4", "raw/old_batch/nested.mp4", "raw/old_batch/deeper/hidden.mp4"]
    assert admitted == expected, admitted
    assert [item["id"] for item in result] == expected, result


def run_manifest_allowlist_probe() -> None:
    batch = "batch_24"
    os.environ["RAW_BATCH_ID"] = batch
    allowed = [f"raw/{batch}/source_{i:02d}.mp4" for i in range(24)]
    manifest = [_entry(key) for key in allowed]
    os.environ["SPORTREEL_INPUT_MANIFEST_B64"] = base64.b64encode(
        json.dumps(manifest).encode("utf-8")
    ).decode("ascii")

    listed: list[str] = []
    module = fake_r2()
    def list_objects(prefix: str) -> list[dict]:
        listed.append(prefix)
        return [{"Key": key} for key in allowed]
    module.list_objects = list_objects
    sys.modules["integrations.r2_storage"] = module

    admitted: list[list[str]] = []
    def prepare_canonical_sources(videos: list[dict], download_one, **kwargs) -> list[dict]:
        admitted.append([video["id"] for video in videos])
        return videos
    sys.modules["pipeline.source_upload_dedup"] = types.SimpleNamespace(
        prepare_canonical_sources=prepare_canonical_sources
    )

    import importlib
    import pipeline.r2_batch_scope as batch_scope
    batch_scope = importlib.reload(batch_scope)
    store = _Store({key: 10 for key in allowed})
    batch_scope._store_factory = lambda: store
    batch_scope.install()
    videos = module.get_new_videos()
    assert len(videos) == 24, f"expected 24 frozen inputs, got {len(videos)}"
    assert len(admitted) == 1 and admitted[0] == allowed
    # An unexpected production input in the batch namespace must fail closed.
    store.objects[f"raw/{batch}/foreign.mp4"] = 3
    try:
        module.get_new_videos()
    except RuntimeError as exc:
        assert "unexpected" in str(exc)
    else:
        raise AssertionError("unexpected raw input must stop the run before admission")
    os.environ.pop("SPORTREEL_INPUT_MANIFEST_B64", None)

def run_simple_raw_reset_probe() -> None:
    """Exercise the real reset recovery logic against an isolated in-memory R2.

    Stage-folder model: reset returns each tracked source to raw/ at the same relative path,
    and clears it from processed/ only after every restored copy is verified. Objects in
    processed/ that are not tracked source uploads are never touched. The full flow against a
    real S3 protocol server is covered by test_stage_folder_flow_e2e.py.
    """
    source = read("scripts/reset_and_rerun.py")
    parsed = ast.parse(source)
    function = next(node for node in parsed.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "_restore_r2_sources_to_raw")
    namespace: dict = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<isolated-reset>", "exec"), namespace)
    objects: dict[str, bytes] = {
        "raw/existing.mp4": b"e" * 10,
        "processed/batch_a/one.mp4": b"1" * 11,
        "processed/batch_b/two.mp4": b"2" * 12,
        "processed/delivered_reel.mp4": b"d" * 13,
    }
    events: list[tuple] = []
    fail_copy_for: set[str] = set()

    def copy_verified(src, dest):
        if src in fail_copy_for:
            raise RuntimeError("simulated R2 copy outage")
        if dest in objects:
            if objects[dest] == objects[src]:
                return "present"
            raise RuntimeError(f"Destination already exists with different content: {dest}")
        events.append(("copy", src, dest))
        objects[dest] = objects[src]
        return "copied"

    fake = types.SimpleNamespace(
        RAW_PREFIX="raw/", PROCESSED_PREFIX="processed/",
        list_objects=lambda prefix: [{"Key": key} for key in objects if key.startswith(prefix)],
        _is_video_key=lambda key: key.endswith(".mp4"),
        _head=lambda key: {"ContentLength": len(objects[key])} if key in objects else None,
        same_object_bytes=lambda a, b: a in objects and b in objects and objects[a] == objects[b],
        copy_object_verified=copy_verified,
        delete_object=lambda key: (events.append(("delete", key)), objects.pop(key)),
    )
    import integrations
    previous_uploads = sys.modules.get("integrations.source_uploads")
    previous_uploads_attr = getattr(integrations, "source_uploads", None)
    tracked = {"raw/batch_a/one.mp4", "raw/batch_b/two.mp4"}
    rekeyed: list[tuple[str, str]] = []

    def rekey(old, new):
        rekeyed.append((old, new))
        if old in tracked:
            tracked.discard(old)
            tracked.add(new)
        return True

    fake_uploads = types.SimpleNamespace(
        get_source_upload=lambda key: {"status": "verified"} if key in tracked else None,
        rekey_source_upload=rekey)
    sys.modules["integrations.source_uploads"] = fake_uploads
    integrations.source_uploads = fake_uploads
    previous = sys.modules.get("integrations.r2_storage")
    previous_attr = getattr(integrations, "r2_storage", None)
    sys.modules["integrations.r2_storage"] = fake
    integrations.r2_storage = fake
    try:
        recover = namespace["_restore_r2_sources_to_raw"]
        snapshot = dict(objects)
        assert recover(dry_run=True) == 2 and objects == snapshot and not events
        assert recover() == 2
        assert objects == {
            "raw/existing.mp4": b"e" * 10,
            "raw/one.mp4": b"1" * 11, "raw/two.mp4": b"2" * 12,
            "processed/delivered_reel.mp4": b"d" * 13,
        }, "sources must return flat to raw/ (no batch folder); non-source outputs stay put"
        assert sorted(rekeyed) == [("raw/batch_a/one.mp4", "raw/one.mp4"), ("raw/batch_b/two.mp4", "raw/two.mp4")], rekeyed
        # Every verified copy happens before any deletion from processed/.
        kinds = [event[0] for event in events]
        assert kinds == ["copy", "copy", "delete", "delete"], kinds
        # Nothing left to do on a second reset.
        before = dict(objects)
        assert recover() == 0 and objects == before
        # A different-content file already at the destination fails closed, changing nothing.
        objects["processed/batch_a/one.mp4"] = b"1" * 11
        tracked.add("raw/batch_a/one.mp4")
        objects["raw/one.mp4"] = b"X" * 11
        before = dict(objects)
        try:
            recover()
        except RuntimeError as exc:
            assert "collision" in str(exc)
        else:
            raise AssertionError("different content at the destination must block reset")
        assert objects == before
        # An outage while restoring must not delete anything from processed/.
        objects["raw/one.mp4"] = b"1" * 11
        objects.pop("raw/one.mp4")
        tracked.add("raw/batch_b/two.mp4")
        objects["processed/batch_b/two.mp4"] = b"2" * 12
        objects.pop("raw/two.mp4")
        fail_copy_for.add("processed/batch_b/two.mp4")
        before = dict(objects)
        try:
            recover()
        except RuntimeError as exc:
            assert "simulated R2 copy outage" in str(exc)
        else:
            raise AssertionError("copy outage must abort reset")
        assert {k for k in before if k.startswith("processed/")} <= set(objects), "processed sources must survive"
    finally:
        if previous_uploads is None:
            sys.modules.pop("integrations.source_uploads", None)
        else:
            sys.modules["integrations.source_uploads"] = previous_uploads
        if previous_uploads_attr is None:
            delattr(integrations, "source_uploads")
        else:
            integrations.source_uploads = previous_uploads_attr
        if previous is None:
            sys.modules.pop("integrations.r2_storage", None)
        else:
            sys.modules["integrations.r2_storage"] = previous
        if previous_attr is None:
            delattr(integrations, "r2_storage")
        else:
            integrations.r2_storage = previous_attr


def run_atomic_r2_copy_probe() -> None:
    """Exercise the actual create-only copy implementation with a competing writer."""
    parsed = ast.parse(read("integrations/r2_storage.py"))
    fn = next(node for node in parsed.body if isinstance(node, ast.FunctionDef)
              and node.name == "copy_object_if_absent")
    class ClientError(Exception):
        def __init__(self, status):
            self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}
    prior = sys.modules.get("botocore.exceptions")
    sys.modules["botocore.exceptions"] = types.SimpleNamespace(ClientError=ClientError)
    objects = {"raw/source.mp4": b"original"}
    calls = []
    class Body:
        def __init__(self, data):
            self.data = data
            self.closed = False
        def read(self, amount=-1):
            return self.data
        def close(self):
            self.closed = True
    class Client:
        def get_object(self, *, Bucket, Key):
            return {"Body": Body(objects[Key]), "ContentLength": len(objects[Key]),
                    "ContentType": "video/mp4"}
        def put_object(self, *, Bucket, Key, Body, ContentLength, ContentType, IfNoneMatch):
            assert IfNoneMatch == "*" and ContentLength == len(objects["raw/source.mp4"])
            calls.append(Key)
            if Key in objects:
                raise ClientError(412)
            objects[Key] = Body.read()
    client = Client()
    namespace = {"_client": lambda: client, "_bucket": lambda: "sandbox",
                 "_content_type": lambda key: "video/mp4"}
    try:
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "<isolated-conditional-copy>", "exec"), namespace)
        copy = namespace["copy_object_if_absent"]
        copy("raw/source.mp4", "raw/restored.mp4")
        assert objects["raw/restored.mp4"] == b"original"
        # A concurrent writer wins before our conditional PutObject.
        objects["raw/race.mp4"] = b"other"
        for dest in ("raw/restored.mp4", "raw/race.mp4"):
            try:
                copy("raw/source.mp4", dest)
            except RuntimeError as exc:
                assert "Destination already exists" in str(exc)
            else:
                raise AssertionError("Conditional copy overwrote an existing destination")
        assert objects["raw/race.mp4"] == b"other"
        assert objects["raw/restored.mp4"] == b"original"
        assert objects["raw/source.mp4"] == b"original"
    finally:
        if prior is None:
            sys.modules.pop("botocore.exceptions", None)
        else:
            sys.modules["botocore.exceptions"] = prior


def main() -> int:
    run_simple_raw_reset_probe()
    run_atomic_r2_copy_probe()
    upload_route = read("web-api/src/app/api/operator/upload/route.ts")
    multipart_start = read("web-api/src/app/api/operator/upload/multipart/start/route.ts")
    start_route = read("web-api/src/app/api/operator/pipeline/start/route.ts")
    reset_route = read("web-api/src/app/api/operator/pipeline/reset/route.ts")
    batch_helper = read("web-api/src/lib/upload-batch-manifest.ts")
    r2_lib = read("web-api/src/lib/r2-storage.ts")
    workflow = read(".github/workflows/pipeline-run.yml")
    mobile = read("mobile/src/app/(operator)/pipeline.tsx")
    contracts = read("mobile/src/features/operator/types/contracts.ts")
    scope = read("pipeline/r2_batch_scope.py")
    bootstrap = read("pipeline/bootstrap.py")
    dedup = read("pipeline/source_upload_dedup.py")

    for text in [scope, bootstrap, dedup, read("scripts/test_batch_scope_contract.py")]:
        ast.parse(text)

    require("r2 upload key", r2_lib, ["safeBatchId", "newBatchId", "raw/${storageName}", "batch_id: batchId"])
    if ".replace(/^_+|_+$/g, '')" in r2_lib:
        raise SystemExit("safeBatchId must not use the polynomial-time boundary-trim regex")
    require(
        "linear safe batch id sanitizer",
        r2_lib,
        ["for (const char of input)", "normalized.charCodeAt(start)", "normalized.charCodeAt(end - 1)"],
    )
    require(
        "durable batch resolver",
        batch_helper,
        [
            "resolveUploadBatchId",
            "resolveReadyUploadBatchId",
            "uniqueBatchIdForStates",
            "Multiple durable upload batches are active",
            "No unique size-verified upload batch is ready",
        ],
    )
    require(
        "upload route",
        upload_route,
        [
            "files?: UploadFileInput[]",
            "normalizeUploadFiles",
            "uploadFilename",
            "resolveUploadBatchId",
            "client_upload_id",
            "createSinglePutSourceManifest",
            "createR2UploadUrlForKey(session.storageKey)",
            "registerSourceUploadBatchMembership",
            "batch_id: session.batchId",
            "uploads,",
        ],
    )
    require(
        "multipart start route",
        multipart_start,
        [
            "client_upload_id",
            "resolveUploadBatchId",
            "registerMultipartBatchMembership",
            "resumed_existing_start",
        ],
    )
    require(
        "pipeline start route",
        start_route,
        [
            "batch_id?: string",
            "safeBatchId",
            "batch_id is required",
            "assertUploadBatchReady",
            "input_manifest_frozen: true",
            "client_payload",
            "batch_id",
        ],
    )
    require("pipeline reset route", reset_route, ["batch_id", "safeBatchId", "inputs", "pipeline_run_id: run.id", "prepareUploadBatchRerun", "releaseUploadBatchAfterDispatchFailure", "input_files: []", "rerunBatch.inputManifest"])
    rerun_migration = read("supabase/migrations/20261004_prepare_upload_batch_rerun.sql")
    require("atomic rerun migration", rerun_migration, ["for update", "previous pipeline run", "still active", "v_actual <> v_batch.expected_file_count", "v_verified <> v_batch.expected_file_count", "jsonb_array_length(v_manifest) <> v_batch.expected_file_count", "pipeline_run_id=p_pipeline_run_id", "input_manifest=v_manifest"])
    require("run-scoped reset authority", reset_route, [
        "sourceRunId", "sourceRun.meta?.batch_id", "sourceRun.input_files",
        "Cannot reset an active pipeline run", "Selected run has no matching frozen input manifest",
    ])
    require("run selection UI", read("mobile/src/features/operator/components/PipelineRunsCard.tsx"), [
        "onSelectRun", "Select this run for reset",
    ])
    if "assertUploadBatchReady(batchId)" in reset_route:
        raise SystemExit("reset must use the migration-compatible atomic rerun gate, not ready-only assertion")
    require("pipeline workflow", workflow, ["batch_id:", "RAW_BATCH_ID", "github.event.client_payload.batch_id || inputs.batch_id || ''"])
    require("mobile batch state", mobile, ["activeBatchId", "lastBatchId", "batch_id: activeBatchId"])
    require("simple operator run/reset", mobile, ["/api/operator/pipeline/start-raw", "/api/operator/pipeline/reset-raw", "Standard reset", "Full clean"])
    shared = read("web-api/src/lib/pipeline-dispatch-core.ts")
    require("simple server run", read("web-api/src/app/api/operator/pipeline/start-raw/route.ts"), ["requireOperator", "dispatchOperatorPipelineRun('process')"])
    require("simple server reset", read("web-api/src/app/api/operator/pipeline/reset-raw/route.ts"), ["requireOperator", "dispatchOperatorPipelineRun('reset_and_rerun'", "full_clean"])
    require("shared dispatch service", shared, ["pipeline-run.yml/dispatches", "batch_id: ''", "pipeline_run_id: runId", "full_clean"])
    require("operator contracts", contracts, ["batch_id?: string | null"])
    require("canonical R2 bootstrap", bootstrap, ["pipeline.r2_batch_scope", "_install_r2_batch_scope", 'if backend != "r2":'])
    if "or not batch_id" in bootstrap:
        raise SystemExit("global R2 runs must not bypass exact dedup admission")
    require("r2 batch scope runtime", scope, ["scoped_prefix", "move_between_prefixes", "prepare_canonical_sources", "get_new_videos", "mark_as_processed", "restore_processed_to_raw"])

    if "const key = `raw/${batchId}/${storageName}`" in r2_lib:
        raise SystemExit("r2 storage key must be flat (raw/<file>); the batch id is not part of the path")
    if "createR2UploadUrl(filename, requestedBatchId)" in upload_route:
        raise SystemExit("upload route must use normalized batch files")
    if "createR2UploadUrl(file.filename, batchId)" in upload_route:
        raise SystemExit("upload route must use unique per-file upload names")
    if "safeBatchId(requestedBatchId) || newBatchId()" in upload_route:
        raise SystemExit("upload route must recover durable batch state instead of trusting only request/mobile state")

    run_scope_probe()
    run_flat_raw_admission_probe()
    os.environ.pop("SPORTREEL_INPUT_MANIFEST_JSON", None)
    run_manifest_allowlist_probe()
    os.environ.pop("SPORTREEL_INPUT_MANIFEST_JSON", None)
    print("Batch scope contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
