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

**Status:** INVESTIGATING  
**Category:** performance  
**Observed:** 2026-09-23  
**Revision / environment:** SportReel PR #219; GitHub Actions run 35899516151; Maestro 2.10.0

**Observed behavior**

The successful UPL-01 run used a cached APK, so the Android Gradle build was
skipped, but the workflow still had to provision dependencies, start Metro,
boot an Android emulator, install Maestro, and then run the scenarios serially.

**Impact**

The complete successful workflow took roughly seven minutes. The four Maestro
flows themselves consumed several minutes sequentially even though the three
behavioral scenarios can be isolated on separate device instances.

**Evidence**

Run 35899516151 completed successfully. The APK build step was skipped from the
checkpoint cache. Maestro passed media seed, no-secret, picker-cancelled and
gallery-upload; independent backend verification also passed.

**Likely cause**

Independent scenarios share one emulator and are intentionally executed in
series by `mobile/.maestro/upl01/run-upl01.sh`.

**Simpler / faster alternative**

Run independent scenarios concurrently on isolated emulators/device workers.
Keep only the positive upload scenario responsible for Supabase/R2 verification.
Evaluate Maestro Cloud/managed devices to remove repeated emulator provisioning
when credentials/infrastructure are available.

**Action taken**

Tracked for the next optimization change.

**Follow-up**

Measure serial baseline versus parallel wall-clock time and then inspect the
rest of the project for other safely parallelizable CI/test stages.


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
