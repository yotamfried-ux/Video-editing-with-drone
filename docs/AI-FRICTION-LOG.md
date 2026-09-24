# AI Friction & Improvement Log

Persistent learning log for AI agents working on SportReel.

This is broader than a bug list. Record material friction that can teach us how
to make the product, repository, tests, infrastructure, or AI workflow simpler,
faster, clearer, cheaper, or more reliable.

## Record a finding when

- application behavior is wrong or surprising;
- a test is failing, flaky, brittle, misleading, obsolete, or slower than it should be;
- documentation, configuration, dependencies, APIs, tool assumptions, or examples are stale;
- a step takes materially longer than expected;
- setup, downloads, builds, environment preparation, or context reconstruction repeat unnecessarily;
- an AI worker spends excessive tokens/context to rediscover something the project could encode;
- a workflow has unnecessary manual steps or duplicated work;
- a tool/capability exists but is not being used effectively;
- missing automation, caching, observability, evidence, or project-level configuration causes avoidable work;
- an interface, API, folder structure, ownership boundary, or naming scheme is confusing;
- a simpler, faster, safer, more deterministic, or more parallel approach is credible;
- infrastructure limitations force a slower workaround.

A run does not need to fail for an entry to be useful. A seven-minute passing
test that can safely become a three-minute test is valid friction.

## Working rule

Do not stop normal work merely to report a friction item.

1. Continue the active task when safe.
2. Append or update the finding briefly.
3. Fix it immediately when the change is small, reversible, in scope, and verifiable.
4. Otherwise leave a concrete follow-up.
5. Before investigating a recurring infrastructure/tooling problem, search this
   log so the same issue is not rediscovered from scratch.

Never record secrets, tokens, credentials, private personal data, or secret-bearing logs.

## Entry template

### [FRICTION-XXX] Short title

**Status:** OPEN | INVESTIGATING | IMPROVED | RESOLVED | ACCEPTED  
**Category:** bug | performance | tooling | testing | CI | context | documentation | architecture | developer-experience | automation | dependency | other  
**Observed:** YYYY-MM-DD  
**Revision / environment:** commit, branch, workflow run, host, tool version, or N/A

**Observed behavior**

What actually happened.

**Impact**

Practical cost. Prefer measurements when available: wall-clock time, repeated
attempts, token/context cost, number of manual steps, downloads/builds, or failed runs.

**Evidence**

Concrete run IDs, logs, files, screenshots, measurements, or commands.
Separate verified observation from inference.

**Likely cause**

State only what current evidence supports. Mark uncertainty explicitly.

**Simpler / faster alternative**

A concrete improvement when one is credible: cache an artifact, persist project
configuration, use an existing Engineering-OS capability, parallelize independent
work, move execution to managed infrastructure, replace brittle UI coordinates
with semantic selectors, or consolidate repeated agent logic.

**Action taken**

What changed during this task, if anything.

**Follow-up**

Remaining verification or implementation.

## Resolution rule

Do not delete useful history when a finding is fixed. Change its status and add
the resolving commit/PR/run plus the measured improvement when available.

If several entries reveal the same reusable pattern, promote that lesson back
into Engineering-OS so other projects can avoid the same friction.

---

### [FRICTION-001] UPL-01 emulator execution is slower than the Maestro scenarios require

**Status:** IMPROVED  
**Category:** performance  
**Observed:** 2026-09-23  
**Revision / environment:** SportReel PR #219; GitHub Actions runs 35899516151 and 35904081092; Maestro 2.10.0

**Observed behavior**

The successful serial UPL-01 run used a cached APK but still provisioned one
Android emulator and executed the behavioral scenarios in series. A follow-up
implementation isolated the scenarios and fanned them out to separate jobs.

**Impact**

Serial run 35899516151 took 7m19s from start to result. The parallel run
35904081092 executed in about 5 minutes once runners started, but spent roughly
12m34s queued first; trigger-to-result time was therefore about 17m34s. Parallel
test execution worked, but GitHub-hosted runner availability dominated feedback
latency.

**Evidence**

Both runs completed successfully. The parallel run proved the isolated Maestro
scenarios can execute independently while the positive upload path retains
authoritative backend verification.

**Likely cause**

Emulator provisioning and GitHub-hosted runner queueing are more expensive than
the saved serial Maestro time. Multiple workers also repeat environment setup.

**Simpler / faster alternative**

Keep the isolated scenario design, but run it where workers/devices are already
available: managed-device/Maestro Cloud infrastructure or qualified
local/self-hosted capacity. Share immutable app artifacts and avoid rebuilding or
reinstalling per worker.

**Action taken**

