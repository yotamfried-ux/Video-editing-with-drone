#!/usr/bin/env python3
"""Concurrent consensus calls change latency only, never the verdict, pair order or fail-closed behaviour."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import _consensus_fixture as fx  # noqa: E402
from pipeline import identity_pair_consensus as c  # noqa: E402


def _run(workers: str, ask, n: int = 4):
    os.environ["SPORTREEL_CONSENSUS_WORKERS"] = workers
    try:
        thumb = str(ROOT / "scripts" / "test_consensus_concurrency_contract.py")
        apps = [{"path": f"s{i}.mp4", "thumbnail": thumb, "_sheet_crops": 6, "events": []} for i in range(n)]
        return c.verify_cluster({"appearances": apps}, ask)
    finally:
        os.environ.pop("SPORTREEL_CONSENSUS_WORKERS", None)


def test_same_result_serial_and_concurrent() -> None:
    serial = _run("1", lambda p, i: fx.MATCH_SPECIFIC)
    conc = _run("4", lambda p, i: fx.MATCH_SPECIFIC)
    assert serial == conc and serial["verdict"] == "MATCH" and len(serial["pairs"]) == 6, (serial, conc)
    assert [(p["a"], p["b"]) for p in serial["pairs"]] == [(p["a"], p["b"]) for p in conc["pairs"]]


def test_calls_really_overlap_and_are_faster() -> None:
    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow(prompt, images):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return fx.MATCH_SPECIFIC

    t0 = time.time(); _run("1", slow); serial_t = time.time() - t0
    assert state["peak"] == 1, state
    t0 = time.time(); _run("4", slow); conc_t = time.time() - t0
    assert state["peak"] > 1 and conc_t < serial_t * 0.6, (state, serial_t, conc_t)


def test_error_or_disagreement_in_any_call_is_still_not_a_match() -> None:
    def flaky(prompt, images):
        if threading.current_thread() is not threading.main_thread() and not hasattr(flaky, "hit"):
            flaky.hit = True
            raise RuntimeError("boom")
        return fx.MATCH_SPECIFIC

    for w in ("1", "4"):
        flaky.__dict__.pop("hit", None)
        if w == "1":
            calls = {"n": 0}

            def ask(prompt, images, calls=calls):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise RuntimeError("boom")
                return fx.MATCH_SPECIFIC
        else:
            ask = flaky
        assert _run(w, ask)["verdict"] == "REVIEW", w


def test_workers_env_is_bounded() -> None:
    for raw, want in (("0", 1), ("-3", 1), ("99", 16), ("x", 4), ("2", 2)):
        os.environ["SPORTREEL_CONSENSUS_WORKERS"] = raw
        try:
            assert c.workers() == want, (raw, c.workers())
        finally:
            os.environ.pop("SPORTREEL_CONSENSUS_WORKERS", None)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t(); print(f"PASS {t.__name__}")
    print(f"PASS consensus concurrency contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
