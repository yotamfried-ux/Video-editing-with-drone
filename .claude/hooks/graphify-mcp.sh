#!/usr/bin/env bash
# .claude/hooks/graphify-mcp.sh
# Launcher for the `graphify` MCP server (see .mcp.json). A fresh cloud container has neither the
# graphify binary nor graphify-out/graph.json when MCP servers start, because session-start.sh installs
# and builds them in the background. This wrapper waits for that work (or does it itself) and then
# execs the real server, so the first session of a container gets a working graph tool.
#
# stdout is the MCP protocol channel: nothing may be written to it before the exec.

set -u

export PATH="${HOME}/.local/bin:${PATH}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
GRAPH="${PROJECT_DIR}/graphify-out/graph.json"
LOCK_FILE="${TMPDIR:-/tmp}/eos-graphify.lock"
LOG_FILE="${TMPDIR:-/tmp}/eos-session-start.log"
WAIT_SECONDS="${GRAPHIFY_MCP_WAIT_SECONDS:-150}"

say() { echo "[graphify-mcp.sh] $*" >&2; }

ready() { command -v graphify-mcp >/dev/null 2>&1 && [ -s "${GRAPH}" ]; }

if ! ready; then
  sleep 3  # let the SessionStart hook launch its worker first, so we do not start a duplicate
  if ! ready && [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] && [ -x "${PROJECT_DIR}/.claude/hooks/session-start.sh" ]; then
    worker_pid="$(cat "${LOCK_FILE}" 2>/dev/null || true)"
    if [ -z "${worker_pid}" ] || ! kill -0 "${worker_pid}" 2>/dev/null; then
      # Nobody is provisioning yet (the hook has not run, or it failed): do it here, bounded by the wait.
      say "no provisioning in progress; running the graph worker"
      ( CLAUDE_PROJECT_DIR="${PROJECT_DIR}" timeout "${WAIT_SECONDS}" \
          bash "${PROJECT_DIR}/.claude/hooks/session-start.sh" --graph-worker >>"${LOG_FILE}" 2>&1 ) </dev/null &
      sleep 1
    fi
    say "waiting up to ${WAIT_SECONDS}s for graphify and the graph"
    waited=0
    while ! ready && [ "${waited}" -lt "${WAIT_SECONDS}" ]; do
      sleep 2
      waited=$((waited + 2))
    done
  fi
fi

if ! command -v graphify-mcp >/dev/null 2>&1; then
  say "graphify-mcp is not installed; see ${LOG_FILE}"
  exit 1
fi
if [ ! -s "${GRAPH}" ]; then
  say "no graph at ${GRAPH}; run: graphify extract . --code-only"
  exit 1
fi

exec graphify-mcp "${GRAPH}"
