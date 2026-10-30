#!/usr/bin/env bash
# .claude/hooks/session-start.sh
# Idempotent, non-fatal session startup hook for ephemeral Claude Code cloud containers.
# Foreground: install pinned rtk (a few seconds). Background worker: install pinned graphify and
# build the code graph, so session start never waits on it. Nothing is printed to stdout (stdout of a
# SessionStart hook is injected into the model context); details go to ${TMPDIR:-/tmp}/eos-session-start.log.

set -u

# Only run in remote Claude Code cloud containers
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

RTK_TARGET_VER="0.49.0"
GRAPHIFY_TARGET_VER="0.9.66"
LOG_FILE="${TMPDIR:-/tmp}/eos-session-start.log"
LOCK_FILE="${TMPDIR:-/tmp}/eos-graphify.lock"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"

# Ensure ~/.local/bin is on PATH
export PATH="${HOME}/.local/bin:${PATH}"
mkdir -p "${HOME}/.local/bin"

log_event() {
  echo "[$(date -u +%FT%TZ)] $*" >> "${LOG_FILE}"
}

install_rtk() {
  if command -v rtk >/dev/null 2>&1 && rtk --version 2>/dev/null | grep -q "${RTK_TARGET_VER}"; then
    log_event "RTK v${RTK_TARGET_VER} is already installed."
    return 0
  fi

  log_event "Installing RTK v${RTK_TARGET_VER}..."
  local temp_dir
  temp_dir="$(mktemp -d -t eos-rtk-XXXXXX 2>/dev/null || mktemp -d)"
  if curl -fsSL "https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh" -o "${temp_dir}/install.sh" >> "${LOG_FILE}" 2>&1; then
    (export RTK_VERSION="v${RTK_TARGET_VER}"; sh "${temp_dir}/install.sh") >> "${LOG_FILE}" 2>&1 || log_event "RTK install script failed"
  else
    log_event "Failed to download RTK installer script"
  fi
  rm -rf "${temp_dir}"

  if command -v rtk >/dev/null 2>&1; then
    mkdir -p "${HOME}/.claude"
    rtk init -g >> "${LOG_FILE}" 2>&1 || true
    log_event "RTK installed."
  fi
}

install_graphify() {
  if command -v graphify >/dev/null 2>&1 && command -v graphify-mcp >/dev/null 2>&1 \
     && graphify --version 2>/dev/null | grep -q "${GRAPHIFY_TARGET_VER}"; then
    log_event "Graphify ${GRAPHIFY_TARGET_VER} is already installed."
    return 0
  fi

  if ! command -v uv >/dev/null 2>&1; then
    log_event "uv not found; skipping graphify install"
    return 0
  fi
  log_event "Installing Graphify ${GRAPHIFY_TARGET_VER}..."
  if UV_TOOL_BIN_DIR="${HOME}/.local/bin" uv tool install --force "graphifyy[mcp]==${GRAPHIFY_TARGET_VER}" >> "${LOG_FILE}" 2>&1; then
    log_event "Graphify installed."
  else
    log_event "uv tool install graphify failed"
  fi
}

exclude_graph_output() {
  if [ -d "${PROJECT_DIR}/.git" ]; then
    mkdir -p "${PROJECT_DIR}/.git/info"
    local exclude_file="${PROJECT_DIR}/.git/info/exclude"
    if ! grep -qs "^graphify-out/" "${exclude_file}"; then
      echo "graphify-out/" >> "${exclude_file}"
    fi
  fi
}

current_head() {
  (cd "${PROJECT_DIR}" && git rev-parse HEAD 2>/dev/null) || echo "non-git"
}

graph_is_current() {
  local head_sha="$1"
  local graph_file="${PROJECT_DIR}/graphify-out/graph.json"
  local stamp_file="${PROJECT_DIR}/graphify-out/.engineering-os-head"
  [ -s "${graph_file}" ] && [ -f "${stamp_file}" ] && [ "$(cat "${stamp_file}" 2>/dev/null)" = "${head_sha}" ]
}

# Background worker: runs detached from the hook; owns the lock with its own PID.
graph_worker() {
  local head_sha
  head_sha="$(current_head)"
  graph_is_current "${head_sha}" && exit 0

  if [ -f "${LOCK_FILE}" ]; then
    local old_pid
    old_pid="$(cat "${LOCK_FILE}" 2>/dev/null || true)"
    if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
      log_event "Worker already running (PID ${old_pid})."
      exit 0
    fi
  fi
  echo "$$" > "${LOCK_FILE}"
  trap 'rm -f "${LOCK_FILE}"' EXIT

  install_graphify
  if command -v graphify >/dev/null 2>&1; then
    log_event "Extracting code-only graph for HEAD ${head_sha}..."
    cd "${PROJECT_DIR}" || exit 0
    if graphify extract . --code-only >> "${LOG_FILE}" 2>&1; then
      echo "${head_sha}" > "graphify-out/.engineering-os-head"
      log_event "Graph extraction complete for ${head_sha}."
    else
      log_event "graphify extract failed"
    fi
  fi
  exit 0
}

if [ "${1:-}" = "--graph-worker" ]; then
  graph_worker
fi

main() {
  log_event "Session start hook triggered (PID $$)."
  install_rtk || true
  exclude_graph_output || true
  if ! graph_is_current "$(current_head)"; then
    # Detach fully (new session, no stdin/stdout) so the worker survives the hook process exiting.
    if command -v setsid >/dev/null 2>&1; then
      setsid nohup bash "$0" --graph-worker </dev/null >/dev/null 2>&1 &
    else
      nohup bash "$0" --graph-worker </dev/null >/dev/null 2>&1 &
    fi
  fi
  exit 0
}

if ! main "$@"; then
  echo "[session-start.sh] Warning: provisioning encountered errors; details in ${LOG_FILE}" >&2
  exit 0
fi
