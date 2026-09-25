#!/usr/bin/env bash
set -euo pipefail

export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$EVIDENCE_DIR"

for var in APK EVIDENCE_DIR MAESTRO_OPERATOR_SECRET E2E_SUPPORT_ID E2E_SUPPORT_MESSAGE E2E_SUGGESTION_MESSAGE E2E_OPERATOR_REPLY E2E_PRICING_SPORT; do
  test -n "${!var:-}" || { echo "missing required env $var" >&2; exit 2; }
done

collect() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb shell dumpsys activity activities > "$EVIDENCE_DIR/final-activities.txt" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null
  echo "::group::Operator Maestro failure evidence"
  test -f "$EVIDENCE_DIR/operator-basic.junit.xml" && cat "$EVIDENCE_DIR/operator-basic.junit.xml"
  test -f "$EVIDENCE_DIR/maestro-debug/maestro.log" && tail -n 200 "$EVIDENCE_DIR/maestro-debug/maestro.log"
  test -f "$EVIDENCE_DIR/crash-logcat.txt" && { echo "--- crash logcat ---"; tail -n 120 "$EVIDENCE_DIR/crash-logcat.txt"; }
  echo "::endgroup::"
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect; fi; exit "$code"' EXIT

adb wait-for-device
stable=0
for attempt in $(seq 1 30); do
  state="$(adb get-state 2>/dev/null || true)"
  boot="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  if [[ "$state" == "device" && "$boot" == "1" ]] && adb shell true >/dev/null 2>&1; then
    stable=$((stable + 1))
    (( stable >= 5 )) && break
  else
    stable=0
    adb reconnect >/dev/null 2>&1 || true
  fi
  sleep 2
done
(( stable >= 5 )) || { echo "Android emulator never reached stable ADB readiness" >&2; exit 3; }

adb reverse tcp:8081 tcp:8081
adb reverse tcp:3000 tcp:3000
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
adb shell monkey -p com.sportreel.app 1 >/dev/null 2>&1 || true
sleep 3
adb shell am force-stop com.sportreel.app >/dev/null 2>&1 || true

timeout --signal=TERM --kill-after=30s 600s   maestro test "$HERE/01-operator-basic.yaml"     --format junit --output "$EVIDENCE_DIR/operator-basic.junit.xml"     --debug-output "$EVIDENCE_DIR/maestro-debug"     --test-output-dir "$EVIDENCE_DIR/maestro-debug"     --flatten-debug-output

adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null || true
