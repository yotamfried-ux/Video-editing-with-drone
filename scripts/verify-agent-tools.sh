#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/tooling/agent-tools.lock.env"

failures=0

ok() { printf 'PASS  %s\n' "$*"; }
bad() { printf 'FAIL  %s\n' "$*" >&2; failures=$((failures + 1)); }
note() { printf 'INFO  %s\n' "$*"; }

check_version() {
  local tool="$1" expected="$2"
  if ! command -v "$tool" >/dev/null 2>&1; then
    bad "$tool is not installed"
    return
  fi
  local actual
  actual="$("$tool" --version 2>&1 | head -n 1 || true)"
  if [[ "$actual" == *"$expected"* ]]; then
    ok "$tool $expected"
  else
    bad "$tool version mismatch (expected $expected; got: $actual)"
  fi
}

if command -v claude >/dev/null 2>&1; then
  ok "Claude Code CLI available"
  plugins="$(claude plugin list 2>/dev/null || true)"
  if grep -qi 'superpowers' <<<"$plugins"; then
    ok "Superpowers plugin installed (qualified baseline: $SUPERPOWERS_TESTED_VERSION)"
  else
    bad "Superpowers plugin is not installed"
  fi
else
  bad "Claude Code CLI is not available"
fi

check_version rtk "$RTK_VERSION"
check_version graphify "$GRAPHIFY_VERSION"

if command -v graphify-mcp >/dev/null 2>&1; then
  ok "graphify-mcp entry point available"
else
  bad "graphify-mcp entry point is not available"
fi

if [[ -s "$ROOT/graphify-out/graph.json" ]]; then
  ok "Graphify code graph exists for this checkout"
else
  bad "Graphify graph is missing; run the bootstrap"
fi

if command -v claude >/dev/null 2>&1; then
  mcp_list="$(claude mcp list 2>/dev/null || true)"
  if grep -qi 'graphify' <<<"$mcp_list"; then
    ok "Graphify MCP registered"
  else
    bad "Graphify MCP is not registered for this checkout"
  fi
fi

check_version maestro "$MAESTRO_VERSION"

if grep -qxF 'graphify-out/' "$ROOT/.gitignore"; then
  ok "generated Graphify output is excluded from Git"
else
  bad "graphify-out/ is not excluded in .gitignore"
fi

if (( failures > 0 )); then
  printf '\nAgent tooling verification failed with %d issue(s).\n' "$failures" >&2
  exit 1
fi

note "All persistent/bootstrap-managed SportReel agent tools are ready."
