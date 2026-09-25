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
  for junit in "$EVIDENCE_DIR"/user-journey-attempt-*.junit.xml; do
    test -f "$junit" && { echo "--- $(basename "$junit") ---"; cat "$junit"; }
  done
  for log in "$EVIDENCE_DIR"/maestro-attempt-*/maestro.log; do
    test -f "$log" && { echo "--- $(basename "$(dirname "$log")")/maestro.log ---"; tail -n 160 "$log"; }
  done
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

run_maestro_attempt() {
  local attempt="$1"
  local junit="$EVIDENCE_DIR/user-journey-attempt-$attempt.junit.xml"
  local debug="$EVIDENCE_DIR/maestro-attempt-$attempt"

  set +e
  timeout --signal=TERM --kill-after=30s 600s \
    maestro test \
      -e E2E_EMAIL="$E2E_EMAIL" \
      -e E2E_PASSWORD="$E2E_PASSWORD" \
      -e E2E_MARKER="$E2E_MARKER" \
      "$HERE/01-user-journey.yaml" \
      --format junit --output "$junit" \
      --debug-output "$debug" \
      --test-output-dir "$debug" \
      --flatten-debug-output
  local code=$?
  set -e

  if [ "$code" -eq 0 ]; then
    cp "$junit" "$EVIDENCE_DIR/user-journey.junit.xml"
    return 0
  fi

  if grep -Eqi 'device offline|DeviceServerDiedException' "$debug/maestro.log" 2>/dev/null; then
    echo "Maestro attempt $attempt hit known transient dadb device-offline failure."
    return 75
  fi
  return "$code"
}

maestro_ok=0
for attempt in 1 2 3; do
  if run_maestro_attempt "$attempt"; then
    maestro_ok=1
    break
  else
    code=$?
  fi
  if [ "$code" -ne 75 ] || [ "$attempt" -eq 3 ]; then
    exit "$code"
  fi

  echo "Retrying Maestro with a fresh process after verifying adb health..."
  adb start-server >/dev/null 2>&1 || true
  adb wait-for-device
  for _ in $(seq 1 20); do
    if [ "$(adb get-state 2>/dev/null || true)" = "device" ] && adb shell true >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  test "$(adb get-state 2>/dev/null)" = "device"
  sleep 2
done

test "$maestro_ok" -eq 1
adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null || true
