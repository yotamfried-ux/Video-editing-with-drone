#!/usr/bin/env python3
"""Guard SportReel's Engineering-OS execution policy entry points."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


def main() -> int:
    required = [
        "capability-registry/EXECUTION-FAST-PATH.json",
        "capability-registry/EXECUTION-TRACE.json",
        "exact Engineering-OS entry point and route key",
        "hosted-delegation ROI gate",
        "hosted subagent is never mandatory",
        "no more than five directly relevant files",
        "32 KiB text by default",
        "1,200 output tokens",
        "Documentation consistency/drift is deterministic-first",
        "shared project context",
        "PR/check-suite completion subscription",
        "do not add a timer",
        "capability-registry/CI-CONTINUATION.md",
    ]
    missing = [token for token in required if token not in CLAUDE]
    if missing:
        raise SystemExit(f"agent execution policy missing: {missing}")
    print("PASS agent execution policy contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
