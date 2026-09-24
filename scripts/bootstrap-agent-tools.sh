#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/tooling/agent-tools.lock.env"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export UV_TOOL_BIN_DIR="$HOME/.local/bin"
mkdir -p "$HOME/.local/bin"

say() { printf '\n==> %s\n' "$*"; }
have_version() {
  local tool="$1" expected="$2"
  command -v "$tool" >/dev/null 2>&1 &&
    "$tool" --version 2>&1 | head -n 1 | grep -Fq "$expected"
}

say "SportReel agent-tool bootstrap"
printf 'Project: %s\n' "$ROOT"

if ! command -v claude >/dev/null 2>&1; then
  echo "Claude Code CLI is required for Superpowers and project MCP discovery." >&2
  exit 2
fi

# Superpowers is installed through Claude's official plugin marketplace.
# The marketplace controls the current release; the lock records the live-
# qualified baseline so upgrades can be re-qualified intentionally.
if claude plugin list 2>/dev/null | grep -qi 'superpowers'; then
  say "Superpowers already installed; skipping"
else
  say "Installing Superpowers (qualified baseline $SUPERPOWERS_TESTED_VERSION)"
  claude plugin marketplace add "$SUPERPOWERS_MARKETPLACE" >/dev/null 2>&1 || true
  claude plugin install "$SUPERPOWERS_PLUGIN"
  echo "Superpowers skills become available to newly started Claude sessions."
fi

if have_version rtk "$RTK_VERSION"; then
  say "RTK $RTK_VERSION already installed; skipping"
else
  say "Installing RTK $RTK_VERSION"
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  curl -fsSL     https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh     -o "$tmp"
  RTK_VERSION="v$RTK_VERSION" sh "$tmp"
  rm -f "$tmp"
  trap - EXIT
fi

say "Ensuring RTK Claude hook is registered"
rtk init -g --auto-patch >/dev/null

if have_version graphify "$GRAPHIFY_VERSION" && command -v graphify-mcp >/dev/null 2>&1; then
  say "Graphify $GRAPHIFY_VERSION already installed; skipping package install"
else
  say "Installing Graphify $GRAPHIFY_VERSION with MCP support"
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to install the pinned Graphify tool safely." >&2
    exit 2
  fi
  uv tool install --force "$GRAPHIFY_PACKAGE[mcp]==$GRAPHIFY_VERSION"
fi

cd "$ROOT"
current_head="$(git rev-parse HEAD)"
graph_stamp="$ROOT/graphify-out/.sportreel-head"
if [[ -s "$ROOT/graphify-out/graph.json" ]] &&
   [[ -f "$graph_stamp" ]] &&
   [[ "$(cat "$graph_stamp")" == "$current_head" ]]; then
  say "Graphify graph already matches $current_head; skipping rebuild"
else
  say "Building checkout-local Graphify code graph for $current_head"
  graphify extract . --code-only
  printf '%s\n' "$current_head" > "$graph_stamp"
fi

say "Graphify MCP is persisted by project .mcp.json"
echo "Claude Code may request a one-time trust approval for project MCP servers on a fresh host."

if have_version maestro "$MAESTRO_VERSION"; then
  say "Maestro $MAESTRO_VERSION already installed; skipping"
else
  say "Installing Maestro $MAESTRO_VERSION"
  if ! command -v java >/dev/null 2>&1; then
    echo "Java 17+ is required by Maestro." >&2
    exit 2
  fi
  if ! command -v unzip >/dev/null 2>&1; then
    echo "unzip is required to install Maestro." >&2
    exit 2
  fi
  install_root="$HOME/.cache/sportreel-tools/maestro/$MAESTRO_VERSION"
  zip_file="$(mktemp --suffix=.zip)"
  trap 'rm -f "$zip_file"' EXIT
  curl -fsSL     "https://github.com/mobile-dev-inc/Maestro/releases/download/cli-$MAESTRO_VERSION/maestro.zip"     -o "$zip_file"
  rm -rf "$install_root"
  mkdir -p "$install_root"
  unzip -q "$zip_file" -d "$install_root"
  ln -sfn "$install_root/maestro/bin/maestro" "$HOME/.local/bin/maestro"
  rm -f "$zip_file"
  trap - EXIT
fi

say "Verifying final tool state"
exec "$ROOT/scripts/verify-agent-tools.sh"
