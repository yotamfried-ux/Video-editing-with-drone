#!/usr/bin/env bash
# Run exactly one isolated UPL-01 behavioral scenario on one emulator.
# The workflow executes this script in a matrix so independent Maestro
# scenarios run concurrently instead of sharing one device serially.
set -euo pipefail

export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true

FLOWS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$FLOWS/../../.." && pwd)"
FIXTURE="$FLOWS/media/upl01-fixture.mp4"
SCENARIO="${UPL01_SCENARIO:?UPL01_SCENARIO is required}"
mkdir -p "$EVIDENCE_DIR"

case "$SCENARIO" in
  no-operator-secret)
    FLOW="10-isolated-no-operator-secret.yaml"
    EXPECTATION="no-upload"
    ;;
  picker-cancelled)
    FLOW="11-isolated-picker-cancelled.yaml"
    EXPECTATION="no-upload"
    ;;
  gallery-upload)
    FLOW="12-isolated-gallery-upload.yaml"
    EXPECTATION="verified-upload"
    ;;
  offline-retry)
    FLOW="13-isolated-offline-retry.yaml"
    EXPECTATION="verified-upload"
    ;;
  restart-retry)
    FLOW="14-isolated-restart-retry.yaml"
    EXPECTATION="verified-upload"
    ;;
  *)
    echo "UPL-01 scenario runner: unknown scenario '$SCENARIO'" >&2
    exit 2
    ;;
esac

for var in APK EVIDENCE_DIR SUPABASE_SERVICE_ROLE_KEY SUPABASE_URL API_BASE APP_ID; do
  test -n "${!var:-}" || { echo "UPL-01 scenario runner: required env $var is empty" >&2; exit 2; }
done
if [ "$SCENARIO" != "no-operator-secret" ]; then
  for var in OPERATOR_SECRET MAESTRO_OPERATOR_SECRET; do
    test -n "${!var:-}" || { echo "UPL-01 scenario runner: required env $var is empty" >&2; exit 2; }
  done
fi
test -s "$FIXTURE" || { echo "UPL-01 scenario runner: missing fixture $FIXTURE" >&2; exit 2; }

collect_device_state() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-maestro-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb shell dumpsys activity activities > "$EVIDENCE_DIR/final-activities.txt" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null
  set -e
}

scrub_secrets() {
  python3 - "$EVIDENCE_DIR" <<'PY'
import os, pathlib, sys
root = pathlib.Path(sys.argv[1])
secrets = [
    os.environ[k].encode()
    for k in ("OPERATOR_SECRET", "MAESTRO_OPERATOR_SECRET", "SUPABASE_SERVICE_ROLE_KEY")
    if os.environ.get(k)
]
leaks = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    data = path.read_bytes()
    cleaned = data
    for secret in secrets:
        cleaned = cleaned.replace(secret, b"[REDACTED]")
    if cleaned != data:
        path.write_bytes(cleaned)
    if any(secret in path.read_bytes() for secret in secrets):
        leaks.append(path)
for path in leaks:
    path.unlink()
if leaks:
    print(f"UPL-01 scenario runner: removed {len(leaks)} artifact(s) that still contained a secret", file=sys.stderr)
    sys.exit(3)
PY
}

on_exit() {
  local code=$?
  if [ "$code" -ne 0 ]; then collect_device_state; fi
  scrub_secrets || code=3
  if [ "$code" -ne 0 ]; then
    python3 "$FLOWS/summarize_failure.py" "$EVIDENCE_DIR" "${GITHUB_STEP_SUMMARY:-}" || true
  fi
  exit "$code"
}
trap on_exit EXIT

stabilize_adb_device() {
  local phase="$1" attempt stable
  echo "UPL-01 scenario runner: stabilizing Android device before $phase"
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
      echo "UPL-01 scenario runner: Android device stable before $phase"
      return 0
    fi

    echo "UPL-01 scenario runner: adb unstable before $phase (attempt $attempt/6); restarting adb"
    adb kill-server >/dev/null 2>&1 || true
    sleep 2
    adb start-server >/dev/null 2>&1 || true
    adb wait-for-device || true
    sleep 4
  done

  echo "UPL-01 scenario runner: Android device never became stable before $phase" >&2
  adb devices -l >&2 || true
  return 1
}

