#!/usr/bin/env python3
"""Mark an operator-tracked run row failed when its GitHub workflow died early.

The web-api inserts a ``delivery_runs`` / ``pipeline_runs`` row as ``queued``
before dispatching a workflow. The tracked Python entry point (``deliver.py`` /
``scripts/run_tracked.py``) is what normally moves that row to a terminal
status. If the workflow fails *before* that entry point runs (dependency
install, credential validation, revision gate, preflight), nothing ever
updates the row and the operator app shows "Queued" forever.

This script runs from an ``if: failure() || cancelled()`` workflow step
(``timeout-minutes`` and manual cancellation report ``cancelled``, not failure). It is deliberately
stdlib-only (the failed step may have been ``pip install``) and it only
touches a row that is still non-terminal, so a specific error already written
by the tracked entry point is never overwritten. It is best-effort: it always
exits 0 so it cannot mask the original failure.
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

TERMINAL_STATUSES = {
    "delivery_runs": ("succeeded", "failed", "dispatch_failed"),
    "pipeline_runs": ("succeeded", "failed", "no_input", "no_reviewable_drafts", "dispatch_failed"),
}


def build_request(
    *, table: str, run_id: str, supabase_url: str, service_key: str,
    github_run_id: str, github_run_url: str, now: str, job_status: str = "",
) -> urllib.request.Request:
    terminal = ",".join(TERMINAL_STATUSES[table])
    query = urllib.parse.urlencode({"id": f"eq.{run_id}", "status": f"not.in.({terminal})"})
    body: dict[str, object] = {
        "status": "failed",
        "stage": "failed",
        "error": (
            f"GitHub workflow {job_status or 'failed'} before the tracked step recorded a result"
            + (f": {github_run_url}" if github_run_url else "")
        ),
        "finished_at": now,
        "updated_at": now,
    }
    if github_run_id.isdigit():
        body["github_run_id"] = int(github_run_id)  # bigint column
    if github_run_url:
        body["github_run_url"] = github_run_url
    return urllib.request.Request(
        f"{supabase_url.rstrip('/')}/rest/v1/{table}?{query}",
        data=json.dumps(body).encode("utf-8"),
        method="PATCH",
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", required=True, choices=sorted(TERMINAL_STATUSES))
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)

    run_id = args.run_id.strip()
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not run_id:
        print(f"finalize: no {args.table} id for this workflow run; nothing to finalize")
        return 0
    if not supabase_url or not service_key:
        print("finalize: SUPABASE_URL / SUPABASE_SERVICE_KEY missing; cannot finalize", file=sys.stderr)
        return 0

    server = os.getenv("GITHUB_SERVER_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    gh_run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    gh_run_url = f"{server}/{repo}/actions/runs/{gh_run_id}" if server and repo and gh_run_id else ""
    request = build_request(
        table=args.table, run_id=run_id, supabase_url=supabase_url, service_key=service_key,
        github_run_id=gh_run_id, github_run_url=gh_run_url,
        now=datetime.now(timezone.utc).isoformat(),
        # GitHub's job.status: "failure" or "cancelled" (timeout-minutes also reports cancelled).
        job_status={"failure": "failed", "cancelled": "was cancelled or timed out"}.get(
            os.getenv("JOB_STATUS", "").strip(), ""),
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            rows = json.loads(response.read().decode("utf-8") or "[]")
    except (urllib.error.URLError, ValueError) as exc:
        print(f"finalize: could not update {args.table} {run_id}: {exc}", file=sys.stderr)
        return 0
    if rows:
        print(f"finalize: marked {args.table} {run_id} failed (workflow died before tracked result)")
    else:
        print(f"finalize: {args.table} {run_id} already terminal or absent; left unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
