#!/usr/bin/env bash
# Runs ONE Android background-upload lifecycle scenario on one emulator.
#
# Maestro drives the real UI (operator secret, SAF folder picker, select-all, upload, UI assertions).
# adb performs the OS-level perturbations (Home, screen off, process kill, airplane mode) and reads the
# app's durable native ledger via run-as. scripts/background_upload_evidence.py independently verifies
# Supabase rows, part rows and R2 objects, and the verified-batch gate. Every failure is classified as
# product / backend / android-emulator-infra / harness (UI automation) in failure-class.txt.
set -uo pipefail
export MAESTRO_CLI_NO_ANALYTICS=1 MAESTRO_CLI_ANALYSIS_NOTIFICATION_DISABLED=true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
EVID_PY="$REPO_ROOT/scripts/background_upload_evidence.py"
SCENARIO="${BGQ_SCENARIO:?BGQ_SCENARIO is required}"
E="${EVIDENCE_DIR:?EVIDENCE_DIR is required}"
TOTAL="${BGQ_VIDEO_COUNT:-3}"
FIXTURE_DIR="${BGQ_FIXTURE_DIR:?BGQ_FIXTURE_DIR is required}"
FOLDER="sportreel-bg-${SCENARIO}-${GITHUB_RUN_ID:-local}"
PKG="${APP_ID:-com.sportreel.app}"
PREFS_PATH="shared_prefs/sportreel_background_uploads.xml"
mkdir -p "$E"
PHASE="setup"
FAIL_CLASS=""

log() { echo "[$(date -u +%H:%M:%S)] [$SCENARIO] $*" | tee -a "$E/runner.log"; }
fail() { FAIL_CLASS="${2:-product}"; log "FAIL($FAIL_CLASS) in phase '$PHASE': $1"; echo "$1" > "$E/failure-reason.txt"; exit 1; }

for v in APK EVIDENCE_DIR SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY OPERATOR_SECRET MAESTRO_OPERATOR_SECRET API_BASE; do
  test -n "${!v:-}" || { echo "missing env $v" >&2; exit 2; }
done

