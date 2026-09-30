#!/usr/bin/env bash
# Scenario D (UI): failure/interruption must never be shown as success. Uses the stub API only.
set -euo pipefail
FLOWS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$FLOWS/common.sh"
for v in APK EVIDENCE_DIR MAESTRO_OPERATOR_SECRET; do test -n "${!v:-}" || { echo "required env $v empty" >&2; exit 2; }; done
mkdir -p "$EVIDENCE_DIR"
trap 'code=$?; [ $code -ne 0 ] && collect_device_state; scrub_secrets || code=3; exit $code' EXIT
stabilize_adb_device "APK install"
adb reverse tcp:8081 tcp:8081
adb reverse tcp:8788 tcp:8788
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
stabilize_adb_device "Maestro"
curl -fsS "http://127.0.0.1:8788/__test__/scenario?name=failed-then-unverified-then-ok" > "$EVIDENCE_DIR/scenario-failed.json"
run_flow 03-clean-failure.yaml
curl -fsS "http://127.0.0.1:8788/__test__/evidence" > "$EVIDENCE_DIR/evidence-failed.json"
curl -fsS "http://127.0.0.1:8788/__test__/scenario?name=interrupted" > "$EVIDENCE_DIR/scenario-interrupted.json"
adb shell pm clear com.sportreel.app >/dev/null 2>&1 || true
run_flow 04-interrupted.yaml
curl -fsS "http://127.0.0.1:8788/__test__/evidence" > "$EVIDENCE_DIR/evidence-interrupted.json"
