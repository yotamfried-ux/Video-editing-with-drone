#!/usr/bin/env python3
"""Regression test for the empty approval_blocked_reasons bug found during
GAP-012 real-run validation (run 28938769332).

pipeline/multi_person_clip_gate.py attaches `defects` to a qa_gate dict but
never sets `approval_blocked_reasons` or `review_required_reasons` on it.
integrations/supabase_uploader.py must still persist non-empty
approval_blocked_reasons for a qa_blocked task by deriving reasons from the
defects themselves.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub the `supabase` pip package and the `config` package's real settings
# module so this test can run without either installed (this contract test
# intentionally stays dependency-light, matching the other
# scripts/test_*_contract.py checks run in operator-smoke-check.yml, which
# does not install requirements.txt). Stubbing `supabase` also sidesteps
# ROOT/supabase/ (the migrations directory) shadowing the real package when
# ROOT is on sys.path.
if "supabase" not in sys.modules:
    _fake_supabase_module = types.ModuleType("supabase")
    _fake_supabase_module.create_client = lambda *_a, **_k: None
    _fake_supabase_module.Client = object
    sys.modules["supabase"] = _fake_supabase_module

if "config" not in sys.modules:
    _fake_config_module = types.ModuleType("config")
    _fake_config_module.SUPABASE_URL = "http://example.invalid"
    _fake_config_module.SUPABASE_SERVICE_KEY = "test-key"
    _fake_config_module.APP_DOMAIN = "example.invalid"
    sys.modules["config"] = _fake_config_module

from integrations import supabase_uploader  # noqa: E402


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, name: str, store: dict[str, list[dict]]):
        self.name = name
        self.store = store
        self._filters: dict[str, object] = {}
        self._pending_insert = None
        self._pending_update = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self._pending_insert = payload
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def _matches(self, row: dict) -> bool:
        return all(row.get(key) == value for key, value in self._filters.items())

    def execute(self):
        if self._pending_insert is not None:
            row = dict(self._pending_insert)
            row.setdefault("id", f"row-{len(self.store[self.name]) + 1}")
            self.store[self.name].append(row)
            self._pending_insert = None
            return _Result([row])
        if self._pending_update is not None:
            for row in self.store[self.name]:
                if self._matches(row):
                    row.update(self._pending_update)
            self._pending_update = None
            return _Result([])
        rows = [row for row in self.store[self.name] if self._matches(row)]
        return _Result(rows)


class _FakeClient:
    def __init__(self):
        self.store: dict[str, list[dict]] = {"reprocess_requests": []}

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(name, self.store)


def _multi_person_gate_qa_gate() -> dict:
    """Shape produced by pipeline/multi_person_clip_gate.py::_merge_qa_gate —
    defects only, no approval_blocked_reasons/review_required_reasons keys."""
    return {
        "decision": "review_required_multi_person",
        "final_verdict": "FAIL",
        "qa_review_required": True,
        "critical_defect_count": 1,
        "overall": "multi-person source window requires operator review",
        "defects": [{
            "type": "MULTI_PERSON_CLIP",
            "severity": "critical",
            "blocking": True,
            "event_id": "event_000",
            "note": "single-athlete draft window contains another visible subject without SOCIAL_MOMENT evidence",
            "primary_subject_id": "track_id:105",
            "visible_subject_ids": ["track_id:105", "track_id:136"],
        }],
    }


def main() -> int:
    fake = _FakeClient()
    supabase_uploader._client = fake

    supabase_uploader.upsert_qa_reedit_task(
        "DRAFT_test_20260708.mp4", _multi_person_gate_qa_gate()
    )

    rows = fake.store["reprocess_requests"]
    if len(rows) != 1:
        raise SystemExit(f"expected exactly one persisted row, got {len(rows)}")

    row = rows[0]
    if row.get("status") != "qa_blocked" or row.get("origin") != "qa_gate":
        raise SystemExit(f"unexpected status/origin: {row}")

    reasons = row.get("approval_blocked_reasons")
    if not reasons:
        raise SystemExit(
            "approval_blocked_reasons must not be empty when qa_gate carries "
            "blocking defects, even if the originating gate module didn't set "
            f"approval_blocked_reasons/review_required_reasons directly (got {reasons!r})"
        )
    if "MULTI_PERSON_CLIP" not in reasons[0]:
        raise SystemExit(f"expected derived reason to reference the defect type, got {reasons!r}")

    print("QA re-edit reason fallback contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
