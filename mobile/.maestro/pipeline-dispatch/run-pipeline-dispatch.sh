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
trap 'code=$?; if [ "$code" -ne 0 ]; then collect_device_state; python3 "$FLOWS/../upl01/summarize_failure.py" "$EVIDENCE_DIR" "${GITHUB_STEP_SUMMARY:-}" || true; fi; exit "$code"' EXIT

adb start-server >/dev/null 2>&1 || true
adb wait-for-device
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8787 tcp:8787
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
curl -fsS "$MOCK_API/__test__/reset" > /dev/null

# Retry only a proven emulator/adb infrastructure failure that happened before the app sent any
# dispatch request; any assertion failure or a failure after a dispatch is a real failure.
for attempt in 1 2 3; do
  curl -fsS "$MOCK_API/__test__/reset" > /dev/null
  set +e
  maestro test "$FLOWS/01-run-reset-visibility.yaml" \
    -e MAESTRO_OPERATOR_SECRET="$MAESTRO_OPERATOR_SECRET" \
    --format junit --output "$EVIDENCE_DIR/result.junit.xml" \
    --debug-output "$EVIDENCE_DIR/debug" --test-output-dir "$EVIDENCE_DIR/debug" --flatten-debug-output
  flow_code=$?
  set -e
  [ "$flow_code" -eq 0 ] && break
  dispatches="$(curl -fsS "$MOCK_API/__test__/evidence" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["dispatches"]))')"
  if ! grep -RqsE 'device offline|Device server died|DeviceServerDiedException|StatusRuntimeException: UNAVAILABLE' "$EVIDENCE_DIR/debug"; then
    echo "pipeline-dispatch: flow failed (not an infrastructure failure); not retrying" >&2
    exit "$flow_code"
  fi
  if [ "$dispatches" -ne 0 ] || [ "$attempt" -eq 3 ]; then
    echo "pipeline-dispatch: infrastructure failure but retry is unsafe (dispatches=$dispatches attempt=$attempt)" >&2
    exit "$flow_code"
  fi
  echo "pipeline-dispatch: retrying after proven emulator failure with zero dispatches (attempt $attempt/3)"
  adb kill-server >/dev/null 2>&1 || true
  sleep 3
  adb start-server >/dev/null 2>&1 || true
  adb wait-for-device
  sleep 5
  adb reverse tcp:8081 tcp:8081
  adb reverse tcp:8787 tcp:8787
  rm -rf "$EVIDENCE_DIR/debug"
done

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