Parallel-safe flows and scenario isolation were merged to main. The experiment
established that naive GitHub-hosted fan-out is not the fastest end-to-end path.

**Follow-up**

Qualify a managed-device or persistent local/self-hosted route and compare
trigger-to-result latency against the 7m19s serial baseline.


---

### [FRICTION-002] APK checkpoint cache is branch-scoped, causing an avoidable rebuild on sibling validation branches

**Status:** OPEN  
**Category:** CI  
**Observed:** 2026-09-23  
**Revision / environment:** parallel UPL-01 validation branch `perf/upl01-maestro-parallel`; GitHub Actions

**Observed behavior**

The parallel-validation branch had the same effective mobile application tree as
the already-qualified UPL-01 branch, but its first APK checkpoint restore missed
and Gradle rebuilt the debug APK.

**Impact**

A validation-only branch can pay the expensive Android build cost even when no
APK-affecting mobile source changed, delaying feedback before the actual Maestro
scenarios start.

**Evidence**

Comparison from the last successful UPL-01 application SHA to the then-current
UPL-01 PR head showed only an audit Markdown file changed. The sibling branch
still missed the APK cache because GitHub Actions cache visibility is ref-scoped.

**Likely cause**

The checkpoint is stored with `actions/cache`; matching cache keys alone do not
make a cache created on a sibling branch available to another sibling branch.

**Simpler / faster alternative**

Publish qualified APKs as explicit immutable artifacts keyed by the computed
application-content hash, or provide a trusted shared artifact lookup path, so
validation branches can reuse an identical APK without rebuilding it.

**Action taken**

The parallel workflow now separates APK preparation from scenario execution so
a cold run builds at most once before all parallel workers.

**Follow-up**

Add safe cross-branch APK artifact reuse and measure cold-branch feedback time.

**Update 2026-09-24:** also cold on `main`. A `workflow_dispatch` of UPL-01 on
`main@4846d5f` (run 35967252145) missed the checkpoint and ran the full Gradle
build, although the identical app tree had been built on the merged PR branch.
Caches created on PR branches are never visible to the default branch.

---

### [FRICTION-003] Obsolete in-progress UPL-01 runs can block validation of a newer head

**Status:** OPEN  
**Category:** CI  
**Observed:** 2026-09-23  
**Revision / environment:** UPL-01 GitHub Actions concurrency group

**Observed behavior**

UPL-01 uses one global concurrency group with `cancel-in-progress: false`.
A newer validation head therefore remains pending while an older run continues.

**Impact**

Rapid repair iterations can wait behind work whose result is already superseded
by a newer commit.

**Evidence**

During the parallelization change, newer UPL-01 workflow runs were cancelled or
queued while the first in-progress sibling-branch run retained the shared
concurrency slot.

**Likely cause**

The production backend verifier historically correlated uploads by a run window
and fixture size, so overlapping workflow runs were deliberately prohibited.

**Simpler / faster alternative**

Give every workflow run a collision-resistant backend correlation identity.
Once proven, allow stale runs to be cancelled safely while keeping independent
scenarios within the current run parallel.

**Action taken**

Scenario fixtures are already isolated by distinct byte sizes within one run.

**Follow-up**

Design exact cross-run correlation, add a regression that proves overlapping
runs cannot consume each other's rows, then enable safe stale-run cancellation.


---

### [FRICTION-004] AI work is not yet routed to the cheapest qualified execution path

**Status:** IMPROVED  
**Category:** context  
**Observed:** 2026-09-24  
**Revision / environment:** SportReel main + Engineering-OS execution fast path

**Observed behavior**

SportReel already has deterministic CI, RTK, Graphify, Maestro and reusable agent
assets, while Engineering-OS also catalogs Ollama, agent frameworks and specialist
role prompts. Before this change, project instructions did not explicitly require
an AI session to compare no-model/local/included/paid execution before spawning
subagents or doing cognitive work in the main hosted session.

**Impact**

Bounded tasks such as log triage, independent module review, candidate-test
generation and documentation consistency checking can consume main-agent context
or hosted model usage even when they are suitable for deterministic tooling or a
qualified local worker.

**Evidence**

`CLAUDE.md` previously documented tool bootstrap but had no cost-aware execution
routing. Engineering-OS now exposes `capability-registry/EXECUTION-FAST-PATH.json`
with deterministic/local/included/paid cost classes and local Ollama routing.

**Likely cause**

Tool installation, testing routing and agent catalogs were developed separately;
there was no single low-context execution decision point.

**Simpler / faster alternative**

Route every delegated/LLM-backed subtask through the Engineering-OS execution
fast path. Prefer deterministic tools, then qualified local models for bounded
parallel work, and require deterministic evidence before accepting worker output.

