#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from pipeline.source_upload_dedup import prepare_canonical_sources, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing tokens: {missing}")


def verified_row(upload_id: str, key: str, size: int, verified_at: str) -> dict:
    return {
        "id": upload_id,
        "storage_key": key,
        "status": "verified",
        "verified_at": verified_at,
        "verified_size_bytes": size,
        "canonical_upload_id": upload_id,
    }


def test_streaming_sha256() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        first = Path(tmp) / "first.mp4"
        second = Path(tmp) / "second.mp4"
        changed = Path(tmp) / "changed.mp4"
        payload = (b"sportreel-exact-source\x00" * 1024) + b"tail"
        first.write_bytes(payload)
        second.write_bytes(payload)
        changed.write_bytes(payload[:-1] + b"X")
        expected = hashlib.sha256(payload).hexdigest()
        if sha256_file(str(first), chunk_bytes=17) != expected:
            raise SystemExit("streaming SHA-256 does not match hashlib")
        if sha256_file(str(second), chunk_bytes=31) != expected:
            raise SystemExit("byte-identical files must have the same SHA-256")
        if sha256_file(str(changed), chunk_bytes=31) == expected:
            raise SystemExit("changed bytes must not share the exact-content SHA-256")


def run_duplicate_case(*, delete_fails: bool = False) -> tuple[list[dict], list[str], list[tuple[str, str]], list[tuple[str, str, str]]]:
    old_key = "raw/batch/z_old_name.mp4"
    new_key = "raw/batch/a_new_name.mp4"
    payload = b"byte-identical-video" * 4096
    rows = {
        old_key: verified_row("old-upload", old_key, len(payload), "2026-07-23T10:00:00+00:00"),
        new_key: verified_row("new-upload", new_key, len(payload), "2026-07-23T11:00:00+00:00"),
    }
    deleted: list[str] = []
    removed: list[tuple[str, str]] = []
    removal_errors: list[tuple[str, str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        paths: dict[str, Path] = {}

        def download(video: dict) -> dict:
            key = video["id"]
            path = Path(tmp) / f"{video['name']}.download"
            path.write_bytes(payload)
            paths[key] = path
            return {"path": str(path), "meta": video}

        def get_upload(key: str) -> dict | None:
            return rows.get(key)

        def resolve(upload_id: str, content_sha256: str) -> dict:
            if content_sha256 != hashlib.sha256(payload).hexdigest():
                raise SystemExit("resolver received the wrong SHA-256")
            if upload_id == "old-upload":
                return {
                    "content_sha256": content_sha256,
                    "canonical": {
                        "upload_id": "old-upload",
                        "storage_key": old_key,
                        "verified_at": rows[old_key]["verified_at"],
                    },
                    "superseded": [],
                }
            if upload_id == "new-upload":
                return {
                    "content_sha256": content_sha256,
                    "canonical": {
                        "upload_id": "new-upload",
                        "storage_key": new_key,
                        "verified_at": rows[new_key]["verified_at"],
                    },
                    "superseded": [{
                        "upload_id": "old-upload",
                        "storage_key": old_key,
                        "verified_at": rows[old_key]["verified_at"],
                    }],
                }
            raise SystemExit(f"unexpected upload id: {upload_id}")

        def delete_source(key: str) -> None:
            if delete_fails and key == old_key:
                raise RuntimeError("simulated R2 delete failure")
            deleted.append(key)

        result = prepare_canonical_sources(
            [
                {"id": old_key, "key": old_key, "name": "z_old_name.mp4"},
                {"id": new_key, "key": new_key, "name": "a_new_name.mp4"},
            ],
            download,
            storage_backend="r2",
            get_upload=get_upload,
            resolve_duplicate=resolve,
            delete_source=delete_source,
            mark_removed=lambda upload_id, canonical_id: removed.append((upload_id, canonical_id)),
            mark_removal_error=lambda upload_id, canonical_id, error: removal_errors.append(
                (upload_id, canonical_id, error)
            ),
        )

        if paths[old_key].exists():
            raise SystemExit("superseded local source must be removed before analysis")
        if not paths[new_key].exists():
            raise SystemExit("canonical local source must remain available for analysis")
        if [item["id"] for item in result] != [new_key]:
            raise SystemExit(f"only newest verified source may remain canonical, got {result}")
        if result[0].get("source_upload_id") != "new-upload":
            raise SystemExit("canonical source upload id was not preserved")

        return result, deleted, removed, removal_errors


def test_newest_verified_wins_and_old_is_deleted() -> None:
    _, deleted, removed, errors = run_duplicate_case()
    if deleted != ["raw/batch/z_old_name.mp4"]:
        raise SystemExit(f"expected only old R2 key deletion, got {deleted}")
    if removed != [("old-upload", "new-upload")]:
        raise SystemExit(f"expected durable removal audit update, got {removed}")
    if errors:
        raise SystemExit(f"unexpected removal errors: {errors}")


def test_delete_failure_never_restores_pipeline_eligibility() -> None:
    result, deleted, removed, errors = run_duplicate_case(delete_fails=True)
    if [item["id"] for item in result] != ["raw/batch/a_new_name.mp4"]:
        raise SystemExit("delete failure must not make the superseded source eligible")
    if deleted or removed:
        raise SystemExit("failed deletion must not be recorded as removed")
    if len(errors) != 1 or errors[0][:2] != ("old-upload", "new-upload"):
        raise SystemExit(f"delete failure must be durably recorded, got {errors}")


def test_unverified_manifest_fails_closed() -> None:
    key = "raw/batch/unverified.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "unverified.mp4"

        def download(video: dict) -> dict:
            local.write_bytes(b"not-yet-verified")
            return {"path": str(local), "meta": video}

        try:
            prepare_canonical_sources(
                [{"id": key, "key": key, "name": "unverified.mp4"}],
                download,
                storage_backend="r2",
                get_upload=lambda _: {
                    "id": "pending-upload",
                    "storage_key": key,
                    "status": "uploading",
                    "verified_at": None,
                    "verified_size_bytes": None,
                },
                resolve_duplicate=lambda *_: {},
                delete_source=lambda _: None,
                mark_removed=lambda *_: None,
                mark_removal_error=lambda *_: None,
            )
        except RuntimeError as exc:
            if "not durably verified" not in str(exc):
                raise SystemExit(f"unexpected unverified error: {exc}")
        else:
            raise SystemExit("tracked unverified source must fail closed")
        if local.exists():
            raise SystemExit("failed preflight must clean its local staging file")


def test_static_contract() -> None:
    migration = read("supabase/migrations/20260723_source_upload_exact_dedup.sql")
    upload_route = read("web-api/src/app/api/operator/upload/route.ts")
    verify_route = read("web-api/src/app/api/operator/upload/verify/route.ts")
    manifest = read("web-api/src/lib/source-upload-manifest.ts")
    batch_scope = read("pipeline/r2_batch_scope.py")
    audit = read("docs/app-pipeline-audit.md")

    require("source upload migration", migration, [
        "create table if not exists public.source_uploads",
        "content_sha256",
        "verified_at desc, created_at desc, id desc",
        "exact_content_duplicate",
        "old_storage_key",
        "new_storage_key",
        "old_verified_at",
        "new_verified_at",
        "resolve_exact_source_duplicate",
        "grant execute on function public.resolve_exact_source_duplicate(uuid, text) to service_role",
    ])
    if "order by storage_key" in migration or "order by source_filename" in migration:
        raise SystemExit("canonical duplicate choice must not use a filename or R2 key")
    require("upload init manifest", upload_route, [
        "createSourceUploadManifests",
        "sourceSizeBytes: file.sourceSizeBytes",
        "upload_id: uploadId",
    ])
    require("verified upload manifest", verify_route, [
        "markSourceUploadVerified",
        "upload_status: manifest.status",
        "verified_at: manifest.verifiedAt",
    ])
    require("first verification authority", manifest, [
        "existing.verified_at ?? new Date().toISOString()",
        "status: 'size_mismatch'",
    ])
    require("pre-analysis admission gate", batch_scope, [
        "prepare_canonical_sources",
        "canonical = prepare_canonical_sources",
        "return canonical",
    ])
    require("authoritative audit", audit, [
        "Two byte-identical verified uploads must resolve to one canonical source.",
        "exact_content_duplicate",
    ])


def main() -> int:
    test_streaming_sha256()
    test_newest_verified_wins_and_old_is_deleted()
    test_delete_failure_never_restores_pipeline_eligibility()
    test_unverified_manifest_fails_closed()
    test_static_contract()
    print("Exact source-upload dedup contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
