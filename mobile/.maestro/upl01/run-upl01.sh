#!/usr/bin/env bash
# UPL-01 emulator driver. Non-UI provisioning only (install, Metro tunnel,
# evidence); every operator interaction is a Maestro flow in this directory.
#
# Required env: APK, EVIDENCE_DIR, MAESTRO_OPERATOR_SECRET, OPERATOR_SECRET,
# SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL, API_BASE, APP_ID.
set -euo pipefail

export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true

FLOWS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$FLOWS/../../.." && pwd)"
FIXTURE="$FLOWS/media/upl01-fixture.mp4"
mkdir -p "$EVIDENCE_DIR"

for var in APK EVIDENCE_DIR MAESTRO_OPERATOR_SECRET OPERATOR_SECRET SUPABASE_SERVICE_ROLE_KEY SUPABASE_URL API_BASE APP_ID; do
  test -n "${!var:-}" || { echo "UPL-01 harness: required env $var is empty" >&2; exit 2; }
done
test -s "$FIXTURE" || { echo "UPL-01 harness: missing fixture $FIXTURE" >&2; exit 2; }

collect_device_state() {
  # Maestro's own view first (what the flows could see), then raw device state.
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-maestro-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb shell dumpsys activity activities > "$EVIDENCE_DIR/final-activities.txt" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  adb logcat -b crash -d > "$EVIDENCE_DIR/crash-logcat.txt" 2>/dev/null
  set -e
}

scrub_secrets() {
  # Maestro debug output records evaluated commands (inputText). Replace the
  # secret in every text artifact and refuse to publish anything still leaking.
  python3 - "$EVIDENCE_DIR" <<'PY'
import os, pathlib, sys
root = pathlib.Path(sys.argv[1])
secrets = [os.environ[k].encode() for k in ("OPERATOR_SECRET", "MAESTRO_OPERATOR_SECRET", "SUPABASE_SERVICE_ROLE_KEY") if os.environ.get(k)]
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
        leaks.append(str(path))
if leaks:
    for leak in leaks:
        path = pathlib.Path(leak)
        path.unlink()
    print(f"UPL-01 harness: removed {len(leaks)} artifact(s) that still contained a secret", file=sys.stderr)
    sys.exit(3)
PY
}

on_exit() {
  local code=$?
  if [ "$code" -ne 0 ]; then collect_device_state; fi
  scrub_secrets || code=3
  exit "$code"
}
trap on_exit EXIT

adb wait-for-device
test "$(adb shell getprop sys.boot_completed | tr -d '\r')" = "1"
adb shell getprop ro.build.version.sdk | tr -d '\r' > "$EVIDENCE_DIR/android-sdk.txt"
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"

# Correlation window starts before any flow can create a row. The 60 s margin
# absorbs runner/DB clock skew; the workflow's concurrency group guarantees no
# other UPL-01 run can upload inside that margin.
WINDOW_START="$(date -u -d '-60 seconds' +%Y-%m-%dT%H:%M:%SZ)"
echo "$WINDOW_START" > "$EVIDENCE_DIR/window-start-utc.txt"

run_flow() {
  local flow="$1" name
  name="$(basename "$flow" .yaml)"
  echo "::group::Maestro $name"
  maestro test "$FLOWS/$flow" \
    --format junit --output "$EVIDENCE_DIR/$name.junit.xml" \
    --debug-output "$EVIDENCE_DIR/maestro-$name" \
    --test-output-dir "$EVIDENCE_DIR/maestro-$name" \
    --flatten-debug-output
  echo "::endgroup::"
}

run_flow 00-seed-media.yaml
run_flow 01-no-operator-secret.yaml
run_flow 02-picker-cancelled.yaml
run_flow 03-gallery-upload.yaml

python3 "$REPO_ROOT/scripts/upl01_backend_evidence.py" \
  --fixture "$FIXTURE" \
  --since "$WINDOW_START" \
  --api-base "$API_BASE" \
  --supabase-url "$SUPABASE_URL" \
  --evidence "$EVIDENCE_DIR/backend-evidence.json"
