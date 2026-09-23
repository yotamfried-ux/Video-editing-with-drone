# SportReel agent tooling bootstrap

This repository keeps the **recipe and qualification baseline** for the external
tools Claude uses while working on SportReel. It intentionally does **not**
vendor third-party binaries, generated Graphify graphs, credentials, Android
SDKs, or emulator images.

## One command on a fresh Claude Code host

```bash
bash scripts/bootstrap-agent-tools.sh
```

The script is idempotent. It checks the qualified version first and skips a
matching installation. It then runs `scripts/verify-agent-tools.sh`.

Managed capabilities:

- **Superpowers** — Claude workflow/debugging/review skills from the official
  Claude plugin marketplace. The lock records the live-qualified baseline;
  the marketplace itself controls the installed release.
- **RTK** — compact Bash/tool output plus the Claude hook. Exact qualified
  version is installed when missing or different.
- **Graphify** — code-only repository graph plus MCP entry point. The package is
  pinned. `graphify-out/` is generated per checkout and is never Git state.
- **Maestro** — pinned CLI for mobile flows. A local Android device/emulator is
  not required merely to install or syntax-check flows. Actual mobile execution
  may run in CI or a managed external device service.

## What persists and what does not

Git persists this bootstrap, its lock, CI contract, documentation, and any
durable Maestro flows committed by the application.

A disposable cloud host cannot preserve binaries from a previous container.
On a new host the bootstrap may download missing binaries again, but there is
no repeated tool discovery or manual setup. On a reused host it skips matching
installations.

The Graphify graph is rebuilt from the current checkout because a committed
graph can become stale and misleading.

## Verification only

```bash
bash scripts/verify-agent-tools.sh
```

Use this before substantial Claude work. If it passes, do not reinstall tools.

## Qualification boundary

These tools improve agent navigation, context efficiency and test execution;
they are not evidence that SportReel itself works. Application claims still
need exact-revision deterministic tests plus authoritative downstream evidence
(Supabase/R2/API, deployment state, and real-device/real-footage evidence where
the capability requires it).

The baseline was derived from the live Engineering-OS Claude Code host
qualification performed on 2026-09-23. Update the lock only after a replacement
version has been exercised on the target host and its installation path is
verified.
