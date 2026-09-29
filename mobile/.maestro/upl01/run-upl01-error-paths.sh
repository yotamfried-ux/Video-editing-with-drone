#!/usr/bin/env bash
set -euo pipefail

export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
FLOWS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLOW="$FLOWS/15-isolated-api-error.yaml"
MOCK_API="${MOCK_API:-http://127.0.0.1:8787}"
mkdir -p "$EVIDENCE_DIR"

for var in APK EVIDENCE_DIR MAESTRO_OPERATOR_SECRET; do
  test -n "${!var:-}" || { echo "UPL-01 error paths: required env $var is empty" >&2; exit 2; }
done

collect_device_state() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-maestro-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect_device_state; fi; exit "$code"' EXIT

stabilize_adb_device() {
  local phase="$1" attempt stable
  echo "UPL-01 error paths: stabilizing Android device before $phase"
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
    if [ "$stable" -eq 1 ]; then return 0; fi
    adb kill-server >/dev/null 2>&1 || true
    sleep 2
    adb start-server >/dev/null 2>&1 || true
    adb wait-for-device || true
    sleep 4
  done
  echo "UPL-01 error paths: Android device never became stable before $phase" >&2
  return 1
}

stabilize_adb_device "APK install"
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8787 tcp:8787
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

run_case() {
  local scenario="$1" expected_count="$2" expected_regex="$3"
  local case_dir="$EVIDENCE_DIR/$scenario"
  mkdir -p "$case_dir"

  for attempt in 1 2 3; do
    curl -fsS "$MOCK_API/__test__/scenario?name=$scenario" > "$case_dir/scenario-attempt-$attempt.json"
    stabilize_adb_device "Maestro $scenario attempt $attempt"
    adb reverse tcp:8081 tcp:8081
    adb reverse tcp:8787 tcp:8787

    set +e
    maestro test "$FLOW" \
      -e MAESTRO_OPERATOR_SECRET="$MAESTRO_OPERATOR_SECRET" \
      -e ERROR_SCENARIO="$scenario" \
      -e EXPECTED_ERROR_REGEX="$expected_regex" \
      --format junit --output "$case_dir/result-attempt-$attempt.junit.xml" \
      --debug-output "$case_dir/debug-attempt-$attempt" \
      --test-output-dir "$case_dir/debug-attempt-$attempt" \
      --flatten-debug-output
    flow_code=$?
    set -e

    if [ "$flow_code" -eq 0 ]; then
      cp "$case_dir/result-attempt-$attempt.junit.xml" "$case_dir/result.junit.xml"
      break
    fi

    curl -fsS "$MOCK_API/__test__/evidence" > "$case_dir/pre-retry-server-evidence-attempt-$attempt.json"
    upload_requests="$(python3 - "$case_dir/pre-retry-server-evidence-attempt-$attempt.json" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1]))["upload_requests"]))
PY
)"
    infra_failure=0
    if grep -RqsE \
      'device offline|Device server died|DeviceServerDiedException|StatusRuntimeException: UNAVAILABLE|Pixel Launcher isn.t responding' \
      "$case_dir/debug-attempt-$attempt"; then
      infra_failure=1
    fi

    if [ "$infra_failure" -ne 1 ] || [ "$upload_requests" -ne 0 ]; then
      echo "UPL-01 error paths: refusing retry for $scenario (attempt=$attempt infra_failure=$infra_failure upload_requests=$upload_requests)" >&2
      return "$flow_code"
    fi
    if [ "$attempt" -eq 3 ]; then
      echo "UPL-01 error paths: exhausted three infrastructure-only attempts for $scenario" >&2
      return "$flow_code"
    fi

    echo "UPL-01 error paths: retrying $scenario after proven emulator failure with zero upload requests (attempt $attempt/3)"
    adb kill-server >/dev/null 2>&1 || true
    sleep 2
  done

  curl -fsS "$MOCK_API/__test__/evidence" > "$case_dir/server-evidence.json"
  python3 - "$case_dir/server-evidence.json" "$scenario" "$expected_count" <<'PY'
import json, sys
path, expected_scenario, expected_count = sys.argv[1], sys.argv[2], int(sys.argv[3])
data = json.load(open(path))
assert data["scenario"] == expected_scenario, data
assert data["upload_requests"] == expected_count, data
print(f"UPL-01 API error evidence PASS: {expected_scenario} -> {expected_count} upload request(s)")
PY
}

# Auth/client failures must fail fast. Transient errors must exhaust the
# configured three-attempt policy before the UI exposes a durable failed row.
run_case 401 1 "API 401"
run_case 403 1 "API 403"
run_case 429 3 "API 429"
run_case 503 3 "API 503"
run_case timeout 3 "API timeout"
