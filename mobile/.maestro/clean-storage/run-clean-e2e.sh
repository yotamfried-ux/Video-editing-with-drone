#!/usr/bin/env bash
# Scenarios A, B, C + security against the real backend, driven through the real Android UI.
set -euo pipefail
FLOWS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$FLOWS/../../.." && pwd)"
# shellcheck source=common.sh
source "$FLOWS/common.sh"
for v in APK EVIDENCE_DIR API_BASE OPERATOR_SECRET MAESTRO_OPERATOR_SECRET SUPABASE_URL SUPABASE_SERVICE_KEY R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
  test -n "${!v:-}" || { echo "clean-e2e: required env $v is empty" >&2; exit 2; }
done
mkdir -p "$EVIDENCE_DIR"
E2E="python3 $REPO_ROOT/scripts/video_storage_cleanup_e2e.py"
trap 'code=$?; [ $code -ne 0 ] && collect_device_state; scrub_secrets || code=3; exit $code' EXIT

stabilize_adb_device "APK install"
adb reverse tcp:8081 tcp:8081
adb install -r "$APK" > "$EVIDENCE_DIR/install.txt"
stabilize_adb_device "Maestro"

echo "== security probes =="
$E2E api-security 2>&1 | tee "$EVIDENCE_DIR/api-security.txt"

echo "== seed populated state =="
$E2E state --out "$EVIDENCE_DIR/state-00-before-seed.json" > /dev/null
$E2E seed --manifest "$EVIDENCE_DIR/manifest.json" | tee "$EVIDENCE_DIR/seed.txt"
$E2E assert-populated --manifest "$EVIDENCE_DIR/manifest.json" --baseline "$EVIDENCE_DIR/state-01-populated.json" | tee "$EVIDENCE_DIR/assert-populated.txt"

echo "== Scenario A: populated -> clean (Android UI) =="
run_flow 01-clean-populated.yaml
$E2E assert-clean --manifest "$EVIDENCE_DIR/manifest.json" --baseline "$EVIDENCE_DIR/state-01-populated.json" --out "$EVIDENCE_DIR/state-02-after-clean.json" | tee "$EVIDENCE_DIR/assert-clean.txt"

echo "== Scenario B: clean -> clean (Android UI) =="
run_flow 02-clean-again.yaml
$E2E assert-clean --manifest "$EVIDENCE_DIR/manifest.json" --baseline "$EVIDENCE_DIR/state-01-populated.json" --out "$EVIDENCE_DIR/state-03-after-second-clean.json" | tee "$EVIDENCE_DIR/assert-clean-second.txt"

echo "== Scenario C: isolation of a new batch =="
$E2E isolation --manifest "$EVIDENCE_DIR/manifest.json" --out "$EVIDENCE_DIR/isolation.json" | tee "$EVIDENCE_DIR/isolation.txt"
