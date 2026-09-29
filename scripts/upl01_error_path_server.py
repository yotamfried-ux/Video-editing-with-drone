#!/usr/bin/env python3
"""Controlled local API for Android upload error-path qualification.

The server never touches production state. The runner switches scenarios
through /__test__/scenario and reads request counters from /__test__/evidence.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlparse


class State:
    def __init__(self) -> None:
        self.lock = Lock()
        self.scenario = "401"
        self.upload_requests = 0
        self.all_requests = 0

    def reset(self, scenario: str) -> None:
        with self.lock:
            self.scenario = scenario
            self.upload_requests = 0
            self.all_requests = 0

    def count(self, upload: bool = False) -> tuple[str, int, int]:
        with self.lock:
            self.all_requests += 1
            if upload:
                self.upload_requests += 1
            return self.scenario, self.upload_requests, self.all_requests

    def evidence(self) -> dict[str, object]:
        with self.lock:
            return {
                "scenario": self.scenario,
                "upload_requests": self.upload_requests,
                "all_requests": self.all_requests,
            }


STATE = State()


class Handler(BaseHTTPRequestHandler):
    server_version = "SportReelErrorPath/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[mock-api] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Expected when the Android client aborts the timeout scenario.
            pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/__test__/scenario":
            scenario = parse_qs(parsed.query).get("name", [""])[0]
            if scenario not in {"401", "403", "429", "503", "timeout"}:
                self._json(400, {"error": "unsupported scenario"})
                return
            STATE.reset(scenario)
            self._json(200, {"ok": True, "scenario": scenario})
            return

        if parsed.path == "/__test__/evidence":
            self._json(200, STATE.evidence())
            return

        STATE.count()
        if parsed.path == "/api/operator/pipeline/status":
            self._json(200, {"status": "idle", "latest_run": None, "global_live_stale": False})
        elif parsed.path == "/api/operator/pipeline/runs":
            self._json(200, {"runs": []})
        elif parsed.path == "/api/operator/delivery-status":
            self._json(200, {"runs": []})
        elif parsed.path == "/api/operator/reprocess":
            self._json(200, {"requests": []})
        else:
            self._json(404, {"error": "mock route not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/operator/upload":
            STATE.count()
            self._json(404, {"error": "mock route not found"})
            return

        scenario, attempt, _ = STATE.count(upload=True)
        if scenario == "timeout":
            time.sleep(2.0)
            self._json(503, {"error": f"late timeout response attempt {attempt}"})
            return

        status = int(scenario)
        self._json(status, {"error": f"qualified mock HTTP {status} attempt {attempt}"})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"UPL-01 error-path server listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
