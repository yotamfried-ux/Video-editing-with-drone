#!/usr/bin/env python3
"""CI/test uploads must never attach to an existing production-ready batch.

Layers: (1) the operator app never adopts a restored ready batch as an upload target,
(2) the database seals ready/failed/running/completed/cancelled batches against new
source rows and reservations, (3) UPL-01 evidence refuses a row that landed in a batch
that existed before the run. The Postgres behavioural proof lives in
supabase/tests/upload_batch_removed_sources.sql (run by the upload-batch DB workflow).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_app_never_adopts_restored_ready_batch_as_upload_target() -> None:
    src = read("mobile/src/app/(operator)/pipeline.tsx")
    block = src[src.index("const restoreReadyServerBatch"):src.index("useEffect(() => {\n    void restoreReadyServerBatch()")]
    assert "setRestoredServerBatch({" in block
    assert "setActiveBatchId(batches[0]" not in block, "restored ready batch must not become the upload target"


def test_database_seals_non_collecting_batches() -> None:
    sql = read("supabase/migrations/20261006_seal_ready_upload_batches.sql")
    for token in (
        "before insert on public.source_uploads",
        "v_state not in ('collecting', 'uploading')",
        "if v_batch.state in ('ready', 'failed', 'running', 'completed', 'cancelled')",
        "it is sealed",
    ):
        assert token in sql, token


def test_upl01_evidence_rejects_a_preexisting_batch() -> None:
    import upl01_backend_evidence as evidence

    assert hasattr(evidence, "check_isolated_batch"), "UPL-01 evidence must prove batch isolation"
    prod = {"batch_id": "batch_prod", "created_at": "2026-10-03T12:19:52Z"}
    run_start = "2026-10-06T17:30:00Z"
    row = {"batch_id": "batch_prod"}
    assert evidence.check_isolated_batch(row, [prod], run_started_at=run_start), "must fail: attached to production batch"
    fresh = {"batch_id": "batch_ci", "created_at": "2026-10-06T17:31:00Z"}
    assert not evidence.check_isolated_batch({"batch_id": "batch_ci"}, [fresh], run_started_at=run_start)


def test_ci_cleanup_is_scoped_to_the_batch_it_created() -> None:
    import upl01_backend_evidence as evidence

    since = "2026-10-06T17:30:00Z"
    calls: list[str] = []
    orig_fetch, orig_request = evidence.fetch_batch, evidence._request
    try:
        # Production batch (created long before the run) with the CI rows inside it: never cancelled.
        evidence.fetch_batch = lambda *a, **k: [{"batch_id": "batch_prod", "created_at": "2026-10-03T12:19:52Z"}]
        evidence._request = lambda *a, **k: calls.append("request") or (200, [])
        assert evidence.cancel_ci_batch("http://x", "k", "batch_prod", since_iso=since) is False
        # CI batch that also contains an older (production) row: never cancelled.
        evidence.fetch_batch = lambda *a, **k: [{"batch_id": "b", "created_at": "2026-10-06T17:31:00Z"}]
        evidence._request = lambda *a, **k: (200, [{"id": "1", "created_at": "2026-10-03T12:19:53Z"}])
        assert evidence.cancel_ci_batch("http://x", "k", "b", since_iso=since) is False
    finally:
        evidence.fetch_batch, evidence._request = orig_fetch, orig_request


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn(); print(f"ok  {fn.__name__}")
    print(f"{len(tests)} upload batch isolation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
