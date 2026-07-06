#!/usr/bin/env bash
set +euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="${TMP_DIR:-/tmp/dtor}"
DEBUG_DIR="$TMP_ROOT/pipeline-debug"
LOG_FILE="$DEBUG_DIR/run_tracked.log"
REEL_METADATA_FILE="${REEL_METADATA_FILE:-reels_metadata.json}"
DRAFT_TRACE_FILE="$TMP_ROOT/draft_decision_trace.json"
CANDIDATE_LEDGER_FILE="$TMP_ROOT/candidate_decision_ledger.json"
RUN_QUALITY_REPORT_FILE="$DEBUG_DIR/run_quality_report.json"

mkdir -p "$DEBUG_DIR" "$DEBUG_DIR/sidecars"
cd "$ROOT_DIR" || exit 98

python scripts/run_tracked.py 2>&1 | tee "$LOG_FILE"
STATUS=${PIPESTATUS[0]}

python scripts/build_draft_decision_trace.py "$REEL_METADATA_FILE" "$LOG_FILE" "$DRAFT_TRACE_FILE" || true
if [ -f "$DRAFT_TRACE_FILE" ]; then
  cp "$DRAFT_TRACE_FILE" "$DEBUG_DIR/draft_decision_trace.json" || true
  python scripts/build_candidate_decision_ledger.py "$DRAFT_TRACE_FILE" "$CANDIDATE_LEDGER_FILE" || true
fi
if [ -f "$CANDIDATE_LEDGER_FILE" ]; then
  cp "$CANDIDATE_LEDGER_FILE" "$DEBUG_DIR/candidate_decision_ledger.json" || true
fi

python - "$DEBUG_DIR" "$TMP_ROOT" "$STATUS" <<'PY'
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

out = Path(sys.argv[1])
tmp = Path(sys.argv[2])
status = int(sys.argv[3])
sidecar_out = out / "sidecars"
sidecar_out.mkdir(parents=True, exist_ok=True)
files = []
sidecars = []
if tmp.exists():
    for path in sorted(tmp.rglob("*")):
        if path.is_file() and "pipeline-debug" not in path.parts:
            rel = str(path.relative_to(tmp))
            files.append({"path": rel, "size_bytes": path.stat().st_size})
            if path.name.endswith(".perception.json"):
                sidecars.append(rel)
                try:
                    shutil.copy2(path, sidecar_out / path.name)
                except OSError:
                    pass
summary = {
    "exit_code": status,
    "tmp_dir": str(tmp),
    "file_count": len(files),
    "sidecar_count": len(sidecars),
    "sidecars": sidecars,
    "files": files[:1000],
}
(out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
PY

python scripts/generate_run_quality_report.py "$DEBUG_DIR" "$TMP_ROOT" "$STATUS" || true
python scripts/append_qa_gate_summary_to_report.py "$RUN_QUALITY_REPORT_FILE" "$LOG_FILE" || true

exit "$STATUS"