# ---------- adb helpers ----------
stabilize_adb() {
  adb start-server >/dev/null 2>&1 || true
  for _ in 1 2 3 4 5 6; do
    if [ "$(adb get-state 2>/dev/null)" = "device" ] && [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && adb shell true >/dev/null 2>&1; then return 0; fi
    adb kill-server >/dev/null 2>&1 || true; sleep 2; adb start-server >/dev/null 2>&1 || true; adb wait-for-device || true; sleep 4
  done
  return 1
}

prefs() { adb exec-out run-as "$PKG" cat "$PREFS_PATH" 2>/dev/null > "$E/prefs.xml.tmp" && mv "$E/prefs.xml.tmp" "$E/prefs.xml"; }
durable_json() { prefs; [ -s "$E/prefs.xml" ] && python3 "$EVID_PY" durable --prefs "$E/prefs.xml" 2>/dev/null || echo '{"verified":0,"total":0,"acked_parts":0,"batch_ids":[],"statuses":{}}'; }
jget() { python3 -c "import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2],0))" "$1" "$2"; }
snapshot() { durable_json | tee -a "$E/durable-timeline.jsonl" >/dev/null; durable_json > "$E/durable-$1.json"; }

wait_until() { # desc, timeout_s, command...
  local desc="$1" timeout="$2"; shift 2
  local end=$((SECONDS + timeout))
  while [ $SECONDS -lt $end ]; do
    if "$@"; then return 0; fi
    sleep 1
  done
  return 1
}
ledger_total_ge() { [ "$(jget "$(durable_json)" total)" -ge "$1" ]; }
acked_ge() { [ "$(jget "$(durable_json)" acked_parts)" -ge "$1" ]; }
all_verified() { local j; j="$(durable_json)"; [ "$(jget "$j" verified)" -ge "$TOTAL" ] && [ "$(jget "$j" total)" -ge "$TOTAL" ]; }
app_pid() { adb shell pidof "$PKG" 2>/dev/null | tr -d '\r' | awk '{print $1}'; }

capture_notification() { # label
  adb shell dumpsys notification --noredact 2>/dev/null > "$E/notification-$1.txt" || true
  python3 "$EVID_PY" notification --dump "$E/notification-$1.txt" > "$E/notification-$1.json" 2>/dev/null && return 0 || return 1
}
capture_service() { adb shell dumpsys activity services "$PKG" > "$E/services-$1.txt" 2>/dev/null || true; }

run_maestro() { # flow, extra -e args...
  local flow="$1"; shift
  local name; name="$(basename "$flow" .yaml)"
  stabilize_adb || fail "adb unstable before Maestro $name" infra
  maestro test "$HERE/$flow" "$@" --format junit --output "$E/$name.junit.xml" \
    --debug-output "$E/maestro-$name" --test-output-dir "$E/maestro-$name" --flatten-debug-output \
    >> "$E/maestro-$name.log" 2>&1
  local code=$?
  if [ $code -ne 0 ]; then
    # Classify from THIS flow's own logs only, and say which signature matched.
    local sig
    sig="$(grep -hsoE 'device offline|Device server died|DeviceServerDiedException|StatusRuntimeException: UNAVAILABLE|isn.t responding' "$E/maestro-$name.log" "$E/maestro-$name"/* 2>/dev/null | sort -u | head -3 | tr '\n' ';')"
    if [ -n "$sig" ]; then FAIL_CLASS="android-emulator-infra"; log "Maestro $name infra signature: $sig"; else FAIL_CLASS="harness-or-product-ui"; fi
    timeout 20s maestro hierarchy > "$E/hierarchy-after-$name.json" 2>/dev/null || true
    adb exec-out screencap -p > "$E/screen-after-$name.png" 2>/dev/null || true
    log "--- device-level diagnostics (focus, UI dump, ANR/RN/crash log) ---"
    {
      echo "focus: $(adb shell dumpsys window 2>/dev/null | grep -E 'mCurrentFocus|mFocusedApp' | head -2 | tr -d '\r' | tr '\n' ' ')"
      adb shell uiautomator dump /sdcard/bgq-ui.xml >/dev/null 2>&1
      adb exec-out cat /sdcard/bgq-ui.xml 2>/dev/null | python3 -c "
import re, sys
x = sys.stdin.read()
rows = re.findall(r'text=\"([^\"]*)\"[^>]*resource-id=\"([^\"]*)\"', x)
print('ui nodes:', len(rows))
for t, r in rows[:40]:
    if t or r: print('  id=%r text=%r' % (r, t[:70]))
" 2>&1 | head -50
      adb logcat -d -v time -t 1500 2>/dev/null | grep -E "ANR in|isn.t responding|Input dispatching timed out|ReactNativeJS|AndroidRuntime|FATAL EXCEPTION|SportReelBgUpload|StorageAccess|documentsui" | tail -n 40 | cut -c1-260
    } 2>&1 | sed 's/^/    /' | tee -a "$E/runner.log"
    log "--- Maestro $name failure summary ---"
    python3 "$REPO_ROOT/mobile/.maestro/upl01/summarize_failure.py" "$E" "" 2>&1 | head -80 | tee -a "$E/runner.log"
  fi
  return $code
}

ui_args() { echo -e "-e\nEXPECT_MIN_VERIFIED=$1\n-e\nEXPECT_TOTAL=$TOTAL\n-e\nEXPECT_FIRST_FILENAME=$FIRST_NAME"; }

# ---------- teardown / evidence always ----------
finish() {
  local code=$?
  set +e
  if [ -n "${BATCH_ID:-}" ]; then
    # Evidence is captured above; remove only this qualification batch (bgq_ fixtures) from production storage.
    python3 "$EVID_PY" cancel-batch --batch-id "$BATCH_ID" > "$E/cancel-batch.txt" 2>&1
    # Keep failed batches for diagnosis; only a passing scenario's fixtures are purged.
    [ $code -eq 0 ] && python3 "$EVID_PY" purge-batch --batch-id "$BATCH_ID" > "$E/purge-batch.txt" 2>&1
  fi
  adb logcat -d -v threadtime > "$E/logcat-full.txt" 2>/dev/null
  adb logcat -b crash -d > "$E/logcat-crash.txt" 2>/dev/null
  [ -n "${LOGCAT_PID:-}" ] && kill "$LOGCAT_PID" 2>/dev/null
  grep -E "SportReelBgUpload" "$E/logcat-full.txt" > "$E/bg-upload-events.log" 2>/dev/null
  python3 "$EVID_PY" part-log --logcat "$E/bg-upload-events.log" --out "$E/part-log-evidence.json" > "$E/part-log.txt" 2>&1 || { [ $code -eq 0 ] && code=1 && FAIL_CLASS="product" && echo "acknowledged part resent" > "$E/failure-reason.txt"; }
  snapshot final
  adb exec-out screencap -p > "$E/final-screen.png" 2>/dev/null
  if [ $code -ne 0 ]; then echo "${FAIL_CLASS:-product}" > "$E/failure-class.txt"; fi
  python3 - "$E" "$SCENARIO" "$code" "${PHASE}" <<'PY'
import json, os, pathlib, sys
root = pathlib.Path(sys.argv[1]); scenario, code, phase = sys.argv[2], int(sys.argv[3]), sys.argv[4]
secrets = [os.environ[k].encode() for k in ("OPERATOR_SECRET", "MAESTRO_OPERATOR_SECRET", "SUPABASE_SERVICE_ROLE_KEY", "R2_SECRET_ACCESS_KEY", "R2_ACCESS_KEY_ID") if os.environ.get(k)]
for p in root.rglob("*"):
    if p.is_file():
        d = p.read_bytes(); c = d
        for s in secrets: c = c.replace(s, b"[REDACTED]")
        if c != d: p.write_bytes(c)
def read(name):
    f = root / name
    return json.loads(f.read_text()) if f.exists() and f.stat().st_size else None
summary = {"scenario": scenario, "result": "PASS" if code == 0 else "FAIL", "failed_phase": None if code == 0 else phase,
           "failure_class": (root / "failure-class.txt").read_text().strip() if (root / "failure-class.txt").exists() else None,
           "failure_reason": (root / "failure-reason.txt").read_text().strip() if (root / "failure-reason.txt").exists() else None,
           "final_backend": (read("final-backend-evidence.json") or {}).get("counts"),
           "final_backend_result": (read("final-backend-evidence.json") or {}).get("result"),
           "gate_incomplete": (read("gate-incomplete-evidence.json") or {}).get("http_status"),
           "gate_ready_result": (read("gate-ready-evidence.json") or {}).get("result"),
           "part_log": {k: v for k, v in (read("part-log-evidence.json") or {}).items() if k in ("result", "reconciles", "resent_acknowledged")},
           "notes": (read("scenario-notes.json") or {})}
(root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
PY
  exit $code
}
trap finish EXIT

# ---------- setup ----------
PHASE="setup"
stabilize_adb || fail "device never became stable" infra
adb shell getprop ro.build.version.sdk | tr -d '\r' > "$E/android-sdk.txt"
adb shell getprop ro.build.fingerprint | tr -d '\r' > "$E/android-build.txt"
adb reverse tcp:8081 tcp:8081 || fail "adb reverse failed" infra
adb install -r "$APK" > "$E/install.txt" 2>&1 || fail "APK install failed" infra
sha256sum "$APK" | cut -d' ' -f1 > "$E/apk-sha256.txt"
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null || true
adb shell settings put global window_animation_scale 0 >/dev/null 2>&1; adb shell settings put global transition_animation_scale 0 >/dev/null 2>&1
adb shell cmd connectivity airplane-mode disable >/dev/null 2>&1 || true
adb shell svc power stayon true >/dev/null 2>&1 || true
adb logcat -c; adb logcat -G 16M >/dev/null 2>&1 || true
adb logcat -v threadtime SportReelBgUpload:I '*:S' > "$E/bg-upload-live.log" 2>/dev/null &
LOGCAT_PID=$!

adb shell rm -rf "/sdcard/Download/$FOLDER"; adb shell mkdir -p "/sdcard/Download/$FOLDER"
i=0; : > "$E/fixtures.txt"
for f in "$FIXTURE_DIR"/*.mp4; do
  adb push "$f" "/sdcard/Download/$FOLDER/$(basename "$f")" >/dev/null || fail "fixture push failed" infra
  echo "$(basename "$f") $(stat -c %s "$f")" >> "$E/fixtures.txt"; i=$((i+1))
done
[ "$i" -eq "$TOTAL" ] || fail "expected $TOTAL fixtures, found $i" harness
adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file:///sdcard/Download/$FOLDER" >/dev/null 2>&1 || true
FIRST_NAME="$(head -1 "$E/fixtures.txt" | cut -d' ' -f1 | sed 's/\.mp4$//')"
WINDOW_START="$(date -u -d '-60 seconds' +%Y-%m-%dT%H:%M:%SZ)"; echo "$WINDOW_START" > "$E/window-start-utc.txt"

# ---------- start (real UI) ----------
PHASE="start-upload"
run_maestro 00-start-upload.yaml -e BG_FOLDER="$FOLDER" || fail "could not start the batch through the UI (SAF picker / secret / selection)" "${FAIL_CLASS:-harness}"
PHASE="durable-ledger"
wait_until "durable ledger has $TOTAL jobs" 90 ledger_total_ge "$TOTAL" \
  || fail "native durable ledger never reached $TOTAL jobs (enqueue did not persist)" product
snapshot started
J="$(durable_json)"
BATCH_ID="$(python3 -c "import json,sys; ids=json.loads(sys.argv[1])['batch_ids']; print(ids[0] if len(ids)==1 else '')" "$J")"
[ -n "$BATCH_ID" ] || fail "jobs do not share exactly one stable batch id: $J" product
echo "$BATCH_ID" > "$E/batch-id.txt"; log "stable batch $BATCH_ID with $TOTAL jobs"

PHASE="gate-incomplete-probe"
python3 "$EVID_PY" gate-incomplete --batch-id "$BATCH_ID" --api-base "$API_BASE" --out "$E/gate-incomplete-evidence.json" || fail "pipeline start was not rejected for the incomplete batch" backend-or-product

PHASE="progress-before-perturbation"
wait_until "first parts acked" 240 acked_ge 3 || fail "no durable upload progress (3 acknowledged parts) within 240s" product
capture_notification started || fail "foreground upload notification not present while uploading" product
capture_service started
python3 - "$E" <<'PY'
import json, pathlib, sys
n = json.loads(pathlib.Path(sys.argv[1], "notification-started.json").read_text())
assert n["total"] == int(__import__("os").environ.get("BGQ_VIDEO_COUNT", "3")), n
PY
[ $? -eq 0 ] || fail "notification does not report the stable batch size" product
snapshot before-perturbation
BEFORE="$(durable_json)"; BEFORE_ACKED="$(jget "$BEFORE" acked_parts)"; BEFORE_VERIFIED="$(jget "$BEFORE" verified)"
PID_BEFORE="$(app_pid)"; echo "$PID_BEFORE" > "$E/pid-before.txt"
NOTES="$E/scenario-notes.json"; echo '{}' > "$NOTES"
note() { python3 - "$NOTES" "$1" "$2" <<'PY'
import json, sys
p, k, v = sys.argv[1:4]; d = json.load(open(p))
try: v = json.loads(v)
except Exception: pass
d[k] = v; json.dump(d, open(p, "w"), indent=2)
PY
}
note acked_before_perturbation "$BEFORE_ACKED"

kill_app() { adb shell "run-as $PKG kill -9 \$(pidof $PKG)" >/dev/null 2>&1 || adb shell "run-as $PKG sh -c 'kill -9 \$(pidof $PKG)'" >/dev/null 2>&1; sleep 1; }

# ---------- scenario ----------
PHASE="scenario-$SCENARIO"
case "$SCENARIO" in
  foreground-baseline)
    ;;
  home-background)
    adb shell input keyevent KEYCODE_HOME; sleep 3
    capture_notification after-home || fail "foreground notification disappeared after Home" product
    capture_service after-home
    wait_until "progress while backgrounded" 120 acked_ge $((BEFORE_ACKED + 2)) || all_verified || fail "no progress while the app was in the background" product
    snapshot while-background; note background_progress "$(durable_json)"
    ;;
  screen-off)
    adb shell input keyevent KEYCODE_SLEEP; sleep 3
    SCREEN="$(adb shell dumpsys power | grep -E 'mWakefulness=' | head -1)"; note screen_state_asleep "\"$SCREEN\""
    wait_until "progress with screen off" 120 acked_ge $((BEFORE_ACKED + 2)) || all_verified || fail "no progress while the screen was off" product
    capture_notification screen-off || true
    snapshot while-screen-off
    adb shell input keyevent KEYCODE_WAKEUP; adb shell wm dismiss-keyguard >/dev/null 2>&1; adb shell input keyevent 82; sleep 2
    run_maestro 02-screen-off-resume.yaml $(ui_args "$(jget "$(durable_json)" verified)" | tr '\n' ' ') || fail "UI did not show durable progress after screen off/on" "${FAIL_CLASS:-product}"
    ;;
  process-death-resume)
    adb shell input keyevent KEYCODE_HOME; sleep 2
    kill_app; sleep 2
    PID_AFTER_KILL="$(app_pid)"; note pid_after_kill "\"${PID_AFTER_KILL:-none}\""
    snapshot after-kill; AFTER_KILL="$(jget "$(durable_json)" acked_parts)"
    [ "$AFTER_KILL" -ge "$BEFORE_ACKED" ] || fail "durable acknowledged parts regressed after process death ($BEFORE_ACKED -> $AFTER_KILL)" product
    # Android must restart the worker on its own (no user launch). Record whether it did.
    if wait_until "autonomous resume after process death" 300 acked_ge $((AFTER_KILL + 2)) || all_verified; then note autonomous_resume true; else note autonomous_resume false; fail "worker did not durably resume after process death within 300s (no relaunch)" product; fi
    note pid_after_resume "\"$(app_pid)\""
    ;;
  relaunch-reconcile)
    adb shell input keyevent KEYCODE_HOME; sleep 2
    kill_app; sleep 1
    snapshot after-kill; MIN_VERIFIED="$(jget "$(durable_json)" verified)"
    run_maestro 03-process-restart.yaml $(ui_args "$MIN_VERIFIED" | tr '\n' ' ') || fail "relaunch UI did not reconcile the durable progress" "${FAIL_CLASS:-product}"
    snapshot after-relaunch; [ "$(jget "$(durable_json)" acked_parts)" -ge "$BEFORE_ACKED" ] || fail "durable progress regressed across relaunch" product
    ;;
  network-recovery)
    adb shell cmd connectivity airplane-mode enable >/dev/null 2>&1 || { adb shell svc wifi disable; adb shell svc data disable; }
    sleep 12; snapshot outage-start; OUT_START="$(jget "$(durable_json)" acked_parts)"
    sleep 35; snapshot outage-end; OUT_END="$(jget "$(durable_json)" acked_parts)"
    note outage_acked "{\"start\": $OUT_START, \"end\": $OUT_END}"
    [ "$OUT_END" -le $((OUT_START + 1)) ] || fail "progress continued while offline ($OUT_START -> $OUT_END): outage not effective" android-emulator-infra
    [ "$(jget "$(durable_json)" verified)" -lt "$TOTAL" ] || fail "batch finished during the outage window; outage did not interrupt multipart" harness
    capture_notification outage || true
    run_maestro 04-network-recovery.yaml || fail "UI showed failure/ungated state during the outage" "${FAIL_CLASS:-product}"
    adb shell cmd connectivity airplane-mode disable >/dev/null 2>&1 || { adb shell svc wifi enable; adb shell svc data enable; }
    adb shell input keyevent KEYCODE_HOME
    wait_until "automatic resume after reconnect" 240 acked_ge $((OUT_END + 2)) || all_verified || fail "upload did not resume automatically after the network returned" product
    note resumed_without_user_action true
    ;;
  worker-restart-retry)
    for round in 1 2; do
      adb shell input keyevent KEYCODE_HOME; sleep 1
      cur="$(jget "$(durable_json)" acked_parts)"
      kill_app; snapshot "after-kill-$round"
      wait_until "restart $round resumed" 300 acked_ge $((cur + 2)) || all_verified || fail "worker restart $round did not resume" product
      all_verified && break
    done
    # transient network flap to force the Result.retry() path as well
    if ! all_verified; then
      adb shell cmd connectivity airplane-mode enable >/dev/null 2>&1; sleep 8; adb shell cmd connectivity airplane-mode disable >/dev/null 2>&1
    fi
    note restarts_forced 2
    ;;
  *) fail "unknown scenario $SCENARIO" harness ;;
esac

# ---------- completion (app is NOT reopened for background scenarios) ----------
PHASE="completion"
wait_until "all $TOTAL videos verified" 900 all_verified || fail "batch did not reach $TOTAL verified videos (statuses: $(durable_json))" product
snapshot completed
capture_notification completed || true

PHASE="ui-final"
if [ "$SCENARIO" = "home-background" ]; then
  run_maestro 01-background.yaml $(ui_args "$TOTAL" | tr '\n' ' ') || fail "UI after returning from Home does not show the completed batch" "${FAIL_CLASS:-product}"
fi
run_maestro 05-final-ui.yaml $(ui_args "$TOTAL" | tr '\n' ' ') || fail "final UI state wrong (rows not all verified or run button not enabled)" "${FAIL_CLASS:-product}"

PHASE="backend-final"
python3 "$EVID_PY" final --batch-id "$BATCH_ID" --expected "$TOTAL" --out "$E/final-backend-evidence.json" || fail "backend/R2 final evidence failed (duplicates, missing or unverified)" backend-or-product
PHASE="gate-ready"
python3 "$EVID_PY" gate-ready --batch-id "$BATCH_ID" --expected "$TOTAL" --out "$E/gate-ready-evidence.json" || fail "verified-batch gate does not accept the fully verified batch" backend-or-product
PHASE="done"
log "scenario PASS"
exit 0
