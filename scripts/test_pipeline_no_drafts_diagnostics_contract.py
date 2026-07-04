#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def validate_orchestrator_has_specific_no_draft_failures() -> None:
    orchestrator = _read("pipeline/orchestrator.py")
    required = [
        "NoDraftsProducedError",
        "DraftUploadError",
        "_NO_DRAFT_REASON",
        "reason=\"upload_failed\"",
        "reason=\"no_persons_detected\"",
        "reason=\"no_clips_analyzed\"",
        "reason=\"no_person_clusters\"",
        "reason=\"no_reels_compiled\"",
        "no_drafts_reason",
        "raise NoDraftsProducedError",
    ]
    missing = [token for token in required if token not in orchestrator]
    if missing:
        raise SystemExit(f"orchestrator is missing no-drafts diagnostic contract tokens: {missing}")


def validate_upload_failures_are_not_silently_collapsed() -> None:
    orchestrator = _read("pipeline/orchestrator.py")
    required = [
        "raise DraftUploadError",
        "Draft upload failed for",
        "reason=\"upload_failed\"",
    ]
    missing = [token for token in required if token not in orchestrator]
    if missing:
        raise SystemExit(f"upload failures can still collapse into generic no-drafts: {missing}")


def validate_tracked_error_metadata_preserves_specific_reason() -> None:
    run_tracked = _read("scripts/run_tracked.py")
    run_status = _read("integrations/run_status.py")
    required_run_tracked = [
        "error_code",
        "no_drafts_produced",
        "error=str(exc)",
    ]
    required_run_status = [
        "error: str | None = None",
        "run_fields[\"error\"] = error",
        "global_meta[\"error\"] = error",
    ]
    missing = [token for token in required_run_tracked if token not in run_tracked]
    missing += [token for token in required_run_status if token not in run_status]
    if missing:
        raise SystemExit(f"tracked terminal errors are not preserved: {missing}")


def main() -> int:
    validate_orchestrator_has_specific_no_draft_failures()
    validate_upload_failures_are_not_silently_collapsed()
    validate_tracked_error_metadata_preserves_specific_reason()
    print("Pipeline no-drafts diagnostics contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
