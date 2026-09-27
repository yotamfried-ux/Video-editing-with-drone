#!/usr/bin/env bash
set -euo pipefail
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$EVIDENCE_DIR"
for var in APK EVIDENCE_DIR OPERATOR_SECRET; do
  test -n "${!var:-}" || { echo "missing required env $var" >&2; exit 2; }
done

collect() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  for report in "$EVIDENCE_DIR"/operator-readonly-attempt-*.junit.xml; do
    test -f "$report" && cat "$report"
  done
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect; fi; exit "$code"' EXIT

stabilize_adb_device() {
  local phase="$1" attempt stable
  echo "APP E2E: stabilizing Android device before $phase"
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
      echo "APP E2E: Android device stable before $phase"
      return 0
    fi
    echo "APP E2E: adb unstable before $phase (attempt $attempt/6); restarting adb"
    adb kill-server >/dev/null 2>&1 || true
    sleep 2
    adb start-server >/dev/null 2>&1 || true
    adb wait-for-device || true
    sleep 4
  done
  echo "APP E2E: Android device never became stable before $phase" >&2
  adb devices -l >&2 || true
  return 1
}

stabilize_adb_device "APK install"
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
stabilize_adb_device "operator Maestro"

run_maestro() {
  local attempt="$1"
  local debug="$EVIDENCE_DIR/maestro-attempt-$attempt"
  timeout --signal=TERM --kill-after=30s 600s maestro test \
    -e OPERATOR_SECRET="$OPERATOR_SECRET" \
    "$HERE/02-operator-readonly.yaml" \
    --format junit --output "$EVIDENCE_DIR/operator-readonly-attempt-$attempt.junit.xml" \
    --debug-output "$debug" \
    --test-output-dir "$debug" \
    --flatten-debug-output
}

set +e
run_maestro 1
code=$?
set -e
if [ "$code" -eq 0 ]; then
  exit 0
fi

# GitHub's freshly booted emulator can briefly flap offline when Maestro first
# installs/starts its device server. Retry only that known infrastructure case.
if grep -RqsE 'device offline|Device server died|StatusRuntimeException: UNAVAILABLE' "$EVIDENCE_DIR/maestro-attempt-1"; then
  echo "Maestro attempt 1 hit known transient device-offline failure; retrying after bounded adb stabilization."
  stabilize_adb_device "operator Maestro retry"
  adb reverse tcp:8081 tcp:8081
  run_maestro 2
  exit $?
fi

exit "$code"
