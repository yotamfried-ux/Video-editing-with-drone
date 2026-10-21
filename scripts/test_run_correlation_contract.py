#!/usr/bin/env python3
"""Behavioral contract for exact GitHub run correlation and reset tracking.

Runs scripts/record_run_correlation.py against an in-process PostgREST stub that honours
``id=eq.`` and ``status=eq.`` filters, and checks the workflow wiring and run_status helpers.
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
sys.path.insert(0, str(ROOT))
SCRIPT = ROOT / "scripts/record_run_correlation.py"
RUN = "11111111-1111-4111-8111-111111111111"


class _Stub:
    def __init__(self, rows):
        self.rows, self.requests = rows, []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_PATCH(self):  # noqa: N802
                query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append({"query": query, "body": body})
                row = stub.rows.get(query["id"].removeprefix("eq."))
                updated = []
                wanted = query.get("status", "").removeprefix("eq.")
                if row is not None and (not wanted or row["status"] == wanted):
                    row.update(body)
                    updated.append(row)
                payload = json.dumps(updated).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def _run(stub, *, attempt="1", run_id=RUN, gh_run="777"):
    env = {**os.environ, "CORRELATION_TIMEOUT_S": "2", "SUPABASE_URL": stub.url, "SUPABASE_SERVICE_KEY": "k",
           "GITHUB_RUN_ID": gh_run, "GITHUB_RUN_ATTEMPT": attempt,
           "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
    return subprocess.run([sys.executable, str(SCRIPT), "--run-id", run_id], env=env,
                          capture_output=True, text=True, timeout=30)


def _queued_row():
    return {"status": "queued", "stage": "workflow_dispatched", "github_run_id": None,
            "github_run_url": "https://github.com/o/r/actions/workflows/pipeline-run.yml", "error": None}


def test_first_attempt_records_exact_run_and_starts_row() -> None:
    stub = _Stub({RUN: _queued_row()})
    try:
        assert _run(stub).returncode == 0
        row = stub.rows[RUN]
        assert row["github_run_id"] == 777
        assert row["github_run_url"] == "https://github.com/o/r/actions/runs/777"
        assert (row["status"], row["stage"]) == ("running", "workflow_started")
    finally:
        stub.close()


def test_terminal_row_is_not_reopened_on_first_attempt() -> None:
    stub = _Stub({RUN: {**_queued_row(), "status": "dispatch_failed"}})
    try:
        _run(stub)
        assert stub.rows[RUN]["status"] == "dispatch_failed"
        assert stub.rows[RUN]["github_run_id"] == 777
    finally:
        stub.close()


def test_rerun_attempt_points_to_attempt_url_and_reopens_failed_row() -> None:
    stub = _Stub({RUN: {**_queued_row(), "status": "failed", "error": "old failure", "finished_at": "x"}})
    try:
        _run(stub, attempt="2")
        row = stub.rows[RUN]
        assert row["github_run_url"] == "https://github.com/o/r/actions/runs/777/attempts/2"
        assert (row["status"], row["error"], row["finished_at"]) == ("running", None, None)
    finally:
        stub.close()


def test_missing_run_id_or_context_is_a_safe_noop() -> None:
    stub = _Stub({RUN: _queued_row()})
    try:
        assert _run(stub, run_id="").returncode == 0
        assert not stub.requests
        assert _run(stub, gh_run="").returncode == 0 and not stub.requests
    finally:
        stub.close()


def test_unreachable_backend_never_fails_the_job() -> None:
    stub = _Stub({RUN: _queued_row()})
    stub.close()
    assert _run(stub).returncode == 0


def _workflow_steps():
    jobs = yaml.safe_load((ROOT / ".github/workflows/pipeline-run.yml").read_text())["jobs"]
    return next(iter(jobs.values()))["steps"]


def test_workflow_correlates_first_and_reset_step_has_supabase_env() -> None:
    steps = _workflow_steps()
    idx = next(i for i, s in enumerate(steps) if "record_run_correlation.py" in s.get("run", ""))
    install = next(i for i, s in enumerate(steps) if s.get("name") == "Install Python dependencies")
    assert idx < install, "correlation must precede dependency install so early failures are linked"
    step = steps[idx]
    assert {"SUPABASE_URL", "SUPABASE_SERVICE_KEY", "TRACKED_RUN_ID"} <= set(step["env"])
    assert "${{" not in step["run"] and '"$TRACKED_RUN_ID"' in step["run"]
    reset = next(s for s in steps if s.get("name", "").startswith("Reset"))
    assert {"SUPABASE_URL", "SUPABASE_SERVICE_KEY", "PIPELINE_RUN_ID", "FULL_CLEAN"} <= set(reset["env"]), \
        "reset verifies source provenance in Supabase; without it the step crashes (run 38914592559)"


def test_no_reviewable_drafts_is_terminal_and_meta_is_merged() -> None:
    from integrations import run_status
    assert "no_reviewable_drafts" in run_status.TERMINAL_RUN_STATUSES
    assert "finished_at" in run_status._normalized_run_fields({"status": "no_reviewable_drafts"})

    calls = {}

    class Q:
        def __init__(self, name): self.name = name
        def select(self, *_): return self
        def update(self, fields): calls["update"] = fields; return self
        def eq(self, *_): return self
        def limit(self, *_): return self
        def execute(self):
            class R: data = [{"meta": {"mode": "reset_and_rerun", "reset_requested": True, "batch_id": ""}}]
            return R()

    class Client:
        def table(self, name): return Q(name)

    import types
    fake = types.ModuleType("integrations.supabase_uploader")
    fake._supabase = lambda: Client()
    saved = sys.modules.get("integrations.supabase_uploader")
    sys.modules["integrations.supabase_uploader"] = fake
    os.environ["PIPELINE_RUN_ID"] = RUN
    try:
        run_status.mark_run_strict(stage="analyzing", meta={"files": 2})
    finally:
        os.environ.pop("PIPELINE_RUN_ID", None)
        if saved is not None:
            sys.modules["integrations.supabase_uploader"] = saved
        else:
            sys.modules.pop("integrations.supabase_uploader", None)
    assert calls["update"]["meta"] == {"mode": "reset_and_rerun", "reset_requested": True, "batch_id": "", "files": 2}


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS run correlation contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
