#!/usr/bin/env python3
"""Contract test for upstream single-athlete event selection policy."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    policy = (ROOT / "pipeline" / "single_athlete_selection_policy.py").read_text(encoding="utf-8")
    sitecustomize = (ROOT / "scripts" / "sitecustomize.py").read_text(encoding="utf-8")

    required_policy_tokens = [
        "SINGLE-ATHLETE SELECTION POLICY",
        "shared-wave",
        "same-window multi-person",
        "clean sub-window",
        "at least 6 continuous seconds",
        "If no clean single-athlete sub-window of at least 6 seconds exists, do not return the event at all",
        "subject_isolation",
        "_BAD_DESCRIPTION_PATTERNS",
        "shares a wave",
        "partially obstructed",
        "another rider",
        "_BAD_ISOLATION_VALUES",
        "shared_wave",
        "same_window_multi_person",
        "_rewrite_to_clean_subwindow",
        "clean_end - clean_start < 6.0",
        "rewrite_raw_selection_json",
        "json.loads(text)",
        "person[\"events\"] = clean_events",
        "parse_with_single_athlete_policy",
        "analyzer._parse_session = parse_with_single_athlete_policy",
    ]
    missing = [token for token in required_policy_tokens if token not in policy]
    if missing:
        raise AssertionError(f"single-athlete selection policy missing tokens: {missing}")

    required_sitecustomize_tokens = [
        "def _install_single_athlete_selection_policy()",
        "from pipeline.single_athlete_selection_policy import install",
        "_install_single_athlete_selection_policy()",
    ]
    missing_sitecustomize = [token for token in required_sitecustomize_tokens if token not in sitecustomize]
    if missing_sitecustomize:
        raise AssertionError(f"sitecustomize does not install policy: {missing_sitecustomize}")

    print("single-athlete selection policy contract ok")


if __name__ == "__main__":
    main()
