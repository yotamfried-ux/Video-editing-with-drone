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

adb wait-for-device
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

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
  echo "Maestro attempt 1 hit known transient device-offline failure; retrying after adb health check."
  adb wait-for-device
  for _ in $(seq 1 30); do
    if [ "$(adb get-state 2>/dev/null || true)" = "device" ]; then
      break
    fi
    sleep 2
  done
  adb reverse tcp:8081 tcp:8081
  run_maestro 2
  exit $?
fi

exit "$code"