**Action taken**

SportReel `CLAUDE.md` now makes cost-aware execution/delegation part of the
default working method.

**Follow-up**

Qualify one local Ollama model on the actual persistent host using representative
SportReel tasks, then benchmark a small parallel worker pilot against the current
main-agent workflow. Record latency, quality, hardware use and any hosted-model
usage avoided.

---

### [FRICTION-005] Agent-tool bootstrap exits 126 and misreads the Maestro version

**Status:** RESOLVED (this PR)  
**Category:** tooling  
**Observed:** 2026-09-24  
**Revision / environment:** `main@4846d5f`, fresh Claude Code cloud host

**Observed behavior**

`bash scripts/bootstrap-agent-tools.sh` installed every tool and then exited 126:
it `exec`s `scripts/verify-agent-tools.sh`, which Git stores as mode 100644.
After that, the verifier still failed `maestro version mismatch`: it read the first
line of `maestro --version 2>&1`, which on hosts with `JAVA_TOOL_OPTIONS` is the
JVM's `Picked up JAVA_TOOL_OPTIONS...` stderr notice, not the version.

**Impact**

The bootstrap never reported READY on a proxied host. Every re-run also treated
Maestro as mismatched, which defeats the "skip matching installs" idempotence.

**Evidence**

Bootstrap log `exit=126`; the verifier's FAIL line quoted the JVM notice. Fixed
rerun: bootstrap completed in 5 s with every component skipped as already
installed, and all 10 verifier checks PASS.

**Action taken**

Both scripts now read stdout only and compare the first semver token exactly.
The bootstrap runs the verifier with `bash`. The exec bits are set in Git.
Regression: `test_version_probe_tolerates_jvm_stderr_and_banners` runs the real
verifier against a fake JVM-style `maestro`. It fails on the old verifier.

---

### [FRICTION-006] RTK hook rewrites `npx tsc` to the global TypeScript, producing false failures

**Status:** OPEN (workaround documented)  
**Category:** tooling  
**Observed:** 2026-09-24  
**Revision / environment:** RTK 0.49.0 Claude hook; global `/opt/node22/bin/tsc` 6.0.2; mobile pins 5.9.3

**Observed behavior**

After the bootstrap registered the RTK hook, `npx tsc --noEmit` in `mobile/` was
rewritten to `rtk tsc --noEmit` (`rtk rewrite "npx tsc --noEmit"`). That ran the
global TypeScript 6.0.2 and failed with TS5107 (`moduleResolution=node10`
deprecated). The same command had passed minutes earlier, and
`./node_modules/.bin/tsc --noEmit` still passes.

**Impact**

A clean type-check can be reported as FAIL. That is a qualification-reliability
bug: an agent may "fix" a non-problem or distrust a real PASS.

**Simpler / faster alternative**

Always type-check through the project scripts. `npm run type-check` is rewritten
to `rtk npm run type-check`, which still uses the pinned local `tsc` (verified
rc=0 in mobile and web-api). RTK 0.49.0 exposes no per-command exclusion.

**Follow-up**

Ask upstream for `rtk tsc` to prefer `node_modules/.bin/tsc`, or an exclusion list.

---

### [FRICTION-007] Tracked run rows stay `queued` forever when the workflow fails before the tracked step

**Status:** RESOLVED in code (this PR); production rows not backfilled  
**Category:** bug  
**Observed:** 2026-09-24  
**Revision / environment:** production Supabase; Deliver Preview runs 35526131967, 35535335881

**Observed behavior**

Two operator-app `delivery_runs` rows (approved 2026-09-20 17:31 and 20:22)
remain `queued/delivery_workflow_dispatched` with no `github_run_id`. Their
workflow runs failed before `deliver.py` ran (the revision gate), so nothing
moved the rows to a terminal state. Five `pipeline_runs` rows have been `queued`
since July for the same class of reason.

**Impact**

The operator app shows a delivery or pipeline run as in progress indefinitely.
This contradicts GitHub, which shows it failed.

**Action taken**

Added `scripts/finalize_unfinished_run.py` (stdlib-only; touches only
non-terminal rows; always exits 0). It is wired as an `if: failure() || cancelled()` step in
`deliver.yml` and `pipeline-run.yml`. Regression:
`scripts/test_finalize_unfinished_run_contract.py` runs against a stub PostgREST
that enforces the `not.in` filter. CI: `tracked-run-finalize-check.yml`.

**Follow-up**

After merge, prove it on a real early-failing run. The stale historical
production rows need an explicit, approved data update.

---

### [FRICTION-008] No single command runs the contract tests; several need undeclared setup

**Status:** OPEN  
**Category:** testing  
**Observed:** 2026-09-24

