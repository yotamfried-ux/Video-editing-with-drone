#!/usr/bin/env bash
# SessionStart hook for Claude Code cloud sessions: run the project's own agent-tool bootstrap
# (scripts/bootstrap-agent-tools.sh, versions pinned in tooling/agent-tools.lock.env) in the background.
# The bootstrap is idempotent (every component already installed => a few seconds). Nothing is printed to
# stdout, because stdout of a SessionStart hook is injected into the model context; output goes to
# ${TMPDIR:-/tmp}/eos-session-start.log. Always exits 0, so a failed install never blocks a session.

set -u

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
BOOTSTRAP="${PROJECT_DIR}/scripts/bootstrap-agent-tools.sh"
LOG_FILE="${TMPDIR:-/tmp}/eos-session-start.log"
LOCK_FILE="${TMPDIR:-/tmp}/eos-bootstrap.lock"

[ -f "${BOOTSTRAP}" ] || exit 0

if [ -f "${LOCK_FILE}" ]; then
  old_pid="$(cat "${LOCK_FILE}" 2>/dev/null || true)"
  if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
    exit 0
  fi
fi

run_bootstrap() {
  echo "$$" > "${LOCK_FILE}"
  trap 'rm -f "${LOCK_FILE}"' EXIT
  echo "[$(date -u +%FT%TZ)] bootstrap start" >> "${LOG_FILE}"
  cd "${PROJECT_DIR}" || exit 0
  if bash "${BOOTSTRAP}" >> "${LOG_FILE}" 2>&1; then
    echo "[$(date -u +%FT%TZ)] bootstrap ok" >> "${LOG_FILE}"
  else
    echo "[$(date -u +%FT%TZ)] bootstrap failed (exit $?); see log above" >> "${LOG_FILE}"
  fi
  exit 0
}

if [ "${1:-}" = "--run" ]; then
  run_bootstrap
fi

# Detach fully (new session, no stdin/stdout) so the bootstrap survives the hook process exiting.
if command -v setsid >/dev/null 2>&1; then
  setsid nohup bash "$0" --run </dev/null >/dev/null 2>&1 &
else
  nohup bash "$0" --run </dev/null >/dev/null 2>&1 &
fi
exit 0
