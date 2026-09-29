#!/usr/bin/env bash
set -euo pipefail
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$EVIDENCE_DIR"

for var in APK EVIDENCE_DIR OPERATOR_SECRET BLOCKED_REEDIT_ID READY_APPROVE_ID E2E_REVIEW_STATE_PATH E2E_REVIEW_EVIDENCE_PATH; do
  test -n "${!var:-}" || { echo "missing required env $var" >&2; exit 2; }
done

collect() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
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

stabilize_adb_device "review re-edit Maestro"
timeout --signal=TERM --kill-after=30s 480s maestro test   -e OPERATOR_SECRET="$OPERATOR_SECRET"   -e BLOCKED_REEDIT_ID="$BLOCKED_REEDIT_ID"   "$HERE/03-review-reedit.yaml"   --format junit --output "$EVIDENCE_DIR/review-reedit.junit.xml"   --debug-output "$EVIDENCE_DIR/review-reedit-debug"   --test-output-dir "$EVIDENCE_DIR/review-reedit-debug" --flatten-debug-output

python3 scripts/app_review_delivery_e2e.py verify-reedit-cancel

stabilize_adb_device "review approval Maestro"
adb reverse tcp:8081 tcp:8081
timeout --signal=TERM --kill-after=30s 480s maestro test   -e READY_APPROVE_ID="$READY_APPROVE_ID"   "$HERE/04-review-approve.yaml"   --format junit --output "$EVIDENCE_DIR/review-approve.junit.xml"   --debug-output "$EVIDENCE_DIR/review-approve-debug"   --test-output-dir "$EVIDENCE_DIR/review-approve-debug" --flatten-debug-output

python3 scripts/app_review_delivery_e2e.py verify-delivery-discover

read -r DISCOVER_REEL_ID DISCOVER_SPORT < <(python3 - <<'PY'
import json, os
state = json.load(open(os.environ["E2E_REVIEW_STATE_PATH"]))
print(state["reel_id"], state["discover_sport"])
PY
)
export DISCOVER_REEL_ID DISCOVER_SPORT

stabilize_adb_device "discover Maestro"
adb reverse tcp:8081 tcp:8081
timeout --signal=TERM --kill-after=30s 300s maestro test   -e DISCOVER_REEL_ID="$DISCOVER_REEL_ID"   -e DISCOVER_SPORT="$DISCOVER_SPORT"   "$HERE/05-discover-fixture.yaml"   --format junit --output "$EVIDENCE_DIR/discover.junit.xml"   --debug-output "$EVIDENCE_DIR/discover-debug"   --test-output-dir "$EVIDENCE_DIR/discover-debug" --flatten-debug-output

python3 scripts/app_review_delivery_e2e.py verify-discover
