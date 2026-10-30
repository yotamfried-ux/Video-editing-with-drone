#!/usr/bin/env python3
"""Export ``predictions/v1`` from a run's diagnostics (candidate ledger + EDL files). Read-only on pipeline artifacts.

usage: export_pipeline_predictions.py LEDGER_JSON EDL_DIR OUTPUT_JSON [--source-hashes FILE]
Opt-in (SPORTREEL_EXPORT_EDL=1 in the diagnostics wrapper); never fails a pipeline run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.prediction_export import build_predictions, validate_predictions  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    parser.add_argument("edl_dir")
    parser.add_argument("output")
    parser.add_argument("--source-hashes")
    args = parser.parse_args()
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8")) if Path(args.ledger).exists() else {}
    edls = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.edl_dir).glob("*.edl.json"))] if Path(args.edl_dir).is_dir() else []
    hashes = json.loads(Path(args.source_hashes).read_text(encoding="utf-8")) if args.source_hashes else None
    payload = build_predictions(ledger, edls, run_id=os.getenv("PIPELINE_RUN_ID"),
                                commit=os.getenv("SPORTREEL_COMMIT") or os.getenv("GITHUB_SHA"), source_hashes=hashes)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    problems = validate_predictions(payload)
    print(f"predictions sources={len(payload['sources'])} unresolved={len(payload['unresolved'])} problems={problems}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
