#!/usr/bin/env bash
set +euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="${TMP_DIR:-/tmp/dtor}"
DEBUG_DIR="$TMP_ROOT/pipeline-debug"
LOG_FILE="$DEBUG_DIR/run_tracked.log"
REEL_METADATA_FILE="${REEL_METADATA_FILE:-reels_metadata.json}"
DRAFT_TRACE_FILE="$TMP_ROOT/draft_decision_trace.json"
UPSTREAM_CANDIDATES_FILE="$TMP_ROOT/selector_candidate_events.json"
SELECTION_FILTER_EVENTS_FILE="$TMP_ROOT/selection_filter_events.json"
CANDIDATE_LEDGER_FILE="$TMP_ROOT/candidate_decision_ledger.json"
SELECTION_AUDIT_FILE="$TMP_ROOT/selection_decision_audit.json"
ATHLETE_COVERAGE_FILE="$TMP_ROOT/athlete_coverage_report.json"
PUBLISHABLE_MANIFEST_FILE="${PUBLISHABLE_REEL_MANIFEST_FILE:-$TMP_ROOT/publishable_reel_manifest.json}"
PUBLISHABLE_GATE_RESULT_FILE="$DEBUG_DIR/publishable_reel_gate_result.json"
RUN_QUALITY_REPORT_FILE="$DEBUG_DIR/run_quality_report.json"

mkdir -p "$DEBUG_DIR" "$DEBUG_DIR/sidecars"
cd "$ROOT_DIR" || exit 98

python scripts/run_tracked.py 2>&1 | tee "$LOG_FILE"
STATUS=${PIPESTATUS[0]}

python scripts/build_draft_decision_trace.py "$REEL_METADATA_FILE" "$LOG_FILE" "$DRAFT_TRACE_FILE" || true
if [ -f "$DRAFT_TRACE_FILE" ]; then
  cp "$DRAFT_TRACE_FILE" "$DEBUG_DIR/draft_decision_trace.json" || true
  if [ -f "$UPSTREAM_CANDIDATES_FILE" ]; then
    cp "$UPSTREAM_CANDIDATES_FILE" "$DEBUG_DIR/selector_candidate_events.json" || true
    python scripts/build_candidate_decision_ledger.py "$DRAFT_TRACE_FILE" "$CANDIDATE_LEDGER_FILE" "$UPSTREAM_CANDIDATES_FILE" || true
  else
    python scripts/build_candidate_decision_ledger.py "$DRAFT_TRACE_FILE" "$CANDIDATE_LEDGER_FILE" || true
  fi
fi
if [ -f "$SELECTION_FILTER_EVENTS_FILE" ]; then
  cp "$SELECTION_FILTER_EVENTS_FILE" "$DEBUG_DIR/selection_filter_events.json" || true
fi
if [ -f "$CANDIDATE_LEDGER_FILE" ]; then
  cp "$CANDIDATE_LEDGER_FILE" "$DEBUG_DIR/candidate_decision_ledger.json" || true
  if [ -f "$SELECTION_FILTER_EVENTS_FILE" ]; then
    python scripts/build_selection_decision_audit.py "$CANDIDATE_LEDGER_FILE" "$DRAFT_TRACE_FILE" "$SELECTION_AUDIT_FILE" "$LOG_FILE" "$SELECTION_FILTER_EVENTS_FILE" || true
  else
    python scripts/build_selection_decision_audit.py "$CANDIDATE_LEDGER_FILE" "$DRAFT_TRACE_FILE" "$SELECTION_AUDIT_FILE" "$LOG_FILE" || true
  fi
fi
if [ -f "$SELECTION_AUDIT_FILE" ]; then
  cp "$SELECTION_AUDIT_FILE" "$DEBUG_DIR/selection_decision_audit.json" || true
fi
if [ -f "$CANDIDATE_LEDGER_FILE" ]; then
  if [ -f "$SELECTION_AUDIT_FILE" ]; then
    python scripts/build_athlete_coverage_report.py "$CANDIDATE_LEDGER_FILE" "$ATHLETE_COVERAGE_FILE" "$SELECTION_AUDIT_FILE" || true
  else
    python scripts/build_athlete_coverage_report.py "$CANDIDATE_LEDGER_FILE" "$ATHLETE_COVERAGE_FILE" || true
  fi
fi
if [ -f "$ATHLETE_COVERAGE_FILE" ]; then
  cp "$ATHLETE_COVERAGE_FILE" "$DEBUG_DIR/athlete_coverage_report.json" || true
