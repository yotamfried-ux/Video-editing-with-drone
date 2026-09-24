# SportReel agent tooling bootstrap

This repository keeps the **recipe, project configuration, and qualification
baseline** for the external tools Claude uses while working on SportReel. It
intentionally does **not** vendor third-party binaries, generated Graphify
graphs, credentials, Android SDKs, or emulator images.

## One command on a fresh Claude Code host

```bash
bash scripts/bootstrap-agent-tools.sh
```

The script is idempotent. It checks qualified versions first, skips matching
installations, avoids rebuilding the Graphify graph when it already matches the
current Git HEAD, and finishes with `scripts/verify-agent-tools.sh`.

Managed capabilities:

- **Superpowers** — Claude workflow/debugging/review skills from the official
  Claude plugin marketplace. The lock records the live-qualified baseline;
  marketplace installation is host-level.
- **RTK** — compact Bash/tool output plus the Claude hook. The exact qualified
  binary version is restored when missing or different.
- **Graphify** — pinned CLI/MCP package plus a code-only graph generated from the
  checkout. The MCP definition is committed in root `.mcp.json`, so it is
  project-scoped rather than recreated by every session.
- **Maestro** — pinned CLI for mobile flows. Actual mobile execution can run in
  CI or a managed external device service; the Claude host does not need a
  local emulator just to keep the test tooling available.

## What persists

Git persists:

- `.engineering-os-tools.json`, the authoritative list of Engineering-OS external tools adopted by this project;
- this bootstrap and verifier;
- the qualified version lock;
- the project-scoped Graphify MCP definition;
- the CI safety contract and documentation;
- durable Maestro flows committed by the application.

A disposable cloud host cannot preserve binaries from a previous container.
On a new host the bootstrap downloads only missing/mismatched tools. There is
no repeated discovery or manual configuration. On a reused host, matching
installs and a current Graphify graph are skipped.

Claude Code may request a one-time trust approval for a project-scoped MCP on a
fresh host. That is a security boundary, not missing project configuration.

## What is intentionally regenerated

`graphify-out/` is derived from the current checkout and ignored by Git. A
small stamp ties it to the exact Git HEAD so a reused checkout avoids needless
rebuilds without trusting a stale graph.

## Verification only

```bash
bash scripts/verify-agent-tools.sh
```

If this passes, do not reinstall tools.

## Qualification boundary

These tools improve agent navigation, context efficiency and test execution;
they are not evidence that SportReel itself works. Application claims still
need exact-revision deterministic tests plus authoritative downstream evidence
(Supabase/R2/API, deployment state, and real-device/real-footage evidence where
the capability requires it).

The baseline comes from the live Engineering-OS Claude Code host qualification
performed on 2026-09-23. Update the lock only after a replacement version has
been exercised on the target host and its installation path is verified.
