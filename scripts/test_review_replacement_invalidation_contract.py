#!/usr/bin/env python3
"""A REVIEW object that is overwritten (re-edit / re-render under the same key) must lose its old PASS authority
BEFORE the new bytes are written, so the approval API can never approve bytes that final QA has not graded.

Existing approval flow, UI and routes are untouched: this only closes the window in which the previous run's
`draft_publishability` row (publishable / PASS) still described a replaced R2 object.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

KEY = "review/athlete_reel_part1.mp4"

import types  # noqa: E402

_stub = types.ModuleType("supabase")
_stub.create_client = lambda *a, **k: None
_stub.Client = object
sys.modules["supabase"] = _stub


class _Query:
    def __init__(self, log, table):
        self.log, self.table, self.payload, self.filters = log, table, None, []

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def execute(self):
        self.log.append(("db", self.table, dict(self.payload or {}), list(self.filters)))
        return type("R", (), {"data": []})()


class _Supabase:
    def __init__(self, log):
        self.log = log

    def table(self, name):
        return _Query(self.log, name)


def _run(db_fails=False):
    import integrations.r2_storage as r2
    import integrations.supabase_uploader as su

    log = []
    saved = (su._supabase, r2.upload_object)
    if db_fails:
        def boom():
            raise RuntimeError("supabase down")
        su._supabase = boom
    else:
        su._supabase = lambda: _Supabase(log)
    r2.upload_object = lambda path, key, ct=None: log.append(("upload", key)) or key
    try:
        try:
            r2.upload_draft("/tmp/x.mp4", "athlete_reel_part1.mp4")
            error = None
        except Exception as exc:  # noqa: BLE001
            error = exc
    finally:
        su._supabase, r2.upload_object = saved
    return log, error


def test_old_authority_is_revoked_before_new_bytes_are_written() -> None:
    log, error = _run()
    assert error is None, error
    kinds = [entry[0] for entry in log]
    assert kinds == ["db", "upload"], log                      # revoke first, then write
    _, table, payload, filters = log[0]
    assert table == "draft_publishability" and ("storage_object_id", KEY) in filters, log[0]
    assert payload["publishable"] is False and payload["qa_evidence_recorded"] is False, payload
    assert payload["qa_passed"] is False and payload["qa_verdict"] is None, payload
    assert payload["approval_blocked_reasons"], payload        # the Review screen shows why it is not approvable


def test_if_revocation_cannot_be_recorded_the_object_is_not_replaced() -> None:
    log, error = _run(db_fails=True)
    assert error is not None and not any(entry[0] == "upload" for entry in log), (log, error)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"PASS review replacement invalidation contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
