#!/usr/bin/env python3
"""Controlled stub of /api/operator/storage/clean for UI failure-safety scenarios. Never touches production."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlparse

LOCK = Lock()
STATE = {"scenario": "failed-then-unverified-then-ok", "posts": 0, "confirmed_starts": 0}
INV = {"r2_video_objects": 0, "r2_video_bytes": 0, "r2_video_by_prefix": {}, "r2_non_video_objects": 2,
       "r2_unscoped_video_objects": 0, "r2_incomplete_multipart": 0, "supabase_reels_videos": 0,
       "supabase_reels_non_video": 0, "protected_bucket_counts": {}, "total_removable": 0}
ACTIVE = {"source_uploads_active": 0, "upload_batches_active": 0, "reprocess_requests_active": 0, "reels_active": 0,
          "live_pipeline_runs": 0, "live_running_batches": 0, "paid_reels": 0}


def run(status: str, **kw):
    base = {"run_id": "11111111-1111-4111-8111-111111111111", "status": status, "phase": status,
            "progress": {"initial_total": 4, "deleted": 2, "remaining": 2 if status == "running" else 0},
            "totals": {"r2_deleted": 2, "multipart_aborted": 0, "reels_removed": 0}, "before": INV, "after": None,
            "active_state_before": ACTIVE, "active_state_after": None, "neutralized": None, "failures": [], "error": None,
            "message": ""}
    base.update(kw)
    return base


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/__test__/scenario":
            with LOCK:
                STATE.update(scenario=parse_qs(u.query)["name"][0], posts=0, confirmed_starts=0)
            return self._send(200, STATE)
        if u.path == "/__test__/evidence":
            return self._send(200, STATE)
        if u.path == "/api/operator/storage/clean":
            return self._send(200, {"inventory": {**INV, "r2_video_objects": 3, "total_removable": 3}, "active_state": ACTIVE, "latest_run": None})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path != "/api/operator/storage/clean":
            return self._send(404, {"error": "not found"})
        with LOCK:
            STATE["posts"] += 1
            if "confirmation" in body:
                STATE["confirmed_starts"] += 1
            sc, starts = STATE["scenario"], STATE["confirmed_starts"]
        if sc == "failed-then-unverified-then-ok":
            if starts == 1:
                return self._send(200, run("failed", failures=["1 R2 video object(s) remain"], error="verification failed: 1 R2 video object(s) remain"))
            if starts == 2:  # claims success with no verification evidence
                return self._send(200, run("succeeded", after=None))
            return self._send(200, run("succeeded", after=INV, active_state_after=ACTIVE))
        if sc == "interrupted":
            if "confirmation" in body:
                return self._send(200, run("running"))
            if STATE["posts"] == 2:
                self.connection.close()  # connection dies mid-run
                return None
            return self._send(200, run("succeeded", after=INV, active_state_after=ACTIVE))
        self._send(500, {"error": "unknown scenario"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