stabilize_adb_device "APK install"
adb shell getprop ro.build.version.sdk | tr -d '\r' > "$EVIDENCE_DIR/android-sdk.txt"
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
stabilize_adb_device "Maestro"

# A unique fixture byte size is generated for each matrix scenario. That lets
# negative and positive backend checks run concurrently without correlating to
# each other's rows.
WINDOW_START="$(date -u -d '-60 seconds' +%Y-%m-%dT%H:%M:%SZ)"
echo "$WINDOW_START" > "$EVIDENCE_DIR/window-start-utc.txt"
printf '%s\n' "$SCENARIO" > "$EVIDENCE_DIR/scenario.txt"
stat -c '%s' "$FIXTURE" > "$EVIDENCE_DIR/fixture-size-bytes.txt"

run_flow() {
  local flow="$1" name
  name="$(basename "$flow" .yaml)"
  echo "::group::Maestro $SCENARIO / $name"
  maestro test "$FLOWS/$flow" \
    --format junit --output "$EVIDENCE_DIR/$name.junit.xml" \
    --debug-output "$EVIDENCE_DIR/maestro-$name" \
    --test-output-dir "$EVIDENCE_DIR/maestro-$name" \
    --flatten-debug-output
  echo "::endgroup::"
}

# Seed + behavior execute inside one Maestro process. On parallel emulator
# workers, opening a second Maestro process after the seed flow caused the
# Android device server to go offline on run 35901916354.
#
# Re-check adb immediately before Maestro. GitHub-hosted Android emulators can
# transiently return "device offline" after boot even when boot_completed=1.
# Retry only negative/no-upload scenarios when Maestro itself proves the device
# server died; positive flows are never replayed because that could create a
# second backend write and weaken the exactly-one-row evidence.
stabilize_adb_device "Maestro flow"
set +e
run_flow "$FLOW"
flow_code=$?
set -e

infra_failure=0
if [ "$flow_code" -ne 0 ] && grep -RqsE   'device offline|Device server died|DeviceServerDiedException|StatusRuntimeException: UNAVAILABLE|Pixel Launcher isn.t responding'   "$EVIDENCE_DIR"; then
  infra_failure=1
fi

safe_retry=0
if [ "$flow_code" -ne 0 ] && [ "$infra_failure" -eq 1 ]; then
  if [ "$EXPECTATION" = "no-upload" ]; then
    safe_retry=1
  else
    set +e
    python3 "$REPO_ROOT/scripts/upl01_backend_evidence.py" \
      --fixture "$FIXTURE" \
      --since "$WINDOW_START" \
      --api-base "$API_BASE" \
      --supabase-url "$SUPABASE_URL" \
      --expect no-upload \
      --evidence "$EVIDENCE_DIR/pre-retry-backend-evidence.json"
    no_upload_code=$?
    set -e
    if [ "$no_upload_code" -eq 0 ]; then
      safe_retry=1
    else
      echo "UPL-01 scenario runner: refusing positive-flow retry because backend state is not empty" >&2
    fi
  fi
fi

if [ "$safe_retry" -eq 1 ]; then
  echo "UPL-01 scenario runner: proven infrastructure failure with no unsafe backend side effect; retrying scenario once"
  stabilize_adb_device "Maestro infrastructure retry"
  adb shell settings put global airplane_mode_on 0 >/dev/null 2>&1 || true
  adb shell am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false >/dev/null 2>&1 || true
  mkdir -p "$EVIDENCE_DIR/attempt-1"
  for artifact in "$EVIDENCE_DIR/maestro-"* "$EVIDENCE_DIR/"*.junit.xml; do
    [ -e "$artifact" ] || continue
    mv "$artifact" "$EVIDENCE_DIR/attempt-1/" || true
  done
  run_flow "$FLOW"
elif [ "$flow_code" -ne 0 ]; then
  exit "$flow_code"
fi

python3 "$REPO_ROOT/scripts/upl01_backend_evidence.py" \
  --fixture "$FIXTURE" \
  --since "$WINDOW_START" \
  --api-base "$API_BASE" \
  --supabase-url "$SUPABASE_URL" \
  --expect "$EXPECTATION" \
  --evidence "$EVIDENCE_DIR/backend-evidence.json"
