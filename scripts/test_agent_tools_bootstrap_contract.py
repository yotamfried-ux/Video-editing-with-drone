#!/usr/bin/env python3
"""Static safety/portability contract for the SportReel agent-tool bootstrap."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TOOLS = json.loads((ROOT / ".engineering-os-tools.json").read_text(encoding="utf-8"))
BOOT = (ROOT / "scripts/bootstrap-agent-tools.sh").read_text(encoding="utf-8")
VERIFY = (ROOT / "scripts/verify-agent-tools.sh").read_text(encoding="utf-8")
LOCK = (ROOT / "tooling/agent-tools.lock.env").read_text(encoding="utf-8")
IGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")
MCP_TEXT = (ROOT / ".mcp.json").read_text(encoding="utf-8")
MCP = json.loads(MCP_TEXT)
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
FRICTION = (ROOT / "docs/AI-FRICTION-LOG.md").read_text(encoding="utf-8")


def test_ai_friction_log_is_durable_project_policy() -> None:
    assert "docs/AI-FRICTION-LOG.md" in CLAUDE
    for concept in ("slow", "context/token", "complexity", "automation/caching/parallelism"):
        assert concept in CLAUDE
    for section in ("Observed behavior", "Impact", "Evidence", "Simpler / faster alternative", "Follow-up"):
        assert section in FRICTION
    assert "Never record secrets" in FRICTION


def test_project_declares_every_managed_tool() -> None:
    assert PROJECT_TOOLS["tools"] == [
        "superpowers",
        "rtk",
        "graphify",
        "maestro",
        "playwright-mcp",
        "chrome-devtools-mcp",
    ]


def test_versions_are_explicit() -> None:
    expected = {
        "SUPERPOWERS_TESTED_VERSION": "6.4.1",
        "RTK_VERSION": "0.49.0",
        "GRAPHIFY_VERSION": "0.9.66",
        "MAESTRO_VERSION": "2.10.0",
    }
    for key, value in expected.items():
        assert f"{key}={value}" in LOCK


def test_bootstrap_is_idempotent_by_construction() -> None:
    assert "have_version" in BOOT
    assert "already installed; skipping" in BOOT
    assert "already matches" in BOOT
    assert "claude plugin list" in BOOT
    assert ".sportreel-head" in BOOT


def test_only_verified_upstream_install_sources_are_used() -> None:
    assert "raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh" in BOOT
    assert "github.com/mobile-dev-inc/Maestro/releases/download/cli-" in BOOT
    assert "graphifyy[mcp]" not in BOOT
    assert "GRAPHIFY_PACKAGE=graphifyy" in LOCK
    assert "claude-plugins-official" in LOCK


def test_graphify_output_is_never_repo_state() -> None:
    assert "graphify-out/" in IGNORE
    assert "graphify extract . --code-only" in BOOT
    for forbidden in ("git add graphify-out", "git commit graphify-out"):
        assert forbidden not in BOOT


def test_qualification_mcps_are_project_scoped() -> None:
    graphify = MCP["mcpServers"]["graphify"]
    assert graphify["command"] == "${HOME}/.local/bin/graphify-mcp"
    assert graphify["args"] == ["${PWD}/graphify-out/graph.json"]

    maestro = MCP["mcpServers"]["maestro"]
    assert maestro["command"] == "maestro"
    assert maestro["args"] == ["mcp"]

    playwright = MCP["mcpServers"]["playwright"]
    assert playwright["command"] == "npx"
    assert playwright["args"] == ["-y", "@playwright/mcp@latest"]

    devtools = MCP["mcpServers"]["chrome-devtools"]
    assert devtools["command"] == "npx"
    assert devtools["args"] == ["-y", "chrome-devtools-mcp@latest"]

    assert "claude mcp add -s local" not in BOOT


def test_no_credentials_are_embedded() -> None:
    combined = "\n".join((BOOT, VERIFY, LOCK, MCP_TEXT))
    credential_patterns = (
        r"sk-[A-Za-z0-9_-]{16,}",
        r"sb_(?:secret|service_role)_[A-Za-z0-9_-]+",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
    )
    for pattern in credential_patterns:
        assert re.search(pattern, combined) is None


def test_bootstrap_does_not_install_application_dependencies() -> None:
    for forbidden in ("npm install", "npm ci", "pip install -r", "apt-get", "sudo "):
        assert forbidden not in BOOT


def test_verify_checks_all_managed_capabilities() -> None:
    for token in (
        "Superpowers",
        "rtk",
        "graphify",
        "graphify-mcp",
        "maestro",
        "playwright",
        "chrome-devtools",
    ):
        assert token.lower() in VERIFY.lower()


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS agent tooling bootstrap contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
