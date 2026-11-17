#!/usr/bin/env bash
# Cycle 10 Gate A driver (CI only, LLM budget 0). Every phase runs the PRODUCTION pipeline entry point
# (scripts/run_tracked.py) inside a qualification namespace with a FRESH TMP_DIR, as a new runner would after a crash.
set -u
NS="$1"; BATCH="$2"; OUT="${3:-/tmp/gate-a}"
mkdir -p "$OUT"
export SPORTREEL_LLM_BUDGET_USD=0 STORAGE_BACKEND=r2 RAW_BATCH_ID=''

inv() {  # phase run_id exit_code tmp
  python scripts/qualification_gate_a.py inventory --run-id "$2" --phase "$1" --exit-code "$3" --tmp "$4" --out "$OUT/$1.inventory.json"
}
phase() {  # name run_id fault
  local name="$1" rid="$2" fault="$3" tmp="/tmp/gate-a-run/$1"
  rm -rf "$tmp"; mkdir -p "$tmp/pipeline-debug"
  echo "::group::phase $name (namespace $rid, fault=${fault:-none})"
  TMP_DIR="$tmp" SPORTREEL_QUALIFICATION_RUN_ID="$rid" SPORTREEL_QUALIFICATION_FAULT="$fault" \
    PYTHONUNBUFFERED=1 timeout 7200 python -u scripts/run_tracked.py > "$tmp/pipeline-debug/run_tracked.log" 2>&1
  local code=$?
  tail -15 "$tmp/pipeline-debug/run_tracked.log"
  echo "exit code $code"
  echo "::endgroup::"
  inv "$name" "$rid" "$code" "$tmp"
  cp "$tmp/pipeline-debug/run_tracked.log" "$OUT/$name.run_tracked.log" 2>/dev/null
  cp "$tmp/pipeline-debug/qualification_ledger.jsonl" "$OUT/$name.ledger.jsonl" 2>/dev/null
  find "$tmp" -type f \( -iname '*.mp4' -o -iname '*.mov' \) -delete
}

mkdir -p /tmp/gate-a-run/seed
inv seed "$NS" 0 /tmp/gate-a-run/seed
# A1: retry into the namespace of a run that already completed (q9-dry-02, cycle 9)
mkdir -p /tmp/gate-a-run/R0-before
inv R0-before q9-dry-02 0 /tmp/gate-a-run/R0-before
phase R0 q9-dry-02 ""
# A2: deliberate hard crashes, then recovery and a second retry, all in one fresh namespace
phase F1 "$NS" after_analysis
phase F2 "$NS" before_qa
phase F3 "$NS" after_first_upload
phase R4 "$NS" ""
phase R5 "$NS" ""
