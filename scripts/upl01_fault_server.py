#!/usr/bin/env python3
"""Local-only HTTP fault server for Android UPL-01 qualification.

The server never talks to production. A CI runner exposes it to the emulator
with adb reverse and points EXPO_PUBLIC_API_BASE_URL at localhost.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LOCK = threading.Lock()
STATE: dict[str, Any] = {
    "mode": "api-401",
    "upload_init": 0,
    "put": 0,
    "verify": 0,
    "uploaded_bytes": 0,
}


def reset(mode: str) -> None:
    with LOCK:
        STATE.update(
            mode=mode,
            upload_init=0,
            put=0,
            verify=0,
            uploaded_bytes=0,
        )


def snapshot() -> dict[str, Any]:
    with LOCK:
        return dict(STATE)


class Handler(BaseHTTPRequestHandler):
    server_version = "SportReelFault/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[fault-server] {self.address_string()} {fmt % args}", flush=True)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or "0")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.send_header("connection", "close")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _empty_ok(self) -> None:
        self.send_response(200)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._json(200, {"ok": True})
            return
        if path == "/stats":
            self._json(200, snapshot())
            return
        if path == "/api/operator/pipeline/status":
            self._json(
                200,
                {
                    "status": None,
                    "latest_run": None,
                    "global_live_stale": False,
                    "global_live_stale_reason": None,
                },
            )
            return
        if path == "/api/operator/pipeline/runs":
            self._json(200, {"runs": []})
            return
        if path == "/api/operator/delivery-status":
            self._json(200, {"runs": []})
            return
        if path == "/api/operator/reprocess":
            self._json(200, {"requests": []})
            return
        self._json(404, {"error": f"fault stub has no GET {path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/control":
            body = self._read_json()
            mode = str(body.get("mode") or "")
            allowed = {
                "api-401",
                "api-403",
                "api-429-recovery",
                "api-503-recovery",
                "api-timeout-recovery",
            }
            if mode not in allowed:
                self._json(400, {"error": "unsupported mode"})
                return
            reset(mode)
            self._json(200, {"ok": True, "mode": mode})
            return

        if path == "/api/operator/upload":
            body = self._read_json()
            with LOCK:
                STATE["upload_init"] += 1
                attempt = int(STATE["upload_init"])
                mode = str(STATE["mode"])

            if mode == "api-401":
                self._json(401, {"error": "Unauthorized"})
                return
            if mode == "api-403":
                self._json(403, {"error": "Forbidden"})
                return
            if mode == "api-429-recovery" and attempt < 3:
                self._json(429, {"error": "Too many requests"})
                return
            if mode == "api-503-recovery" and attempt < 3:
                self._json(503, {"error": "Service unavailable"})
                return
            if mode == "api-timeout-recovery" and attempt < 3:
                # Longer than the mobile 30s deadline. ThreadingHTTPServer lets
                # the next retry arrive while the timed-out handler is sleeping.
                time.sleep(35)
                self._json(504, {"error": "late timeout fixture"})
                return

            client_upload_id = str(body.get("client_upload_id") or "fault_client_upload_0001")
            batch_id = str(body.get("batch_id") or "batch_fault_local")
            source_name = str(body.get("filename") or "fault-fixture.mp4")
            session = {
                "uploadUrl": "http://127.0.0.1:9090/upload/object",
                "upload_id": "11111111-2222-4333-8444-555555555555",
                "client_upload_id": client_upload_id,
                "upload_status": "uploading",
                "filename": "fault-fixture.mp4",
                "source_filename": source_name,
                "mimeType": str(body.get("mimeType") or "video/mp4"),
                "batch_id": batch_id,
                "storage_backend": "r2",
                "storage_key": "raw/batch_fault_local/fault-fixture.mp4",
            }
            self._json(200, {**session, "uploads": [session]})
            return

        if path == "/api/operator/upload/verify":
            self._read_json()
            with LOCK:
                STATE["verify"] += 1
            self._json(
                200,
                {
                    "ok": True,
                    "exists": True,
                    "storage_backend": "r2",
                    "storage_key": "raw/batch_fault_local/fault-fixture.mp4",
                    "size": snapshot()["uploaded_bytes"],
                    "upload_id": "11111111-2222-4333-8444-555555555555",
                    "upload_status": "verified",
                },
            )
            return

        self._json(404, {"error": f"fault stub has no POST {path}"})

    def do_PUT(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/upload/object":
            self._json(404, {"error": f"fault stub has no PUT {path}"})
            return
        length = int(self.headers.get("content-length", "0") or "0")
        remaining = length
        read = 0
        while remaining > 0:
            chunk = self.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            read += len(chunk)
            remaining -= len(chunk)
        with LOCK:
            STATE["put"] += 1
            STATE["uploaded_bytes"] += read
        self._empty_ok()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9090)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[fault-server] listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
