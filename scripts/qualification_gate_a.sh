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
phase() {  # name run_id fault [ledger 1|0] [description-suffix] [draft-date]
  local name="$1" rid="$2" fault="$3" ledger="${4:-1}" suffix="${5:-}" day="${6:-}" tmp="/tmp/gate-a-run/$1"
  rm -rf "$tmp"; mkdir -p "$tmp/pipeline-debug"
  echo "::group::phase $name (namespace $rid, fault=${fault:-none}, ledger=$ledger, suffix=${suffix:-none}, date=${day:-today})"
  TMP_DIR="$tmp" SPORTREEL_QUALIFICATION_RUN_ID="$rid" SPORTREEL_QUALIFICATION_FAULT="$fault" \
    SPORTREEL_DRAFT_LEDGER="$ledger" SPORTREEL_QUALIFICATION_DESCRIPTION_SUFFIX="$suffix" SPORTREEL_QUALIFICATION_DRAFT_DATE="$day" \
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
if [ "${GATE_A_SUITE:-cycle10}" = "pa13" ]; then
  # Cycle 12 PA-13: crash after the first draft upload, then a retry that proposes different draft names (another
  # model description + another day). RED leg: legacy names (ledger off) in its own namespace. GREEN leg: ledger on.
  NSL="${NS}-legacy"
  python scripts/qualification_run.py seed --run-id "$NSL" --batch "$BATCH" && python scripts/qualification_run.py seed-check --run-id "$NSL" --batch "$BATCH"
  mkdir -p /tmp/gate-a-run/seedL; inv seedL "$NSL" 0 /tmp/gate-a-run/seedL
  phase L1 "$NSL" after_first_upload 0
  phase L2 "$NSL" "" 0 "retry-description" 20991231
  phase G1 "$NS" after_first_upload 1
  phase G2 "$NS" "" 1 "retry-description" 20991231
  phase G3 "$NS" "" 1 "retry-description" 20991231
  exit 0
fi
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
