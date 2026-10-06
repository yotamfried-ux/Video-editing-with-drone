#!/usr/bin/env python3
"""Every terminal pipeline status must release the locked upload batch."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "finalize_upload_batch.py"
RUN, BATCH = "11111111-1111-1111-1111-111111111111", "batch_x"


class Stub:
    def __init__(self, run_status, batch_state="running"):
        self.run_status, self.batch_state, self.patches = run_status, batch_state, []
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _send(self, rows):
                body = json.dumps(rows).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_GET(self):
                self._send([] if stub.run_status is None else [{"id": RUN, "status": stub.run_status}])
            def do_PATCH(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                matches = stub.batch_state == "running" and f"state=eq.running" in self.path and RUN in self.path
                stub.patches.append((self.path, payload, matches))
                if matches:
                    stub.batch_state = payload["state"]
                self._send([{"batch_id": BATCH}] if matches else [])

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def run(self):
        env = {**os.environ, "SUPABASE_URL": self.url, "SUPABASE_SERVICE_KEY": "k"}
        out = subprocess.run([sys.executable, str(SCRIPT), "--run-id", RUN, "--batch-id", BATCH],
                             env=env, capture_output=True, text=True, timeout=30)
        self.server.shutdown()
        assert out.returncode == 0, out.stderr
        return out.stdout


def test_success_completes_batch():
    s = Stub("succeeded"); s.run(); assert s.batch_state == "completed"


def test_every_failure_and_cancellation_status_releases_the_lock():
    for status in ("failed", "dispatch_failed", "no_input", "no_reviewable_drafts", "cancelled", "canceled", "timed_out"):
        s = Stub(status); s.run()
        assert s.batch_state == "failed", f"{status} left the batch {s.batch_state}"


def test_non_terminal_run_leaves_batch_running():
    for status in ("queued", "dispatching", "dispatching_reset", "running"):
        s = Stub(status); s.run()
        assert s.batch_state == "running" and not s.patches, status


def test_only_this_runs_running_batch_is_touched():
    s = Stub("failed", batch_state="ready"); s.run()
    assert s.batch_state == "ready"
    s = Stub(None); s.run(); assert not s.patches


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn(); print(f"ok  {fn.__name__}")
    print(f"{len(tests)} finalize_upload_batch checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