fi
if [ -f "$PUBLISHABLE_MANIFEST_FILE" ]; then
  cp "$PUBLISHABLE_MANIFEST_FILE" "$DEBUG_DIR/publishable_reel_manifest.json" || true
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
python scripts/append_pairwise_source_window_overlap_to_report.py "$RUN_QUALITY_REPORT_FILE" "$DRAFT_TRACE_FILE" || true
if [ -f "$CANDIDATE_LEDGER_FILE" ]; then
  python scripts/append_candidate_ledger_summary_to_report.py "$RUN_QUALITY_REPORT_FILE" "$CANDIDATE_LEDGER_FILE" || true
fi
if [ -f "$SELECTION_AUDIT_FILE" ]; then
  python scripts/append_selection_decision_audit_summary_to_report.py "$RUN_QUALITY_REPORT_FILE" "$SELECTION_AUDIT_FILE" || true
fi
if [ -f "$ATHLETE_COVERAGE_FILE" ]; then
  python scripts/append_athlete_coverage_summary_to_report.py "$RUN_QUALITY_REPORT_FILE" "$ATHLETE_COVERAGE_FILE" || true
fi
python scripts/append_qa_gate_summary_to_report.py "$RUN_QUALITY_REPORT_FILE" "$LOG_FILE" || true
python scripts/append_qa_policy_trace_summary_to_report.py "$RUN_QUALITY_REPORT_FILE" "$DRAFT_TRACE_FILE" || true
# Run last so the old coarse track-count alert cannot overwrite the explicit
# primary-actor decision after other report appenders have finished.
python scripts/append_primary_actor_subject_summary_to_report.py "$RUN_QUALITY_REPORT_FILE" "$DRAFT_TRACE_FILE" "$DEBUG_DIR/sidecars" || true

write_missing_gate_result() {
  local error_message="$1"
  python - "$PUBLISHABLE_GATE_RESULT_FILE" "$PUBLISHABLE_MANIFEST_FILE" "$ATHLETE_COVERAGE_FILE" "$error_message" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

result = Path(sys.argv[1])
result.parent.mkdir(parents=True, exist_ok=True)
result.write_text(
    json.dumps(
        {
            "schema_version": "sportreel.publishable_reel_gate_result.v1",
            "passed": False,
            "manifest_path": sys.argv[2],
            "athlete_coverage_path": sys.argv[3],
            "errors": [sys.argv[4]],
        },
        indent=2,
    ),
    encoding="utf-8",
)
PY
}

BUSINESS_GATE_STATUS=0
if [ -f "$PUBLISHABLE_MANIFEST_FILE" ] && [ -f "$ATHLETE_COVERAGE_FILE" ]; then
  python scripts/check_publishable_reel_manifest.py \
    "$PUBLISHABLE_MANIFEST_FILE" \
    "$PUBLISHABLE_GATE_RESULT_FILE" \
    "$ATHLETE_COVERAGE_FILE"
  BUSINESS_GATE_STATUS=$?
elif [ -f "$PUBLISHABLE_MANIFEST_FILE" ]; then
  # A true no-input run has no candidate/selection evidence and may legitimately
  # have an empty manifest. Any other successful run must include the athlete
  # coverage report so missing evidence cannot appear green.
  if [ ! -f "$CANDIDATE_LEDGER_FILE" ] \
     && [ ! -f "$SELECTION_FILTER_EVENTS_FILE" ] \
     && [ ! -f "$DRAFT_TRACE_FILE" ]; then
    python scripts/check_publishable_reel_manifest.py \
      "$PUBLISHABLE_MANIFEST_FILE" \
      "$PUBLISHABLE_GATE_RESULT_FILE"
    BUSINESS_GATE_STATUS=$?
  else
    write_missing_gate_result "athlete coverage report missing for a run with candidate evidence"
    if [ "$STATUS" -eq 0 ]; then
      echo "::error::athlete coverage evidence missing after a successful pipeline process"
      BUSINESS_GATE_STATUS=1
    fi
  fi
else
  write_missing_gate_result "publishable reel manifest missing"
  if [ "$STATUS" -eq 0 ]; then
    echo "::error::publishable reel manifest missing after a successful pipeline process"
    BUSINESS_GATE_STATUS=1
  fi
fi

# run_tracked.py has already written a terminal result before this post-run gate.
# When processing succeeded but the product contract failed, overwrite both the
# durable run row and the global operator signal so the app cannot show success.
if [ "$STATUS" -eq 0 ] && [ "$BUSINESS_GATE_STATUS" -ne 0 ]; then
  if ! python scripts/record_publishable_business_gate_status.py "$PUBLISHABLE_GATE_RESULT_FILE"; then
    echo "::warning::could not propagate publishable business-gate failure to operator status"
  fi
fi

# Preserve the original processing failure as the primary exit code. When the
# renderer itself succeeded, the athlete-level business gate becomes the final
# production result instead of allowing incomplete coverage to appear green.
if [ "$STATUS" -ne 0 ]; then
  exit "$STATUS"
fi
exit "$BUSINESS_GATE_STATUS"
