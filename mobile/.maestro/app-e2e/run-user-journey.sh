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
  echo "::group::Maestro failure evidence"
  test -f "$EVIDENCE_DIR/user-journey.junit.xml" && cat "$EVIDENCE_DIR/user-journey.junit.xml"
  test -f "$EVIDENCE_DIR/maestro-debug/maestro.log" && tail -n 160 "$EVIDENCE_DIR/maestro-debug/maestro.log"
  test -f "$EVIDENCE_DIR/crash-logcat.txt" && { echo "--- crash logcat ---"; tail -n 120 "$EVIDENCE_DIR/crash-logcat.txt"; }
  echo "::endgroup::"
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect; fi; exit "$code"' EXIT

adb wait-for-device

# reactivecircus can report sys.boot_completed before ADB remains stable enough
# for Maestro's device server. Require consecutive healthy probes so a transient
# offline/reconnect window is treated as infrastructure readiness, not an app failure.
stable=0
for attempt in $(seq 1 30); do
  state="$(adb get-state 2>/dev/null || true)"
  boot="$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  if [[ "$state" == "device" && "$boot" == "1" ]] && adb shell true >/dev/null 2>&1; then
    stable=$((stable + 1))
    if (( stable >= 5 )); then
      break
    fi
  else
    stable=0
    adb reconnect >/dev/null 2>&1 || true
  fi
  sleep 2
done
if (( stable < 5 )); then
  echo "Android emulator never reached stable ADB readiness" >&2
  adb devices -l >&2 || true
  exit 3
fi

adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
adb shell monkey -p "$APP_ID" 1 >/dev/null 2>&1 || true
sleep 3
adb shell am force-stop "$APP_ID" >/dev/null 2>&1 || true

timeout --signal=TERM --kill-after=30s 600s \
  maestro test "$HERE/01-user-journey.yaml" \
    --format junit --output "$EVIDENCE_DIR/user-journey.junit.xml" \
    --debug-output "$EVIDENCE_DIR/maestro-debug" \
    --test-output-dir "$EVIDENCE_DIR/maestro-debug" \
    --flatten-debug-output

adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null || true
