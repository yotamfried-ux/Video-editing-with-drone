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

adb wait-for-device
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

timeout --signal=TERM --kill-after=30s 480s maestro test   -e OPERATOR_SECRET="$OPERATOR_SECRET"   -e BLOCKED_REEDIT_ID="$BLOCKED_REEDIT_ID"   "$HERE/03-review-reedit.yaml"   --format junit --output "$EVIDENCE_DIR/review-reedit.junit.xml"   --debug-output "$EVIDENCE_DIR/review-reedit-debug"   --test-output-dir "$EVIDENCE_DIR/review-reedit-debug" --flatten-debug-output

python3 scripts/app_review_delivery_e2e.py verify-reedit-cancel

timeout --signal=TERM --kill-after=30s 480s maestro test   -e READY_APPROVE_ID="$READY_APPROVE_ID"   "$HERE/04-review-approve.yaml"   --format junit --output "$EVIDENCE_DIR/review-approve.junit.xml"   --debug-output "$EVIDENCE_DIR/review-approve-debug"   --test-output-dir "$EVIDENCE_DIR/review-approve-debug" --flatten-debug-output

python3 scripts/app_review_delivery_e2e.py verify-approval-cancel
python3 scripts/app_review_delivery_e2e.py seed-discover

DISCOVER_SPORT="$(python3 - <<'PY'
import json, os
print(json.load(open(os.environ["E2E_REVIEW_STATE_PATH"]))["discover_sport"])
PY
)"
export DISCOVER_SPORT

timeout --signal=TERM --kill-after=30s 300s maestro test   -e DISCOVER_SPORT="$DISCOVER_SPORT"   "$HERE/05-discover-fixture.yaml"   --format junit --output "$EVIDENCE_DIR/discover.junit.xml"   --debug-output "$EVIDENCE_DIR/discover-debug"   --test-output-dir "$EVIDENCE_DIR/discover-debug" --flatten-debug-output

python3 scripts/app_review_delivery_e2e.py verify-discover
