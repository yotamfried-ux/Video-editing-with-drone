#!/usr/bin/env bash
set -euo pipefail
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$EVIDENCE_DIR"
for var in APK EVIDENCE_DIR OPERATOR_SECRET; do
  test -n "${!var:-}" || { echo "missing required env $var" >&2; exit 2; }
done

# Maestro's debug logger can echo inputText values. Register the value with
# GitHub's masker before Maestro starts and scrub persisted evidence before it
# is uploaded so operator credentials never become test artifacts.
echo "::add-mask::$OPERATOR_SECRET"

redact_secret_from_evidence() {
  OPERATOR_SECRET_TO_REDACT="$OPERATOR_SECRET" EVIDENCE_DIR_TO_REDACT="$EVIDENCE_DIR" python3 - <<'PY'
import os
from pathlib import Path

secret = os.environ.get("OPERATOR_SECRET_TO_REDACT", "").encode()
root = Path(os.environ["EVIDENCE_DIR_TO_REDACT"])
if not secret or not root.exists():
    raise SystemExit(0)
for path in root.rglob("*"):
    if not path.is_file():
        continue
    try:
        data = path.read_bytes()
    except OSError:
        continue
    if secret in data:
        path.write_bytes(data.replace(secret, b"***"))
PY
}

collect() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  for report in "$EVIDENCE_DIR"/operator-readonly-attempt-*.junit.xml; do
    test -f "$report" && cat "$report"
  done
  redact_secret_from_evidence
  set -e
}
trap 'code=$?; if [ "$code" -ne 0 ]; then collect; else redact_secret_from_evidence; fi; exit "$code"' EXIT

stabilize_adb_device() {
  local phase="$1" attempt stable
  echo "APP E2E: stabilizing Android device before $phase"
  adb start-server >/dev/null 2>&1 || true
  for attempt in 1 2 3 4 5 6; do
    stable=1
    for _ in 1 2 3; do
      if [ "$(adb get-state 2>/dev/null || true)" != "device" ] || \
         [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; then
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
stabilize_adb_device "operator Maestro"

run_maestro() {
  local attempt="$1"
  local debug="$EVIDENCE_DIR/maestro-attempt-$attempt"
  timeout --signal=TERM --kill-after=30s 600s maestro test \
    -e OPERATOR_SECRET="$OPERATOR_SECRET" \
    "$HERE/02-operator-readonly.yaml" \
    --format junit --output "$EVIDENCE_DIR/operator-readonly-attempt-$attempt.junit.xml" \
    --debug-output "$debug" \
    --test-output-dir "$debug" \
    --flatten-debug-output
}

# GitHub-hosted emulators occasionally flap offline after Maestro starts its
# device server. Allow up to three attempts, but only when the previous attempt
# contains direct infrastructure-failure evidence. Product/assertion failures
# are never retried.
for attempt in 1 2 3; do
  set +e
  run_maestro "$attempt"
  code=$?
  set -e
  redact_secret_from_evidence

  if [ "$code" -eq 0 ]; then
    exit 0
  fi

  debug="$EVIDENCE_DIR/maestro-attempt-$attempt"
  if ! grep -RqsE 'device offline|Device server died|DeviceServerDiedException|StatusRuntimeException: UNAVAILABLE' "$debug"; then
    exit "$code"
  fi
  if [ "$attempt" -eq 3 ]; then
    echo "Maestro exhausted three infrastructure-only retries." >&2
    exit "$code"
  fi

  echo "Maestro attempt $attempt hit proven device-offline infrastructure failure; retrying on the same emulator after bounded adb recovery."
  adb kill-server >/dev/null 2>&1 || true
  sleep 2
  stabilize_adb_device "operator Maestro retry $((attempt + 1))"
  adb reverse tcp:8081 tcp:8081
done
