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
    FLOW="01-no-operator-secret.yaml"
    EXPECTATION="no-upload"
    ;;
  picker-cancelled)
    FLOW="02-picker-cancelled.yaml"
    EXPECTATION="no-upload"
    ;;
  gallery-upload)
    FLOW="03-gallery-upload.yaml"
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

adb wait-for-device
test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = "1"
adb shell getprop ro.build.version.sdk | tr -d '\r' > "$EVIDENCE_DIR/android-sdk.txt"
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

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

run_flow 00-seed-media.yaml
run_flow "$FLOW"

python3 "$REPO_ROOT/scripts/upl01_backend_evidence.py" \
  --fixture "$FIXTURE" \
  --since "$WINDOW_START" \
  --api-base "$API_BASE" \
  --supabase-url "$SUPABASE_URL" \
  --expect "$EXPECTATION" \
  --evidence "$EVIDENCE_DIR/backend-evidence.json"
