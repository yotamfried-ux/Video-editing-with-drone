#!/usr/bin/env python3
"""Static contract for the Operator "Clean Video Storage" feature (safety invariants)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(p: str) -> str:
    return (ROOT / p).read_text(encoding="utf-8")


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(f"FAIL: {msg}")


def main() -> int:
    route = read("web-api/src/app/api/operator/storage/clean/route.ts")
    svc = read("web-api/src/lib/video-storage-cleanup.ts")
    rt = read("web-api/src/lib/video-storage-cleanup-runtime.ts")
    mig = read("supabase/migrations/20260930_video_storage_cleanup.sql")
    ui = read("mobile/src/features/operator/components/CleanVideoStorageCard.tsx")
    client = read("mobile/src/features/operator/lib/cleanVideoStorage.ts")
    e2e_wf = read(".github/workflows/video-storage-clean-e2e.yml")
    manual_wf = read(".github/workflows/clean-video-storage.yml")

    # Operator-only, mutation is POST only, auth before any work.
    handlers = re.findall(r"export\s+async\s+function\s+(GET|POST|PUT|PATCH|DELETE)\b", route)
    require(sorted(handlers) == ["GET", "POST"], f"unexpected handlers {handlers}")
    for method in ("GET", "POST"):
        body = route.split(f"function {method}")[1]
        require(body.lstrip().split("requireOperator", 1)[0].count("await") == 0, f"{method}: work before auth")
        require("requireOperator(req)" in body.split("\n", 3)[1] + body.split("\n", 3)[2], f"{method}: requireOperator must be first")
    get_body = route.split("function GET")[1].split("function POST")[0]
    require("advanceCleanup" not in get_body, "GET must never mutate")
    require("CLEANUP_CONFIRMATION" in route and "isRunId" in route, "POST needs confirmation / uuid run_id")

    # Client cannot choose bucket/key/prefix.
    require(not re.search(r"body\??\.(bucket|key|prefix|path)", route), "client-supplied bucket/key/prefix")
    require(re.search(r"\{ confirmation\?: unknown; run_id\?: unknown \}", route) is not None, "request body must be only confirmation/run_id")

    # Storage APIs only; never SQL on storage.objects; scope gate exists and is used before deletes.
    for text, name in ((svc, "service"), (rt, "runtime"), (mig, "migration")):
        require(re.search(r"(from|into|update|join|delete)\s+(from\s+)?storage\.objects", text, re.I) is None, f"{name} runs SQL on storage.objects")
    require("delete from" not in mig.lower(), "migration must not delete rows (history preserved)")
    require("isInScopeR2VideoKey" in svc and svc.count("isInScopeR2VideoKey(key)") >= 1, "delete path must use scope gate")
    require("'metadata/'" in svc and "athlete_photos" in svc, "protected prefixes/buckets missing")
    require("abortR2MultipartUpload" in rt and "deleteR2Object" in rt, "must use R2 delete/abort APIs")
    require("storage.from(bucket).remove" in rt, "must use Supabase Storage API")

    # Fail-closed success derivation + single-runner lock + audit.
    require("verifyClean" in svc and "phase: verification.ok ? 'succeeded' : 'failed'" in svc, "success must derive from verification")
    require("video_storage_cleanup_single_running_idx" in mig and "unique index" in mig.lower(), "single running cleanup lock missing")
    require("pipeline_active" in mig, "must refuse while pipeline is live")

    # Mobile: no direct Supabase, no secrets, explicit confirmation, double-submit guard, exact success copy.
    for text in (ui, client):
        require("@/shared/lib/supabase" not in text, "operator UI must not use direct Supabase")
        require("SERVICE" not in text and "R2_" not in text, "no server credentials in client")
    require("operatorFetch" in client, "client must use operatorFetch")
    require("inFlight.current" in ui, "double-submit guard missing")
    require("disabled={!understood}" in ui, "explicit confirmation gate missing")
    require("Video storage is clean — 0 active videos. You can upload a new set." in client, "success copy")
    require("isVerifiedClean" in client, "client must require verified success")

    # No GitHub Actions dispatch from the API; destructive workflows never run on pull_request.
    require("api.github.com" not in route + rt + svc, "cleanup API must not dispatch GitHub Actions")
    require(not re.search(r"^\s*(pull_request|push):", e2e_wf.split("jobs:")[0], re.M), "E2E workflow must be dispatch-only (destructive on production)")
    require(not re.search(r"^\s*pull_request", manual_wf.split("jobs:")[0], re.M), "manual cleanup workflow must not run on pull_request")
    require(not re.search(r"^\s*push:", manual_wf.split("jobs:")[0], re.M), "manual cleanup workflow must be dispatch-only")
    require("DELETE_OLD_VIDEOS" in manual_wf, "manual workflow needs typed confirmation")
    print("video storage cleanup contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
