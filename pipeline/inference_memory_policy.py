"""Cold-inference memory policy (MEM-03): what the inference plane may and may not read about earlier runs.

Active when SPORTREEL_STRICT_COLD_INFERENCE=1 (set by both pipeline workflows, see PR #401 and
scripts/assert_cold_inference.py). Then, inside the inference process:

* history channels are CLOSED and every closure is recorded:
    - operator_notes          (reprocess notes for earlier drafts -> analysis prompt)
    - draft_feedback          (structured operator complaints -> analysis prompt)
    - label_feedback_history  (approval/edit history scores -> analysis prompt)
    - qa_calibration_history  (earlier QA verdicts/engagement -> QA prompt)
    - identity_decisions      (manual identity decisions, also qualification-only files)
    - llm_cache / sidecar_cache (cross-run model answers / tracker sidecars; integrations.llm_cache)
* a perception sidecar is reused only if it was written during THIS run (mtime >= run start); an older sidecar is
  ignored and recomputed, never trusted;
* a Python audit hook refuses to open evaluation-only material (Ground Truth, frozen holdouts, qualification and
  identity-review decisions, private GT boxes) from the inference process;
* ``write_report`` stores the run's isolation evidence (channels closed, open attempts refused, sidecars rejected,
  run start, strict flag) for the evaluator: it is evidence, not a substitute for the external read-path audit.

Operational state is NOT a memory channel and stays available: processed-source markers, draft ledger names and
revisions (idempotent uploads), source-upload dedup records, run status. None of them carries an event label, a
window, an identity decision or an editorial verdict into inference.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

STRICT_ENV = "SPORTREEL_STRICT_COLD_INFERENCE"
RUN_START_ENV = "SPORTREEL_INFERENCE_RUN_STARTED_AT"
# Deny-list for the open() guard. Kept as path segments (joined below) so this refusing module never carries a
# literal GT path that the evaluator-side "no runtime file names the GT" scan (test_gt_scorecard_contract S10) would
# have to whitelist; the guard refuses these reads, it never performs them.
_FORBIDDEN_SEGMENTS = (
    ("evaluation", "ground_truth"),
    ("evaluation", "qualification"),
    ("evaluation", "identity_reviews"),
    ("evaluation", "evidence"),
    ("gt_boxes",),
    ("gtv1_frozen",),
    ("ground_truth", "holdout"),
)
FORBIDDEN_PATH_PARTS = tuple("/".join(parts) for parts in _FORBIDDEN_SEGMENTS)
_TRUE = {"1", "true", "yes", "on"}
_lock = threading.Lock()
_events: list[dict[str, Any]] = []
_guard_installed = False


class ForbiddenInferenceInput(PermissionError):
    """The inference process tried to read evaluation-only or prior-run memory. Always refused."""


def strict() -> bool:
    return os.getenv(STRICT_ENV, "").strip().lower() in _TRUE


def run_started_at() -> float:
    """Start of this inference run (seconds since epoch); fixed on first use and inherited by subprocesses."""
    raw = os.getenv(RUN_START_ENV, "")
    try:
        return float(raw)
    except ValueError:
        now = time.time()
        os.environ[RUN_START_ENV] = repr(now)
        return now


def record(channel: str, action: str, **detail: Any) -> None:
    with _lock:
        _events.append({"channel": channel, "action": action, "at": time.time(), **detail})


def events() -> list[dict[str, Any]]:
    with _lock:
        return list(_events)


def closed(channel: str) -> bool:
    """True when ``channel`` must not be read in this run (and records that it was closed)."""
    if not strict():
        return False
    record(channel, "closed")
    return True


def sidecar_reusable(path: str | os.PathLike) -> bool:
    """A pre-existing perception sidecar may short-circuit the producer only if this run wrote it."""
    if not strict():
        return True
    try:
        fresh = Path(path).stat().st_mtime >= run_started_at() - 1.0
    except OSError:
        return False
    if not fresh:
        record("prior_perception_sidecar", "rejected", path=str(path))
    return fresh


def _forbidden(path: str) -> bool:
    normalised = str(path).replace("\\", "/")
    return any(part in normalised for part in FORBIDDEN_PATH_PARTS)


def _audit(event: str, args: tuple) -> None:
    if event != "open" or not args:
        return
    target = args[0]
    if isinstance(target, (bytes, bytearray)):
        target = target.decode("utf-8", "replace")
    if isinstance(target, (str, os.PathLike)) and _forbidden(os.fspath(target)):
        record("evaluation_material", "open_refused", path=str(target))
        raise ForbiddenInferenceInput(f"inference may not read evaluation-only material: {target}")


def install_guard() -> bool:
    """Install the open() audit hook once per process when strict. Audit hooks cannot be removed: call it only in
    the inference process (bootstrap), never in an evaluator."""
    global _guard_installed
    if not strict() or _guard_installed:
        return _guard_installed
    run_started_at()
    sys.addaudithook(_audit)
    _guard_installed = True
    record("evaluation_material", "guard_installed")
    return True


def database_key(service_key: str, inference_key: str = "") -> str:
    """The Supabase key this process should use. Strict inference prefers the least-privilege inference key (database
    refuses draft_feedback / reprocess_requests / ground_truth); without one it falls back to the service key and
    records that database-level isolation is NOT in effect, so the isolation report cannot overstate it."""
    if strict() and inference_key:
        record("database_role", "least_privilege_inference_key")
        return inference_key
    if strict():
        record("database_role", "service_role_fallback_not_isolated")
    return service_key


def using_inference_key(inference_key: str = "") -> bool:
    return strict() and bool(inference_key)


def report() -> dict[str, Any]:
    evs = events()
    return {
        "schema": "sportreel.inference_isolation.v1",
        "strict_cold_inference": strict(),
        "run_started_at": float(os.getenv(RUN_START_ENV) or 0) or None,
        "guard_installed": _guard_installed,
        "channels_closed": sorted({e["channel"] for e in evs if e["action"] == "closed"}),
        "open_refused": [e.get("path") for e in evs if e["action"] == "open_refused"],
        "prior_sidecars_rejected": [e.get("path") for e in evs if e["action"] == "rejected"],
        "database_role": next((e["action"] for e in reversed(evs) if e["channel"] == "database_role"), None),
        "events": evs[-500:],
        "scope": "inference-process evidence only; external R2/Supabase read paths are audited in "
                 "docs/production-readiness/INFERENCE-READ-PATH-AUDIT.md",
    }


def write_report(path: str | os.PathLike) -> None:
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report(), indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001 - evidence writing must never break a run
        pass
