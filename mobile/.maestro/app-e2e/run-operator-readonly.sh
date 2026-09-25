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
  test -f "$EVIDENCE_DIR/operator-readonly.junit.xml" && cat "$EVIDENCE_DIR/operator-readonly.junit.xml"
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect; fi; exit "$code"' EXIT

adb wait-for-device
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

timeout --signal=TERM --kill-after=30s 600s maestro test   -e OPERATOR_SECRET="$OPERATOR_SECRET"   "$HERE/02-operator-readonly.yaml"   --format junit --output "$EVIDENCE_DIR/operator-readonly.junit.xml"   --debug-output "$EVIDENCE_DIR/maestro-debug"   --test-output-dir "$EVIDENCE_DIR/maestro-debug"   --flatten-debug-output
