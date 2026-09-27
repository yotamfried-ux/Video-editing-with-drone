#!/usr/bin/env bash
# Run local-only API fault scenarios on one isolated Android emulator.
set -euo pipefail

export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true

FLOWS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="$FLOWS/media/upl01-fixture.mp4"
mkdir -p "$EVIDENCE_DIR"

for var in APK EVIDENCE_DIR APP_ID; do
  test -n "${!var:-}" || { echo "UPL-01 fault runner: required env $var is empty" >&2; exit 2; }
done
test -s "$FIXTURE" || { echo "UPL-01 fault runner: missing fixture $FIXTURE" >&2; exit 2; }

MAESTRO_OPERATOR_SECRET="${MAESTRO_OPERATOR_SECRET:-upl01-local-fault-fixture-secret}"
export MAESTRO_OPERATOR_SECRET

collect_device_state() {
  local label="${1:-final}"
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/${label}-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/${label}-screen.png" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/${label}-logcat.txt" 2>/dev/null
  set -e
}

stabilize_adb_device() {
  local phase="$1" attempt stable
  echo "UPL-01 fault runner: stabilizing Android device before $phase"
  adb start-server >/dev/null 2>&1 || true
  for attempt in 1 2 3 4 5 6; do
    stable=1
    for _ in 1 2 3; do
      if [ "$(adb get-state 2>/dev/null || true)" != "device" ] ||          [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; then
        stable=0
        break
      fi
      adb shell true >/dev/null 2>&1 || { stable=0; break; }
      sleep 2
    done
    if [ "$stable" -eq 1 ]; then
      echo "UPL-01 fault runner: Android device stable before $phase"
      return 0
    fi
    echo "UPL-01 fault runner: adb unstable before $phase (attempt $attempt/6); restarting adb"
    adb kill-server >/dev/null 2>&1 || true
    sleep 2
    adb start-server >/dev/null 2>&1 || true
    adb wait-for-device || true
    sleep 4
  done
  echo "UPL-01 fault runner: Android device never became stable before $phase" >&2
  adb devices -l >&2 || true
  return 1
}

on_exit() {
  local code=$?
  if [ "$code" -ne 0 ]; then collect_device_state "failure"; fi
  exit "$code"
}
trap on_exit EXIT

stabilize_adb_device "APK install"
adb reverse tcp:8081 tcp:8081
adb reverse tcp:9090 tcp:9090
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

set_mode() {
  local mode="$1"
  curl -fsS -X POST http://127.0.0.1:9090/control     -H 'content-type: application/json'     --data-binary "{\"mode\":\"$mode\"}"     > "$EVIDENCE_DIR/${mode}-control.json"
}

save_stats() {
  local mode="$1"
  curl -fsS http://127.0.0.1:9090/stats > "$EVIDENCE_DIR/${mode}-stats.json"
}

assert_stats() {
  local mode="$1" expectation="$2"
  python3 - "$EVIDENCE_DIR/${mode}-stats.json" "$mode" "$expectation" <<'PY'
import json, pathlib, sys
path, mode, expectation = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
stats = json.loads(path.read_text())
if stats.get("mode") != mode:
    raise SystemExit(f"{mode}: stats mode mismatch: {stats}")
if expectation == "fail-fast":
    expected = {"upload_init": 1, "put": 0, "verify": 0, "uploaded_bytes": 0}
    for key, value in expected.items():
        if stats.get(key) != value:
            raise SystemExit(f"{mode}: expected {key}={value}, got {stats.get(key)}: {stats}")
elif expectation == "recovered":
    expected = {"upload_init": 3, "put": 1, "verify": 1}
    for key, value in expected.items():
        if stats.get(key) != value:
            raise SystemExit(f"{mode}: expected {key}={value}, got {stats.get(key)}: {stats}")
    if int(stats.get("uploaded_bytes") or 0) <= 0:
        raise SystemExit(f"{mode}: local PUT uploaded no bytes: {stats}")
else:
    raise SystemExit(f"unknown stats expectation {expectation}")
print(f"{mode}: local fault evidence PASS {stats}")
PY
}

run_fault() {
  local mode="$1" flow="$2" expectation="$3" expected_status="${4:-}"
  local debug="$EVIDENCE_DIR/${mode}-maestro"
  echo "::group::UPL-01 local fault / $mode"
  set_mode "$mode"
  stabilize_adb_device "$mode Maestro"
  adb reverse tcp:8081 tcp:8081
  adb reverse tcp:9090 tcp:9090

  local -a env_args=(-e MAESTRO_OPERATOR_SECRET="$MAESTRO_OPERATOR_SECRET")
  if [ -n "$expected_status" ]; then
    env_args+=(-e FAULT_EXPECTED_STATUS="$expected_status")
  fi

  timeout --signal=TERM --kill-after=30s 240s maestro test     "${env_args[@]}"     "$FLOWS/$flow"     --format junit --output "$EVIDENCE_DIR/${mode}.junit.xml"     --debug-output "$debug"     --test-output-dir "$debug"     --flatten-debug-output
  save_stats "$mode"
  assert_stats "$mode" "$expectation"
  echo "::endgroup::"
}

run_fault "api-401" "15-isolated-api-fail-fast.yaml" "fail-fast" "401"
run_fault "api-403" "15-isolated-api-fail-fast.yaml" "fail-fast" "403"
run_fault "api-429-recovery" "16-isolated-api-transient-recovery.yaml" "recovered"
run_fault "api-503-recovery" "16-isolated-api-transient-recovery.yaml" "recovered"
run_fault "api-timeout-recovery" "16-isolated-api-transient-recovery.yaml" "recovered"

collect_device_state "final"
echo "UPL-01 local API fault qualification: PASS"
