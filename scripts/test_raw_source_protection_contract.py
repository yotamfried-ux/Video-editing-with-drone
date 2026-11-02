#!/usr/bin/env python3
"""RAW permanence contract: no code path may delete, move or replace an original source video.

Two layers:
  1. Static inventory. Every call site that can delete an R2 object (or a whole prefix) anywhere in the
     repository must be listed below with the reason it cannot touch an original source. A new deletion
     site fails this test until someone reviews it and adds it (or, better, routes it through the guard).
  2. Behaviour. The central guard in integrations/r2_storage.py refuses deletion/moves of raw/ objects and
     processed/ videos, and the pipeline modules are checked for the permanence rules.

The real end-to-end proof against an S3 protocol server is scripts/test_raw_permanence_e2e.py.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Anything that can remove an object/prefix in object storage.
DELETE_RE = re.compile(
    r"delete_object\(|\.delete_objects\(|DeleteObject|deleteR2Object\(|signedFetch\('DELETE'|"
    r"aws s3 (?:rm|mv)|rclone (?:delete|move|purge|sync)|removeObjects|\.remove\(\[")
# The local Ground Truth tool keeps its own tests and never deletes in R2; production code must not reference it by
# name (guarded elsewhere), so the folder name is only used here to be skipped.
STUDIO_DIR = "annotation" + "-studio/"
SCANNED = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".yml", ".yaml", ".sh"}

# file -> (reason it cannot delete an original source, tokens that must still be present in that file)
ALLOWED: dict[str, tuple[str, list[str]]] = {
    "integrations/r2_storage.py": (
        "the ONE guarded implementation: delete_object/move_object refuse raw/ and processed/ videos",
        ["assert_not_protected_source(key, \"delete\")", "assert_not_protected_source(source_key, \"move\")", "class ProtectedSourceError"]),
    "pipeline/r2_batch_restore.py": (
        "R2Store.delete only discards a faulty copy that this very restore just created; anything else is refused",
        ["if key not in self._created", "ProtectedSourceError"]),
    "web-api/src/lib/r2-storage.ts": (
        "web API delete/move refuse raw/ and processed/ keys",
        ["Refusing to delete an original source video", "Refusing to move an original source video"]),
    "web-api/src/lib/video-storage-cleanup.ts": (
        "cleanup scope is derived outputs only; raw/ and processed/ are reported, never deleted",
        ["R2_SOURCE_PREFIXES", "isSourceR2Key", "Refusing to delete an original source video"]),
    "scripts/reset_and_rerun.py": (
        "_r2_delete_prefix is only ever called for approved/ and review/ (derived outputs); the guard also applies",
        ["_r2_delete_prefix(r2_storage.APPROVED_PREFIX", "_r2_delete_prefix(r2_storage.REVIEW_PREFIX"]),
    "scripts/check_storage_access.py": (
        "preflight deletes only its own review/_preflight_* probe object",
        ["review/_preflight_"]),
    "scripts/video_storage_cleanup_e2e.py": (
        "QA harness teardown removes only keys tagged e2e_clean_ (never real objects)",
        ["e2e_clean_"]),
    "scripts/background_upload_evidence.py": (
        "QA purge of a qualification batch, refused unless purge_guard proves it is a disposable test batch",
        ["purge_guard(rows, a.batch_id)", "purge refused"]),
    "scripts/app_review_delivery_e2e.py": (
        "QA cleanup of the two synthetic files this e2e seeded itself (blocked_name/ready_name)",
        ["blocked_name", "ready_name"]),
    "scripts/test_real_r2_multipart_upload.py": ("real-R2 test deletes only the keys it created", []),
    "scripts/test_real_r2_conditional_copy.py": ("real-R2 test deletes only the keys it created", []),
    ".github/workflows/upload-foundation-release.yml": (
        "release gate deletes only its own synthetic signer-evidence object",
        ["R2_WEB_API_EVIDENCE_PATH"]),
    ".github/workflows/purge-upl01-test-uploads.yml": (
        "one-off purge of exactly eight listed UPL-01 test objects (explicit keys and sizes, asserted before deleting)",
        ["assert len(by)==8"]),
    # moto-only (in-memory S3) test harnesses: never production storage
    "scripts/test_raw_permanence_e2e.py": ("moto S3 server on 127.0.0.1; fixture manipulation only", ["127.0.0.1"]),
}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if Path(f).suffix in SCANNED and "node_modules" not in f
            and not f.startswith(STUDIO_DIR)]


def deletion_sites() -> dict[str, list[tuple[int, str]]]:
    sites: dict[str, list[tuple[int, str]]] = {}
    for name in tracked_files():
        path = ROOT / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*")) or re.match(r"(async )?def |function ", stripped) or "export async function" in stripped:
                continue
            if DELETE_RE.search(line):
                sites.setdefault(name, []).append((number, stripped[:120]))
    return sites


def test_every_deletion_site_is_reviewed() -> None:
    sites = deletion_sites()
    unreviewed = {f: s for f, s in sites.items() if f not in ALLOWED and not f.startswith("scripts/test_")}
    if unreviewed:
        detail = "; ".join(f"{f}:{s[0][0]} {s[0][1]}" for f, s in unreviewed.items())
        raise SystemExit(
            "New object-deletion call site(s) not reviewed for RAW permanence. Route them through "
            f"integrations.r2_storage.delete_object (guarded) or add a justified entry here: {detail}")
    # scripts/test_*.py fakes/harnesses may mention deletion, but real-R2 ones must be listed
    for f, s in sites.items():
        if f.startswith("scripts/test_") and f not in ALLOWED and any("client.delete_object" in line for _, line in s):
            raise SystemExit(f"{f} deletes through a real client but is not reviewed: {s[0]}")
    for f, (reason, tokens) in ALLOWED.items():
        path = ROOT / f
        if not path.exists():
            raise SystemExit(f"allowlisted file disappeared (remove it from the list): {f}")
        text = path.read_text(encoding="utf-8")
        missing = [t for t in tokens if t not in text]
        if missing:
            raise SystemExit(f"{f}: the safety condition that justified its deletion site is gone: {missing} ({reason})")


def test_guard_refuses_originals() -> None:
    from integrations import r2_storage as r2

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError(f"guard must refuse before any storage call ({name})")

    r2._client = lambda: NoNetwork()
    for key in ("raw/a.mp4", "raw/batch_1/b.MOV", "raw/anything.txt", "processed/c.mp4", "processed/batch/d.mkv"):
        assert r2.is_protected_source_key(key), key
        for action in (lambda k=key: r2.delete_object(k), lambda k=key: r2.move_object(k, "review/x.mp4"),
                       lambda k=key: r2.move_object_verified(k, "review/x.mp4")):
            try:
                action()
            except r2.ProtectedSourceError:
                continue
            raise SystemExit(f"{key}: deletion/move was not refused")
    for key in ("review/d.mp4", "approved/e.mp4", "previews/p.mp4", "metadata/source_state/abc.json", "processed/delivered.json"):
        assert not r2.is_protected_source_key(key), key


def test_pipeline_rules_are_in_the_code() -> None:
    scope = (ROOT / "pipeline/r2_batch_scope.py").read_text(encoding="utf-8")
    dedup = (ROOT / "pipeline/source_upload_dedup.py").read_text(encoding="utf-8")
    reset = (ROOT / "scripts/reset_and_rerun.py").read_text(encoding="utf-8")
    storage = (ROOT / "integrations/r2_storage.py").read_text(encoding="utf-8")
    assert "preserve_sources=True" in scope and "move_object" not in scope, "batch scope must not move or delete sources"
    assert "r2.mark_source_processed(" in scope, "processing must only write a marker"
    assert "delete_source(" not in dedup and "delete_object" not in dedup, "dedup must have no deletion code"
    assert "r2.delete_object(source)" not in reset and "move_object" not in reset, "reset must not delete or move sources"
    # processing records state without touching the video
    mark = storage[storage.index("def mark_as_processed"):storage.index("def ensure_raw_copy")]
    assert "move_object" not in mark and "delete_object" not in mark and "copy_object" not in mark


def main() -> int:
    test_every_deletion_site_is_reviewed()
    test_guard_refuses_originals()
    test_pipeline_rules_are_in_the_code()
    print("RAW source protection contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
