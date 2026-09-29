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
  # stdout only, first semver token: JVM tools may print banners before the version.
  actual="$("$tool" --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
  if [[ "$actual" == "$expected" ]]; then
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

current_head="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"
graph_stamp="$ROOT/graphify-out/.sportreel-head"
if [[ -s "$ROOT/graphify-out/graph.json" ]] &&
   [[ -f "$graph_stamp" ]] &&
   [[ "$(cat "$graph_stamp")" == "$current_head" ]]; then
  ok "Graphify graph matches current checkout $current_head"
else
  bad "Graphify graph is missing or stale; run the bootstrap"
fi

check_version maestro "$MAESTRO_VERSION"

if command -v node >/dev/null 2>&1 && command -v npx >/dev/null 2>&1; then
  ok "Node/npx available for project-scoped browser MCPs"
else
  bad "Node and npx are required for Playwright and Chrome DevTools MCPs"
fi

if python3 - "$ROOT/.mcp.json" <<'PY'
import json
import sys

path = sys.argv[1]
cfg = json.load(open(path, encoding="utf-8"))
servers = cfg.get("mcpServers", {})
expected = {
    "graphify": ("${HOME}/.local/bin/graphify-mcp", ["${PWD}/graphify-out/graph.json"]),
    "maestro": ("maestro", ["mcp"]),
    "playwright": ("npx", ["-y", "@playwright/mcp@latest"]),
    "chrome-devtools": ("npx", ["-y", "chrome-devtools-mcp@latest"]),
}
for name, (command, args) in expected.items():
    server = servers.get(name)
    if not isinstance(server, dict):
        raise SystemExit(f"missing MCP server: {name}")
    if server.get("command") != command or server.get("args") != args:
        raise SystemExit(f"unexpected MCP config for {name}: {server!r}")
PY
then
  ok "project .mcp.json declares Graphify, Maestro, Playwright and Chrome DevTools"
else
  bad "project .mcp.json is missing or misconfigures a required qualification MCP"
fi

if command -v claude >/dev/null 2>&1; then
  mcp_list="$(cd "$ROOT" && claude mcp list 2>/dev/null || true)"
  for mcp_name in graphify maestro playwright chrome-devtools; do
    if grep -qi "$mcp_name" <<<"$mcp_list"; then
      ok "Claude Code sees the $mcp_name MCP entry"
    else
      note "$mcp_name is committed in .mcp.json but this host/session has not trusted or loaded it yet."
    fi
  done
fi

if grep -qxF 'graphify-out/' "$ROOT/.gitignore"; then
  ok "generated Graphify output is excluded from Git"
else
  bad "graphify-out/ is not excluded in .gitignore"
fi

if (( failures > 0 )); then
  printf '\nAgent tooling verification failed with %d issue(s).\n' "$failures" >&2
  exit 1
fi

note "Bootstrap-managed tools and project MCP registrations are ready."
note "Browser/mobile MCP live handshakes still require a compatible host plus browser/device."
