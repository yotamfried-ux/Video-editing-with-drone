#!/usr/bin/env python3
"""Bind the operator's pipeline_runs row to this exact GitHub Actions run.

The web-api creates the row before dispatch, when GitHub has not assigned a run id yet,
so it can only store the generic workflow URL. This stdlib-only step runs first in the
workflow and records the real ``github_run_id`` / run URL (with ``/attempts/N`` for
re-runs) and moves the row from ``queued`` to ``running``. On a re-run attempt (N > 1)
it also reopens a row the previous attempt finalized, so the retry is tracked and the
failure finalizer can act on it. Best-effort: always exits 0 so it cannot fail the job.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def run_url(server: str, repo: str, run_id: str, attempt: int) -> str:
    base = f"{server.rstrip('/')}/{repo}/actions/runs/{run_id}"
    return f"{base}/attempts/{attempt}" if attempt > 1 else base


def build_requests(
    *, run_id: str, supabase_url: str, service_key: str, github_run_id: str,
    github_run_url: str, attempt: int, now: str,
) -> list[urllib.request.Request]:
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    endpoint = f"{supabase_url.rstrip('/')}/rest/v1/pipeline_runs"
    correlation: dict[str, object] = {"github_run_url": github_run_url, "updated_at": now}
    if github_run_id.isdigit():
        correlation["github_run_id"] = int(github_run_id)  # bigint column
    if attempt > 1:
        # Re-run: reopen the row regardless of the previous attempt's terminal state.
        correlation.update({
            "status": "running", "stage": "workflow_started", "error": None,
            "finished_at": None, "started_at": now,
        })
        query = urllib.parse.urlencode({"id": f"eq.{run_id}"})
        return [urllib.request.Request(f"{endpoint}?{query}", data=json.dumps(correlation).encode(),
                                       method="PATCH", headers=headers)]
    first = urllib.request.Request(
        f"{endpoint}?{urllib.parse.urlencode({'id': f'eq.{run_id}'})}",
        data=json.dumps(correlation).encode(), method="PATCH", headers=headers)
    # Only a still-queued row moves to running; never overwrite a terminal state.
    started = {"status": "running", "stage": "workflow_started", "started_at": now, "updated_at": now}
    second = urllib.request.Request(
        f"{endpoint}?{urllib.parse.urlencode({'id': f'eq.{run_id}', 'status': 'eq.queued'})}",
        data=json.dumps(started).encode(), method="PATCH", headers=headers)
    return [first, second]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)
    run_id = args.run_id.strip()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    gh_run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    server = os.getenv("GITHUB_SERVER_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not run_id:
        print("correlation: no pipeline_runs id for this workflow run; nothing to record")
        return 0
    if not (supabase_url and service_key and gh_run_id and server and repo):
        print("correlation: missing SUPABASE_URL / SUPABASE_SERVICE_KEY / GitHub run context", file=sys.stderr)
        return 0
    attempt_raw = os.getenv("GITHUB_RUN_ATTEMPT", "1").strip()
    attempt = int(attempt_raw) if attempt_raw.isdigit() and int(attempt_raw) > 0 else 1
    requests = build_requests(
        run_id=run_id, supabase_url=supabase_url, service_key=service_key, github_run_id=gh_run_id,
        github_run_url=run_url(server, repo, gh_run_id, attempt), attempt=attempt,
        now=datetime.now(timezone.utc).isoformat())
    for request in requests:
        try:
            with urllib.request.urlopen(request, timeout=int(os.getenv("CORRELATION_TIMEOUT_S", "20"))) as response:
                rows = json.loads(response.read().decode("utf-8") or "[]")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"correlation: could not update pipeline_runs {run_id}: {exc}", file=sys.stderr)
            return 0
        print(f"correlation: updated {len(rows)} row(s) for pipeline_runs {run_id} (run {gh_run_id} attempt {attempt})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
