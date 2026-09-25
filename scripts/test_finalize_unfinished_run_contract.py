#!/usr/bin/env python3
"""Behavioral contract for scripts/finalize_unfinished_run.py.

Runs the real script as a subprocess against an in-process stub of the
PostgREST PATCH surface that honours the ``id=eq.`` and ``status=not.in.()``
filters, so the tests prove which rows change, not only which URL is built.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/finalize_unfinished_run.py"


class _Stub:
    def __init__(self, rows: dict[str, dict]):
        self.rows = rows
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_PATCH(self):  # noqa: N802 - http.server API
                parsed = urllib.parse.urlparse(self.path)
                table = parsed.path.rsplit("/", 1)[-1]
                query = dict(urllib.parse.parse_qsl(parsed.query))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append({"table": table, "query": query, "body": body,
                                      "auth": self.headers.get("Authorization")})
                row_id = query["id"].removeprefix("eq.")
                excluded = query["status"].removeprefix("not.in.(").removesuffix(")").split(",")
                row = stub.rows.get(row_id)
                updated = []
                if row is not None and row["status"] not in excluded:
                    row.update(body)
                    updated.append(row)
                payload = json.dumps(updated).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def _run(args: list[str], env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "GITHUB_"))}
    env.update({"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
    env.update(env_extra)
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                          capture_output=True, text=True, check=False, timeout=30)


GH_ENV = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "42"}


def test_queued_delivery_row_is_marked_failed_with_run_link() -> None:
    stub = _Stub({"d1": {"id": "d1", "status": "queued", "stage": "delivery_workflow_dispatched"}})
    try:
        r = _run(["--table", "delivery_runs", "--run-id", "d1"],
                 {"SUPABASE_URL": stub.url, "SUPABASE_SERVICE_KEY": "k", **GH_ENV})
    finally:
        stub.close()
    assert r.returncode == 0, r.stderr
    row = stub.rows["d1"]
    assert row["status"] == "failed" and row["stage"] == "failed"
    assert row["finished_at"]
    assert row["github_run_id"] == 42
    assert "https://github.com/o/r/actions/runs/42" in row["error"]
    assert row["error"].startswith("GitHub workflow failed before")
    assert stub.requests[0]["auth"] == "Bearer k"
    assert "marked delivery_runs d1 failed" in r.stdout


def test_cancelled_or_timed_out_run_is_finalized_with_reason() -> None:
    stub = _Stub({"p9": {"id": "p9", "status": "running", "stage": "analyzing"}})
    try:
        r = _run(["--table", "pipeline_runs", "--run-id", "p9"],
                 {"SUPABASE_URL": stub.url, "SUPABASE_SERVICE_KEY": "k", "JOB_STATUS": "cancelled", **GH_ENV})
    finally:
        stub.close()
    assert r.returncode == 0, r.stderr
    row = stub.rows["p9"]
    assert row["status"] == "failed"
    assert row["error"].startswith("GitHub workflow was cancelled or timed out before"), row["error"]


def test_terminal_row_keeps_specific_error() -> None:
    original = {"id": "d2", "status": "failed", "stage": "failed", "error": "Discover publish failed: 22P02"}
    stub = _Stub({"d2": dict(original)})
    try:
        r = _run(["--table", "delivery_runs", "--run-id", "d2"],
                 {"SUPABASE_URL": stub.url, "SUPABASE_SERVICE_KEY": "k", **GH_ENV})
    finally:
        stub.close()
    assert r.returncode == 0
    assert stub.rows["d2"] == original
    assert "already terminal" in r.stdout


def test_pipeline_terminal_statuses_are_all_protected() -> None:
    rows = {s: {"id": s, "status": s} for s in
            ("succeeded", "failed", "no_input", "no_reviewable_drafts", "dispatch_failed")}
    rows["running"] = {"id": "running", "status": "running"}
    stub = _Stub({k: dict(v) for k, v in rows.items()})
    try:
        for row_id in rows:
            _run(["--table", "pipeline_runs", "--run-id", row_id],
                 {"SUPABASE_URL": stub.url, "SUPABASE_SERVICE_KEY": "k"})
    finally:
        stub.close()
    for row_id, row in stub.rows.items():
        expected = "failed" if row_id in ("running", "failed") else row_id
        assert row["status"] == expected, (row_id, row)
    assert "error" not in stub.rows["failed"]


def test_no_run_id_or_credentials_makes_no_request() -> None:
    stub = _Stub({})
    try:
        r1 = _run(["--table", "delivery_runs", "--run-id", ""],
                  {"SUPABASE_URL": stub.url, "SUPABASE_SERVICE_KEY": "k"})
        r2 = _run(["--table", "delivery_runs", "--run-id", "d3"], {})
    finally:
        stub.close()
    assert r1.returncode == 0 and r2.returncode == 0
    assert stub.requests == []


def test_unreachable_backend_never_masks_original_failure() -> None:
    r = _run(["--table", "pipeline_runs", "--run-id", "p1"],
             {"SUPABASE_URL": "http://127.0.0.1:9", "SUPABASE_SERVICE_KEY": "k"})
    assert r.returncode == 0
    assert "could not update" in r.stderr


def test_workflows_finalize_on_failure_after_tracked_step() -> None:
    for workflow, tracked_cmd, table in (
        (".github/workflows/deliver.yml", "python deliver.py", "delivery_runs"),
        (".github/workflows/pipeline-run.yml", None, "pipeline_runs"),
    ):
        steps = yaml.safe_load((ROOT / workflow).read_text())["jobs"]
        steps = next(iter(steps.values()))["steps"]
        names = [s.get("name", "") for s in steps]
        idx = next(i for i, s in enumerate(steps) if "finalize_unfinished_run.py" in s.get("run", ""))
        step = steps[idx]
        # Timeouts and manual cancels report cancelled(), not failure(); both must finalize.
        assert step["if"] == "failure() || cancelled()", workflow
        assert step["env"]["JOB_STATUS"] == "${{ job.status }}", workflow
        assert f"--table {table}" in step["run"]
        assert '"$TRACKED_RUN_ID"' in step["run"], "run id must come from env, not shell interpolation"
        assert "${{" not in step["run"]
        assert {"SUPABASE_URL", "SUPABASE_SERVICE_KEY", "TRACKED_RUN_ID"} <= set(step["env"])
        if tracked_cmd:
            tracked = next(i for i, s in enumerate(steps) if s.get("run", "").strip() == tracked_cmd)
            assert idx > tracked, names


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS finalize unfinished run contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
