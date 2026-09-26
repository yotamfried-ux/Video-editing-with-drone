# SportReel agent tooling bootstrap

This repository keeps the **recipe, project configuration, and qualification
baseline** for the external tools Claude uses while working on SportReel. It
intentionally does **not** vendor third-party binaries, generated Graphify
graphs, credentials, Android SDKs, emulator images, browsers, or security
scanner databases.

## One command on a fresh Claude Code host

```bash
bash scripts/bootstrap-agent-tools.sh
```

The script is idempotent. It checks qualified versions first, skips matching
installations, avoids rebuilding the Graphify graph when it already matches the
current Git HEAD, and finishes with `scripts/verify-agent-tools.sh`.

## Project qualification capabilities

The project deliberately separates tools that should be available in a normal
Cloud session from heavier escalation/security tools.

Always-declared project capabilities:

- **Superpowers** — Claude workflow/debugging/review skills from the official
  Claude plugin marketplace. The lock records the live-qualified baseline;
  marketplace installation is host-level.
- **RTK** — compact Bash/tool output plus the Claude hook. The exact qualified
  binary version is restored when missing or different.
- **Graphify** — pinned CLI/MCP package plus a code-only graph generated from the
  checkout. The MCP definition is committed in root `.mcp.json`, so it is
  project-scoped rather than recreated by every session.
- **Maestro** — pinned CLI plus project-scoped `maestro mcp`. Deterministic
  Maestro flows remain the default mobile E2E regression route.
- **Playwright MCP** — project-scoped, on-demand browser exploration and web
  user-journey automation through the official Microsoft package.
- **Chrome DevTools MCP** — project-scoped, on-demand browser console, network
  and performance evidence when Playwright alone is not enough.

The browser MCP packages use `npx` and are launched only when invoked. They are
not application dependencies and do not need to be preinstalled into
`node_modules`.

## Escalation-only mobile tools

Engineering-OS also catalogs **Appium MCP** and **Mobile Next MCP**. SportReel
does not keep them in the default project manifest because Maestro already
covers the durable Android/iOS journey layer and every additional MCP increases
host/setup/tool surface.

Use Appium when a test needs native/device/WebDriver control Maestro cannot
expose. Use Mobile Next for agent-driven exploratory device interaction where a
supported target exists. When such a trigger exists, add/ensure the capability
through Engineering-OS for that qualification rather than loading it in every
Cloud session.

## Security qualification

Security scanners are intentionally **CI capabilities**, not permanent Cloud
MCPs. This keeps repetitive scanning deterministic and prevents every Cloud
session from spending context rediscovering or driving scanners.

The security qualification route is based on the Engineering-OS security
catalog and combines:

- GitHub CodeQL for SAST/data-flow analysis;
- OSV-Scanner for dependency/SCA evidence;
- Trivy for dependency, misconfiguration and secret scanning;
- Gitleaks for repository/history secret detection;
- MobSF/mobsfscan for applicable mobile-source or packaged-app evidence;
- OWASP ZAP for authorized dynamic Web/API scanning;
- OWASP ASVS/WSTG and MASVS/MASTG as the standards matrix for controls that
  automation cannot prove.

A scanner pass is evidence for its own scope only. Authorization/business logic,
real mobile journeys and authoritative backend side effects still require the
corresponding deterministic tests and E2E evidence.

## What persists

Git persists:

- `.engineering-os-tools.json`, the authoritative list of Engineering-OS external tools adopted by this project;
- this bootstrap and verifier;
- the qualified version lock;
- the project-scoped MCP definitions;
- the CI safety/security contracts and documentation;
- durable Maestro and other regression tests committed by the application.

A disposable cloud host cannot preserve binaries from a previous container.
On a new host the bootstrap downloads only missing/mismatched pinned host tools.
Npx-backed browser MCPs are resolved on demand. There is no repeated discovery
or manual configuration. On a reused host, matching installs and a current
Graphify graph are skipped.

Claude Code may request a one-time trust approval for project-scoped MCPs on a
fresh host. That is a security boundary, not missing project configuration.

## What is intentionally regenerated

`graphify-out/` is derived from the current checkout and ignored by Git. A
small stamp ties it to the exact Git HEAD so a reused checkout avoids needless
rebuilds without trusting a stale graph.

## Verification only

```bash
bash scripts/verify-agent-tools.sh
```

A passing verifier proves the pinned host tools and project MCP declarations are
present. It does **not** claim a live browser/device handshake. Playwright,
Chrome DevTools and Maestro MCP still need a compatible host and the intended
browser/device before a live qualification claim can be made.

## Qualification boundary

These tools improve agent navigation, context efficiency and test execution;
they are not evidence that SportReel itself works. Application claims still
need exact-revision deterministic tests plus authoritative downstream evidence
(Supabase/R2/API, deployment state, and real-device/real-footage evidence where
the capability requires it).

The pinned host-tool baseline comes from the live Engineering-OS Claude Code
host qualification performed on 2026-09-23. Application-testing and security
routing follows the current Engineering-OS capability registry; host/runtime
requirements must still be verified on the target environment.
