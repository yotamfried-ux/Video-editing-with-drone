#!/usr/bin/env bash
# .claude/hooks/session-start.sh
# Idempotent, non-fatal session startup script for ephemeral Claude Code containers.
# Installs pinned Engineering-OS tooling (rtk, graphify) and extracts code graph.

set -u

# Only run in remote Claude Code cloud containers
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Ensure ~/.local/bin is on PATH
export PATH="${HOME}/.local/bin:${PATH}"
mkdir -p "${HOME}/.local/bin"

log_info() {
  echo "[session-start.sh] $*" >&2
}

log_warn() {
  echo "[session-start.sh] WARNING: $*" >&2
}

# 1. Install pinned RTK (0.49.0) if missing or version differs
install_rtk() {
  local target_ver="0.49.0"
  if command -v rtk >/dev/null 2>&1; then
    local current_ver
    current_ver="$(rtk --version 2>/dev/null || true)"
    if echo "${current_ver}" | grep -q "${target_ver}"; then
      return 0
    fi
  fi

  log_info "Installing rtk v${target_ver}..."
  local temp_dir
  temp_dir="$(mktemp -d -t eos-rtk-XXXXXX 2>/dev/null || mktemp -d)"
  if curl -fsSL "https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh" -o "${temp_dir}/install.sh"; then
    (export RTK_VERSION="v${target_ver}"; sh "${temp_dir}/install.sh") || log_warn "rtk installer script failed"
  else
    log_warn "Failed to download rtk installer script"
  fi
  rm -rf "${temp_dir}"

  if command -v rtk >/dev/null 2>&1; then
    rtk init -g >/dev/null 2>&1 || true
  fi
}

# 2. Install pinned Graphify (0.9.66) if missing or version differs
install_graphify() {
  local target_ver="0.9.66"
  if command -v graphify >/dev/null 2>&1 && command -v graphify-mcp >/dev/null 2>&1; then
    local current_ver
    current_ver="$(graphify --version 2>/dev/null || true)"
    if echo "${current_ver}" | grep -q "${target_ver}"; then
      return 0
    fi
  fi

  log_info "Installing graphify ${target_ver}..."
  if command -v uv >/dev/null 2>&1; then
    UV_TOOL_BIN_DIR="${HOME}/.local/bin" uv tool install --force "graphifyy[mcp]==${target_ver}" || log_warn "uv tool install graphify failed"
  else
    log_warn "uv is required for graphify installation but was not found"
  fi
}

# 3. Ensure code-only graph is built if missing or empty
ensure_graph() {
  local graph_file="graphify-out/graph.json"
  if [ -s "${graph_file}" ]; then
    return 0
  fi

  if command -v graphify >/dev/null 2>&1; then
    log_info "Extracting code-only graph..."
    graphify extract . --code-only || log_warn "graphify extract failed"
    if [ -d "graphify-out" ]; then
      local head_sha
      head_sha="$(git rev-parse HEAD 2>/dev/null || echo "non-git")"
      echo "${head_sha}" > "graphify-out/.engineering-os-head"
    fi
  else
    log_warn "graphify CLI missing; cannot extract graph"
  fi
}

# 4. Exclude graphify-out/ from git tracking
exclude_graph_output() {
  if [ -d ".git" ]; then
    mkdir -p .git/info
    if [ -f .git/info/exclude ]; then
      if ! grep -q "^graphify-out/" .git/info/exclude; then
        echo "graphify-out/" >> .git/info/exclude
      fi
    else
      echo "graphify-out/" > .git/info/exclude
    fi
  fi
}

# Execute all steps defensively: always exit 0
main() {
  install_rtk || log_warn "RTK provisioning step failed"
  install_graphify || log_warn "Graphify provisioning step failed"
  ensure_graph || log_warn "Graph extraction step failed"
  exclude_graph_output || log_warn "Git exclude step failed"
  exit 0
}

main "$@"
