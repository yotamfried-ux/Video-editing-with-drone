#!/usr/bin/env python3
"""Small marker test that keeps storage preflight PRs inside Operator Smoke Check paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    assert (ROOT / "scripts/check_storage_access.py").exists()
    assert (ROOT / ".github/workflows/pipeline-run.yml").exists()
    assert (ROOT / "scripts/reset_and_rerun.py").exists()
    print("Storage preflight marker checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
