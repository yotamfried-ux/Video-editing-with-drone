#!/usr/bin/env bash
# .claude/hooks/session-start.sh
# Idempotent, non-fatal session startup hook for ephemeral Claude Code cloud containers.
# Provisions pinned Engineering-OS tooling (rtk v0.49.0, graphify 0.9.66) and builds graph in background.

set -u

# Only run in remote Claude Code cloud containers
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

LOG_FILE="${TMPDIR:-/tmp}/eos-session-start.log"
LOCK_FILE="${TMPDIR:-/tmp}/eos-graphify.lock"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"

# Ensure ~/.local/bin is on PATH
export PATH="${HOME}/.local/bin:${PATH}"
mkdir -p "${HOME}/.local/bin"

log_event() {
  echo "[$(date -u +%FT%TZ)] $*" >> "${LOG_FILE}"
}

# 1. Install pinned RTK (0.49.0) if missing or mismatched
install_rtk() {
  local target_ver="0.49.0"
  if command -v rtk >/dev/null 2>&1; then
    local current_ver
    current_ver="$(rtk --version 2>/dev/null || true)"
    if echo "${current_ver}" | grep -q "${target_ver}"; then
      log_event "RTK v${target_ver} is already installed."
      return 0
    fi
  fi

  log_event "Installing RTK v${target_ver}..."
  local temp_dir
  temp_dir="$(mktemp -d -t eos-rtk-XXXXXX 2>/dev/null || mktemp -d)"
  if curl -fsSL "https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh" -o "${temp_dir}/install.sh" >> "${LOG_FILE}" 2>&1; then
    (export RTK_VERSION="v${target_ver}"; sh "${temp_dir}/install.sh") >> "${LOG_FILE}" 2>&1 || log_event "RTK install script failed"
  else
    log_event "Failed to download RTK installer script"
  fi
  rm -rf "${temp_dir}"

  if command -v rtk >/dev/null 2>&1; then
    rtk init -g >> "${LOG_FILE}" 2>&1 || true
    log_event "RTK v${target_ver} installed successfully."
  fi
}

# 2. Install pinned Graphify (0.9.66) if missing or mismatched
install_graphify() {
  local target_ver="0.9.66"
  if command -v graphify >/dev/null 2>&1 && command -v graphify-mcp >/dev/null 2>&1; then
    local current_ver
    current_ver="$(graphify --version 2>/dev/null || true)"
    if echo "${current_ver}" | grep -q "${target_ver}"; then
      log_event "Graphify ${target_ver} is already installed."
      return 0
    fi
  fi

  log_event "Installing Graphify ${target_ver}..."
  if command -v uv >/dev/null 2>&1; then
    UV_TOOL_BIN_DIR="${HOME}/.local/bin" uv tool install --force "graphifyy[mcp]==${target_ver}" >> "${LOG_FILE}" 2>&1 || log_event "uv tool install graphify failed"
    log_event "Graphify ${target_ver} installed."
  else
    log_event "uv not found; skipping graphify install"
  fi
}

# 3. Exclude graphify-out/ from local git tracking
exclude_graph_output() {
  if [ -d "${PROJECT_DIR}/.git" ]; then
    mkdir -p "${PROJECT_DIR}/.git/info"
    local exclude_file="${PROJECT_DIR}/.git/info/exclude"
    if [ -f "${exclude_file}" ]; then
      if ! grep -q "^graphify-out/" "${exclude_file}"; then
        echo "graphify-out/" >> "${exclude_file}"
      fi
    else
      echo "graphify-out/" > "${exclude_file}"
    fi
  fi
}

# 4. Trigger asynchronous background graph extraction if missing or stale
trigger_graph_build() {
  local head_sha
  head_sha="$(cd "${PROJECT_DIR}" && git rev-parse HEAD 2>/dev/null || echo "non-git")"
  local graph_file="${PROJECT_DIR}/graphify-out/graph.json"
  local stamp_file="${PROJECT_DIR}/graphify-out/.engineering-os-head"

  # Check if graph is already up to date with HEAD
  if [ -s "${graph_file}" ] && [ -f "${stamp_file}" ]; then
    local current_stamp
    current_stamp="$(cat "${stamp_file}" 2>/dev/null || true)"
    if [ "${current_stamp}" = "${head_sha}" ]; then
      log_event "Code graph is current with HEAD (${head_sha})."
      return 0
    fi
  fi

  # Check lock file to avoid concurrent graphify runs
  if [ -f "${LOCK_FILE}" ]; then
    local old_pid
    old_pid="$(cat "${LOCK_FILE}" 2>/dev/null || true)"
    if [ -n "${old_pid}" ] && kill -0 "${old_pid}" 2>/dev/null; then
      log_event "Graph extraction already running (PID ${old_pid})."
      return 0
    fi
  fi

  log_event "Spawning background graph extraction for HEAD ${head_sha}..."
  (
    echo "$$" > "${LOCK_FILE}"
    cd "${PROJECT_DIR}" || exit 0
    if command -v graphify >/dev/null 2>&1; then
      graphify extract . --code-only >> "${LOG_FILE}" 2>&1
      if [ -d "graphify-out" ]; then
        echo "${head_sha}" > "graphify-out/.engineering-os-head"
        echo "[$(date -u +%FT%TZ)] Background graph extraction complete for ${head_sha}" >> "${LOG_FILE}"
      fi
    fi
    rm -f "${LOCK_FILE}"
  ) >/dev/null 2>&1 &
}

main() {
  log_event "Session start hook triggered (PID $$)."
  install_rtk || true
  install_graphify || true
  exclude_graph_output || true
  trigger_graph_build || true
  exit 0
}

if ! main "$@"; then
  echo "[session-start.sh] Warning: provisioning encountered errors; details in ${LOG_FILE}" >&2
  exit 0
fi
