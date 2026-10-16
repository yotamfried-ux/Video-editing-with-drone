#!/usr/bin/env bash
# Runs the pipeline-dispatch Maestro scenario against the local stub API only.
set -euo pipefail

export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
FLOWS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCK_API="${MOCK_API:-http://127.0.0.1:8787}"
for var in APK EVIDENCE_DIR MAESTRO_OPERATOR_SECRET; do
  test -n "${!var:-}" || { echo "pipeline-dispatch: required env $var is empty" >&2; exit 2; }
done
mkdir -p "$EVIDENCE_DIR"

collect_device_state() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-maestro-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  curl -fsS "$MOCK_API/__test__/evidence" > "$EVIDENCE_DIR/server-evidence-on-exit.json" 2>/dev/null
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect_device_state; fi; exit "$code"' EXIT

adb start-server >/dev/null 2>&1 || true
adb wait-for-device
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8787 tcp:8787
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
curl -fsS "$MOCK_API/__test__/reset" > /dev/null

maestro test "$FLOWS/01-run-reset-visibility.yaml" \
  -e MAESTRO_OPERATOR_SECRET="$MAESTRO_OPERATOR_SECRET" \
  --format junit --output "$EVIDENCE_DIR/result.junit.xml" \
  --debug-output "$EVIDENCE_DIR/debug" --test-output-dir "$EVIDENCE_DIR/debug" --flatten-debug-output

curl -fsS "$MOCK_API/__test__/evidence" > "$EVIDENCE_DIR/server-evidence.json"
python3 - "$EVIDENCE_DIR/server-evidence.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
kinds = [(d["kind"], d["full_clean"], d["accepted"]) for d in data["dispatches"]]
# Run pipeline accepted, duplicate press rejected, standard (not full-clean) reset accepted.
assert kinds == [("process", False, True), ("process", False, False), ("reset_and_rerun", False, True)], kinds
assert data["accepted"] == 2 and data["rejected_409"] == 1, data
print("pipeline-dispatch server evidence PASS:", kinds)
PY
