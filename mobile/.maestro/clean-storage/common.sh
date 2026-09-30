# Shared helpers for the Clean Video Storage Android E2E runners (sourced).
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true

stabilize_adb_device() {
  local phase="$1" attempt stable
  echo "clean-e2e: stabilizing Android device before $phase"
  adb start-server >/dev/null 2>&1 || true
  for attempt in 1 2 3 4 5 6; do
    stable=1
    for _ in 1 2 3; do
      if [ "$(adb get-state 2>/dev/null || true)" != "device" ] || \
         [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; then stable=0; break; fi
      adb shell true >/dev/null 2>&1 || { stable=0; break; }
      sleep 2
    done
    [ "$stable" -eq 1 ] && return 0
    adb kill-server >/dev/null 2>&1 || true; sleep 2
    adb start-server >/dev/null 2>&1 || true; adb wait-for-device || true; sleep 4
  done
  echo "clean-e2e: device never stable before $phase" >&2; return 1
}

collect_device_state() {
  set +e
  maestro hierarchy > "$EVIDENCE_DIR/final-maestro-hierarchy.json" 2>/dev/null
  adb exec-out screencap -p > "$EVIDENCE_DIR/final-screen.png" 2>/dev/null
  adb logcat -d > "$EVIDENCE_DIR/logcat.txt" 2>/dev/null
  set -e
}

scrub_secrets() {
  python3 - "$EVIDENCE_DIR" <<'PY'
import os, pathlib, sys
root = pathlib.Path(sys.argv[1])
secrets = [os.environ[k].encode() for k in ("OPERATOR_SECRET", "MAESTRO_OPERATOR_SECRET", "SUPABASE_SERVICE_KEY",
           "R2_SECRET_ACCESS_KEY", "R2_ACCESS_KEY_ID") if os.environ.get(k)]
leaks = 0
for p in root.rglob("*"):
    if not p.is_file():
        continue
    d = p.read_bytes(); c = d
    for s in secrets:
        c = c.replace(s, b"[REDACTED]")
    if c != d:
        p.write_bytes(c); leaks += 1
print(f"scrub_secrets: redacted {leaks} file(s)")
PY
}

run_flow() {
  local flow="$1" name; name="$(basename "$flow" .yaml)"
  echo "::group::Maestro $name"
  maestro test "$FLOWS/$flow" -e MAESTRO_OPERATOR_SECRET="$MAESTRO_OPERATOR_SECRET" \
    --format junit --output "$EVIDENCE_DIR/$name.junit.xml" \
    --debug-output "$EVIDENCE_DIR/maestro-$name" --test-output-dir "$EVIDENCE_DIR/maestro-$name" --flatten-debug-output
  local code=$?
  echo "::endgroup::"
  return $code
}

# Real infra flake (emulator/Maestro server died) is distinguished from product failure.
is_infra_failure() {
  grep -RqsE 'device offline|Device server died|DeviceServerDiedException|StatusRuntimeException: UNAVAILABLE|Pixel Launcher isn.t responding' "$EVIDENCE_DIR"
}
