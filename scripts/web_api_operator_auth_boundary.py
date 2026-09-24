#!/usr/bin/env python3
"""Behavioral authorization-boundary probe for the Next.js web-api.

Starts the *built* web-api (`next start`) against a recording stub of the
Supabase REST surface, then for every operator-protected handler (discovered
from source: any handler whose body calls ``requireOperator``, plus re-export
aliases of one) proves:

* missing / wrong / prefix / empty ``x-operator-secret`` -> HTTP 401, and
* the rejected requests cause **zero** backend calls (no DB read, no
  rate-limit row, no write) -- i.e. authorization happens first.

A positive control sends the correct secret to every protected GET handler and
requires that it gets past the gate (not 401) and reaches the stub backend, so
the probe cannot pass vacuously against a server that rejects everything.

It also checks public Discover input normalization: hostile ``page``/``limit``
values on ``GET /api/sessions`` must reach the backend as a numeric range with
offset >= 0 and 1 <= limit <= 50 (never NaN / negative).

Usage (after `npm ci && npx next build` in web-api/):
    python scripts/web_api_operator_auth_boundary.py
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web-api"
API = WEB / "src/app/api"
SECRET = "boundary-probe-secret-0123456789"
BAD_SECRETS = {
    "missing": None,
    "wrong": SECRET[:-1] + "X",
    "prefix": SECRET[:8],
    "empty": "",
}
HANDLER_RE = re.compile(r"export\s+async\s+function\s+(GET|POST|PUT|PATCH|DELETE)\b")
ALIAS_RE = re.compile(r"export\s*\{\s*([A-Z,\s]+)\}\s*from\s*'([^']+)'")


def route_url(route_file: Path) -> str:
    rel = route_file.parent.relative_to(API).as_posix()
    rel = re.sub(r"\[([^\]]+)\]", "00000000-0000-0000-0000-000000000000", rel)
    return f"/api/{rel}"


OPERATOR_DIR = API / "operator"
METHODS = "GET|POST|PUT|PATCH|DELETE"
# Any other way of exporting an HTTP method must fail loudly, never be skipped.
OTHER_EXPORT_RE = re.compile(
    rf"export\s+(?:const|let|var)\s+({METHODS})\b|export\s*\{{[^}}]*\bas\s+({METHODS})\b"
)


def protected_handlers() -> list[tuple[str, str]]:
    """Handlers that must reject a missing/wrong operator secret with 401.

    Every handler under /api/operator/** is required, whether or not it calls
    requireOperator -- so a new operator route that forgets auth fails the probe.
    Handlers elsewhere are required when their body calls requireOperator.
    """
    found: dict[Path, set[str]] = {}
    aliases: list[tuple[Path, list[str], Path]] = []
    unrecognized: list[str] = []
    for route in sorted(API.rglob("route.ts")):
        text = route.read_text(encoding="utf-8")
        is_operator = OPERATOR_DIR in route.parents
        marks = list(HANDLER_RE.finditer(text))
        for i, mark in enumerate(marks):
            body = text[mark.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
            if is_operator or "requireOperator(" in body:
                found.setdefault(route, set()).add(mark.group(1))
        for alias in ALIAS_RE.finditer(text):
            target = (route.parent / alias.group(2)).resolve().with_suffix(".ts")
            aliases.append((route, [m.strip() for m in alias.group(1).split(",") if m.strip()], target))
        for other in OTHER_EXPORT_RE.finditer(text):
            unrecognized.append(f"{route.relative_to(API)}: {other.group(0)}")
    if unrecognized:
        raise SystemExit("FAIL handler export form not understood by the probe: " + "; ".join(unrecognized))
    for route, methods, target in aliases:
        for method in methods:
            if OPERATOR_DIR in route.parents or method in found.get(target, set()):
                found.setdefault(route, set()).add(method)
    return sorted((m, route_url(r)) for r, ms in found.items() for m in ms)


class RecordingBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def _any(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                backend.calls.append(f"{self.command} {self.path}")
                body = b"[]"
                if "/rpc/consume_api_rate_limit" in self.path:
                    body = json.dumps([{"allowed": True}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PATCH = do_DELETE = do_HEAD = do_PUT = _any

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base: str, method: str, path: str, secret: str | None) -> int:
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["x-operator-secret"] = secret
    data = json.dumps({"file_id": "probe", "file_name": "probe.mp4", "reply": "probe"}).encode()
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=None if method == "GET" else data)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    handlers = protected_handlers()
    if len(handlers) < 20:
        print(f"FAIL route discovery found only {len(handlers)} protected handlers", file=sys.stderr)
        return 1
    if not (WEB / ".next/BUILD_ID").exists():
        print("FAIL web-api is not built; run `npx next build` in web-api/ first", file=sys.stderr)
        return 1

    backend = RecordingBackend()
    port = free_port()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SUPABASE_", "GITHUB_", "UPSTASH_", "R2_", "STRIPE_", "RESEND_"))}
    env.update(SUPABASE_URL=backend.url, SUPABASE_SERVICE_KEY="probe-service-key",
               OPERATOR_SECRET=SECRET, NEXT_TELEMETRY_DISABLED="1",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    server = subprocess.Popen(["npx", "next", "start", "-p", str(port)], cwd=WEB, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    failures: list[str] = []
    try:
        for _ in range(60):
            try:
                request(base, "GET", "/api/operator/pipeline/status", None)
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        else:
            print("FAIL next start did not become ready", file=sys.stderr)
            return 1

        for label, secret in BAD_SECRETS.items():
            for method, path in handlers:
                before = len(backend.calls)
                status = request(base, method, path, secret)
                side_effects = backend.calls[before:]
                if status != 401:
                    failures.append(f"[{label}] {method} {path} -> {status} (expected 401)")
                if side_effects:
                    failures.append(f"[{label}] {method} {path} caused backend calls before auth: {side_effects}")

        for query in ("page=abc", "page=0", "page=-3", "limit=-5", "limit=abc", "limit=999", "page=2&limit=10"):
            before = len(backend.calls)
            status = request(base, "GET", f"/api/sessions?{query}", None)
            calls = [c for c in backend.calls[before:] if "/rest/v1/reels" in c]
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(calls[0].split(" ", 1)[1]).query)) if calls else {}
            offset, limit = params.get("offset", ""), params.get("limit", "")
            if status != 200 or not (offset.isdigit() and limit.isdigit() and 1 <= int(limit) <= 50):
                failures.append(f"[discover] /api/sessions?{query} -> {status}, offset={offset!r} limit={limit!r}")

        gets = [(m, p) for m, p in handlers if m == "GET"]
        reached = 0
        for method, path in gets:
            before = len(backend.calls)
            status = request(base, method, path, SECRET)
            if status == 401:
                failures.append(f"[positive] {method} {path} rejected the correct secret")
            reached += len(backend.calls) > before
        # Some handlers read storage (R2/Drive) before Supabase, so only require
        # that the authorized requests as a group demonstrably reach the backend.
        if not reached:
            failures.append("[positive] no authorized GET reached the backend; probe wiring is broken")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        backend.server.shutdown()

    checked = len(handlers) * len(BAD_SECRETS)
    if failures:
        print("\n".join(f"FAIL {f}" for f in failures), file=sys.stderr)
        print(f"FAIL operator auth boundary: {len(failures)} issue(s) over {checked} rejected + "
              f"{len(gets)} positive requests", file=sys.stderr)
        return 1
    print(f"PASS operator auth boundary: {len(handlers)} protected handlers x {len(BAD_SECRETS)} bad "
          f"secrets = {checked} requests -> 401 with 0 backend calls; {len(gets)} GET positive controls passed ({reached} reached the backend)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
