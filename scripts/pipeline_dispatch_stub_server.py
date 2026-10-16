#!/usr/bin/env python3
"""Controlled local operator API for the Android pipeline-dispatch Maestro scenario.

Mimics the contract of start-raw / reset-raw / status / runs (durable run row, 409 while a
run is active, exact GitHub run URL once the workflow has started, running -> succeeded
progression) so the real app UI can be exercised on an emulator. Never touches production.
The runner reads /__test__/evidence to prove what the app sent.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlparse

WORKFLOW_URL = "https://github.com/example/stub/actions/workflows/pipeline-run.yml"
STARTED_AFTER_S = 2.0


class State:
    def __init__(self, duration_s: float) -> None:
        self.lock = Lock()
        self.duration_s = duration_s
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.runs: list[dict] = []
            self.dispatches: list[dict] = []
            self.requests = 0
            self.gh_seq = 9000

    def view(self, run: dict, now: float) -> dict:
        age = now - run["created"]
        out = {k: v for k, v in run.items() if k != "created"}
        if age < STARTED_AFTER_S:
            out.update(status="queued", stage="workflow_dispatched", progress=0, github_run_url=WORKFLOW_URL, finished_at=None)
        elif age < self.duration_s:
            out.update(status="running", stage="analyzing", progress=round(min(0.9, age / self.duration_s), 4),
                       github_run_url=f"https://github.com/example/stub/actions/runs/{run['gh_id']}", finished_at=None)
        else:
            out.update(status="succeeded", stage="finished", progress=1.0,
                       github_run_url=f"https://github.com/example/stub/actions/runs/{run['gh_id']}",
                       finished_at="2026-10-16T12:00:30+00:00")
        return out

    def snapshot(self) -> list[dict]:
        now = time.monotonic()
        return [self.view(r, now) for r in reversed(self.runs)]

    def dispatch(self, kind: str, full_clean: bool) -> tuple[int, dict]:
        with self.lock:
            now = time.monotonic()
            active = [v for v in (self.view(r, now) for r in self.runs) if v["status"] in ("queued", "running")]
            record = {"kind": kind, "full_clean": full_clean, "accepted": not active}
            self.dispatches.append(record)
            if active:
                return 409, {"error": f"A pipeline run is already active ({active[0]['id'][:8]}). "
                                      "Wait for it to finish before starting another.",
                             "active_pipeline_run_id": active[0]["id"]}
            self.gh_seq += 1
            run_id = str(uuid.uuid4())
            reset = kind == "reset_and_rerun"
            self.runs.append({
                "id": run_id, "source": "manual", "created": now, "gh_id": self.gh_seq,
                "status": "queued", "stage": "dispatching", "progress": 0, "input_files": [], "output_drafts": [],
                "error": None, "queued_at": "2026-10-16T12:00:00+00:00", "started_at": None, "finished_at": None,
                "updated_at": None, "github_run_url": WORKFLOW_URL,
                "meta": {"requested_by": "operator_app", "mode": "reset_and_rerun" if reset else "simple_raw",
                         "batch_id": "", "reset_requested": reset, "full_clean_requested": reset and full_clean},
            })
            body = {"ok": True, "pipeline_run_id": run_id, "mode": kind, "github_actions_url": WORKFLOW_URL}
            if reset:
                body["full_clean"] = full_clean
            record["pipeline_run_id"] = run_id
            return 200, body

    def evidence(self) -> dict:
        with self.lock:
            return {"requests": self.requests, "dispatches": list(self.dispatches),
                    "accepted": sum(1 for d in self.dispatches if d["accepted"]),
                    "rejected_409": sum(1 for d in self.dispatches if not d["accepted"])}


STATE: State


class Handler(BaseHTTPRequestHandler):
    server_version = "SportReelDispatchStub/1.0"

    def log_message(self, fmt, *args):
        print(f"[dispatch-stub] {fmt % args}", flush=True)

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__test__/reset":
            STATE.reset()
            return self._json(200, {"ok": True})
        if path == "/__test__/evidence":
            return self._json(200, STATE.evidence())
        with STATE.lock:
            STATE.requests += 1
        if path == "/api/operator/pipeline/status":
            runs = STATE.snapshot()
            latest = runs[0] if runs else None
            status = None
            if latest:
                status = {"stage": latest["stage"], "progress": latest["progress"], "meta": {}, "updated_at": None}
            return self._json(200, {"status": status, "latest_run": latest,
                                    "global_live_stale": False, "global_live_stale_reason": None})
        if path == "/api/operator/pipeline/runs":
            return self._json(200, {"runs": STATE.snapshot()})
        if path == "/api/operator/upload/batch":
            return self._json(200, {"batches": []})
        if path == "/api/operator/delivery-status":
            return self._json(200, {"runs": []})
        if path == "/api/operator/reprocess":
            return self._json(200, {"requests": []})
        self._json(404, {"error": "mock route not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "Invalid JSON"})
        with STATE.lock:
            STATE.requests += 1
        if path not in ("/api/operator/pipeline/start-raw", "/api/operator/pipeline/reset-raw"):
            return self._json(404, {"error": "mock route not found"})
        if not self.headers.get("x-operator-secret"):
            return self._json(401, {"error": "Unauthorized"})
        if path.endswith("start-raw"):
            status, payload = STATE.dispatch("process", False)
        else:
            status, payload = STATE.dispatch("reset_and_rerun", body.get("full_clean") is True)
        self._json(status, payload)


def main() -> int:
    global STATE
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--run-duration", type=float, default=14.0, help="seconds until a stub run succeeds")
    args = parser.parse_args()
    STATE = State(args.run_duration)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"pipeline-dispatch stub listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
