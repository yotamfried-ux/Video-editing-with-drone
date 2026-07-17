#!/usr/bin/env python3
"""Return success only for a valid zero-athlete publishable manifest."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def is_empty_manifest(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(payload, dict):
        return False
    athletes = payload.get("athletes")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    try:
        eligible_count = int(summary.get("eligible_athlete_count") or 0)
    except (TypeError, ValueError):
        return False
    return isinstance(athletes, list) and not athletes and eligible_count == 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_publishable_manifest_empty.py MANIFEST_JSON", file=sys.stderr)
        return 2
    return 0 if is_empty_manifest(Path(sys.argv[1])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
