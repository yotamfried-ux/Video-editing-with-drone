#!/usr/bin/env bash
set -euo pipefail

export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$EVIDENCE_DIR"

for var in APK EVIDENCE_DIR E2E_EMAIL E2E_PASSWORD E2E_MARKER; do
  test -n "${!var:-}" || { echo "missing required env $var" >&2; exit 2; }
done

collect() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb shell dumpsys activity activities > "$EVIDENCE_DIR/final-activities.txt" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect; fi; exit "$code"' EXIT

adb wait-for-device
test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = "1"
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

maestro test "$HERE/01-user-journey.yaml" \
  --format junit --output "$EVIDENCE_DIR/user-journey.junit.xml" \
  --debug-output "$EVIDENCE_DIR/maestro-debug" \
  --test-output-dir "$EVIDENCE_DIR/maestro-debug" \
  --flatten-debug-output

adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null || true
