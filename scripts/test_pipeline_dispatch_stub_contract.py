#!/usr/bin/env python3
"""Contract for the pipeline-dispatch stub server and its Maestro scenario (no emulator needed)."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline_dispatch_stub_server as stub  # noqa: E402


def _call(base, method, path, body=None, secret="s"):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **({"x-operator-secret": secret} if secret else {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_dispatch_lifecycle() -> None:
    stub.STATE = stub.State(duration_s=3.0)
    server = ThreadingHTTPServer(("127.0.0.1", 0), stub.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert _call(base, "POST", "/api/operator/pipeline/start-raw", {}, secret="")[0] == 401
        status, first = _call(base, "POST", "/api/operator/pipeline/start-raw", {})
        assert status == 200 and first["ok"] and first["pipeline_run_id"]
        # Duplicate and reset are both rejected while the run is active.
        for path in ("start-raw", "reset-raw"):
            code, body = _call(base, "POST", f"/api/operator/pipeline/{path}", {"full_clean": True})
            assert code == 409 and "already active" in body["error"], (path, body)
        runs = _call(base, "GET", "/api/operator/pipeline/runs")[1]["runs"]
        assert len(runs) == 1 and runs[0]["id"] == first["pipeline_run_id"]
        assert runs[0]["meta"]["mode"] == "simple_raw" and runs[0]["status"] == "queued"
        assert runs[0]["github_run_url"].endswith("pipeline-run.yml"), "generic URL until the workflow starts"
        time.sleep(stub.STARTED_AFTER_S + 0.3)
        running = _call(base, "GET", "/api/operator/pipeline/status")[1]
        assert running["latest_run"]["status"] == "running" and 0 < running["latest_run"]["progress"] < 1
        assert "/actions/runs/" in running["latest_run"]["github_run_url"], "exact run URL once started"
        time.sleep(1.2)
        done = _call(base, "GET", "/api/operator/pipeline/runs")[1]["runs"][0]
        assert (done["status"], done["stage"], done["progress"]) == ("succeeded", "finished", 1.0)
        # After it finishes a full-clean reset is accepted and recorded as such.
        code, reset = _call(base, "POST", "/api/operator/pipeline/reset-raw", {"full_clean": True})
        assert code == 200 and reset["full_clean"] is True
        newest = _call(base, "GET", "/api/operator/pipeline/runs")[1]["runs"][0]
        assert newest["id"] == reset["pipeline_run_id"] and newest["meta"]["mode"] == "reset_and_rerun"
        assert newest["meta"]["full_clean_requested"] is True
        evidence = _call(base, "GET", "/__test__/evidence")[1]
        assert evidence["accepted"] == 2 and evidence["rejected_409"] == 2
    finally:
        server.shutdown()


def test_maestro_flow_and_workflow_wiring() -> None:
    flow = (ROOT / "mobile/.maestro/pipeline-dispatch/01-run-reset-visibility.yaml").read_text()
    config, steps = flow.split("---\n", 1)
    assert yaml.safe_load(config)["appId"] == "com.sportreel.app" and yaml.safe_load(steps)
    for needle in ("pipeline-run", "pipeline-reset", "Pipeline triggered", "Reset triggered", "already active",
                   "Recent pipeline runs", "Succeeded", "Open GitHub run", "Reset & rerun"):
        assert needle in flow, needle
    runner = (ROOT / "mobile/.maestro/pipeline-dispatch/run-pipeline-dispatch.sh").read_text()
    assert "127.0.0.1:8787" in runner and "vercel" not in runner and "supabase.co" not in runner
    workflow = (ROOT / ".github/workflows/android-pipeline-dispatch-e2e.yml").read_text()
    assert "EXPO_PUBLIC_API_BASE_URL: http://127.0.0.1:8787" in workflow
    assert "pipeline_dispatch_stub_server.py" in workflow and "vercel.app" not in workflow.split("jobs:", 1)[1].split("pipeline-dispatch-e2e:")[1]
    screen = (ROOT / "mobile/src/app/(operator)/pipeline.tsx").read_text()
    assert 'testID="pipeline-reset"' in screen and 'testID="pipeline-run"' in screen


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS pipeline dispatch stub contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