**Observed behavior**

`scripts/test_*.py` are invoked one by one from ~40 workflows. Running all 95
locally in parallel took 3 s: 86 passed and 9 failed from setup alone. Five need
`PYTHONPATH=.` (then pass). Four need psycopg, boto3, ffmpeg or supervision.

**Simpler / faster alternative**

Add one runner that sets `PYTHONPATH`, runs the dependency-free set in parallel,
and reports the dependency-gated ones as SKIPPED rather than failed.

---

### [FRICTION-009] Production API host blocked from the agent host; no web-api test harness existed

**Status:** IMPROVED (this PR)  
**Category:** testing  
**Observed:** 2026-09-24

**Observed behavior**

`video-editing-with-drone.vercel.app` is denied by this cloud session's network
policy (proxy 403). The Vercel connector's `web_fetch_vercel_url` reaches
production, but only for GET with no custom headers. `web-api/` had no tests and
no PR check that built it. The mobile and web-api contract mirrors were
unchecked, and had drifted (`OperatorReelRow.token`, `PipelineStatus.meta` /
`updated_at` nullability).

**Action taken**

`scripts/web_api_operator_auth_boundary.py` builds on `next start` plus a
recording backend and covers all 27 operator handlers (4 bad secrets each: 401
with 0 backend calls), GET positive controls, and Discover paging normalization.
CI: `web-api-auth-boundary.yml`. `mobile/.../contracts.drift.ts` makes
`npm run type-check` fail on server→app contract drift.

**Follow-up**

Allow the production host in the environment's network policy if live POST
boundary probes are wanted from agent sessions.

**Update 2026-09-24:** Vercel previews for PR #222 end `CANCELED` ("Ignored"),
so web-api fixes cannot be exercised on real Vercel before merge. The ignore
rule is a project setting, not in `web-api/vercel.json`. Enabling previews for
PRs that touch `web-api/**` would allow a real-infra boundary probe before merge.

---

### [FRICTION-010] PR #222 self-review: the first fixes had blind spots that green CI did not reveal

**Status:** RESOLVED (PR #222 follow-up commit)  
**Category:** testing  
**Observed:** 2026-09-24

**Observed behavior**

An independent review of PR #222 (CI green) found two gaps in its own fixes:

1. The finaliser ran only on `if: failure()`. A `timeout-minutes` expiry or a
   manual cancel reports `cancelled()`, not failure. A row that `run_tracked.py`
   had already moved to `running` would stay stuck. `pipeline-run.yml` has a
   350-minute timeout, so this is a realistic path.
2. The auth-boundary probe discovered routes by the *presence* of
   `requireOperator`, so a new `/api/operator/*` handler that forgot auth was
   invisible to it. That is exactly the regression it exists to catch.

**Action taken**

- The finaliser now uses `failure() || cancelled()` and records `job.status` in
  the error. Regression: `test_cancelled_or_timed_out_run_is_finalized_with_reason`,
  plus a workflow-condition assertion that fails on the previous workflows.
- The probe now requires *every* handler under `/api/operator/**` to return 401,
  and aborts on handler export forms it cannot parse. Proven with two throw-away
  canary routes: an unprotected `GET` returned 200 and failed the probe, and
  `export const POST` failed discovery loudly.

**Lesson**

For a new validation tool, add a canary that the tool must reject before
trusting a PASS.

---

### [FRICTION-011] Heavy path-filtered checks re-run on every push to a PR, including docs-only pushes

**Status:** IMPROVED (#223); reuse to be confirmed on the next same-tree push  
**Category:** CI  
**Observed:** 2026-09-24  
**Revision / environment:** PR #222, `large-upload-foundation-check.yml` (`android-native-compile`)

**Observed behavior**

`pull_request` path filters match against the *whole PR diff*, not the pushed
commit. Because PR #222 touches `mobile/src/features/operator/types/contracts.ts`,
every push to it, including audit and friction-log-only commits, re-runs
`android-native-compile`.

**Impact**

Repeated native Android builds for commits that cannot affect them. It also
encourages agents to delay documentation pushes.

**Simpler / faster alternative**

Split the native compile into a job that checks whether the *pushed* commits
touch its inputs (`git diff --name-only ${{ github.event.before }}..HEAD`), or
key it on a content hash of its inputs with a cached result.

**Update 2026-09-24 (after #223):** `large-upload-foundation-check.yml` now keys a
success marker on the mobile tree. On PR #222 head `de2d605` (run 35978342479)
the marker restore missed, because this was the first run for the tree. The full
compile ran (3m42s) and the marker was saved. This docs-only follow-up push is
the first same-tree run and should skip the compile.

