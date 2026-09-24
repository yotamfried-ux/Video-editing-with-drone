# SportReel — Claude Code Context

## Project overview

Drone/sports footage → AI-assisted editing → personal athlete reels marketplace.

- **Pipeline**: GitHub Actions (`pipeline-run.yml`) dispatches the Python pipeline, mandatory Ultralytics/BoT-SORT perception, Gemini semantic analysis, FFmpeg 4K/30 editing, QA, and diagnostics.
- **Operator app**: React Native (Expo) in `mobile/` — upload, pipeline status, Review, re-edit, approval, and delivery controls.
- **Web API**: Next.js in `web-api/` — Vercel boundary for operator actions, uploads, Discover, checkout, webhooks, and protected media access.
- **Supabase**: DB/auth/tracking state. App-user face recognition is not part of the product.

## Agent tooling bootstrap

On a fresh/disposable Claude Code host, run this once before substantial repository work:

```bash
bash scripts/bootstrap-agent-tools.sh
```

The bootstrap is idempotent: matching installations are reused, generated Graphify state stays outside Git, and the final verifier proves the host is ready. If `bash scripts/verify-agent-tools.sh` already passes, do not reinstall anything. See `docs/agent-tooling-bootstrap.md`.

These are agent/testing tools, not SportReel runtime dependencies. Their presence is not evidence that the application works.


## Cost-aware execution and delegation

Before spawning subagents, choosing a hosted model, or building a new AI workflow,
route the task through Engineering-OS `capability-registry/EXECUTION-FAST-PATH.json`.

Execution preference:

1. deterministic / no-model tools first;
2. reuse already-ready project capabilities;
3. qualified local-model workers for bounded independent tasks;
4. hosted subagents only when they pass the Engineering-OS hosted-delegation ROI gate;
5. paid hosted models only when they materially improve the result.

A hosted subagent is never mandatory merely to satisfy delegation. If the only
available worker is hosted, it may be skipped unless deterministic tooling is
insufficient, no qualified local worker is ready, the task is narrowly bounded,
the expected token/context cost is lower than keeping the work in the
coordinator, and the result will be independently verified.

For hosted workers, send the smallest immutable packet: the exact question,
relevant diff/hunks, and normally no more than five directly relevant files
(32 KiB text by default). Request findings/evidence only, normally no more than
about 1,200 output tokens. Do not pass broad repository context by default.

Documentation consistency/drift is deterministic-first: exact search, static
assertions, contract/schema checks, and diff-based checks. Do not delegate it to
a hosted worker unless a residual semantic question remains after those checks
and the ROI gate passes.

Good local/parallel candidates include log triage, independent module review,
candidate-test generation and static-analysis triage. Give every worker a
bounded output contract and validate its conclusions with deterministic tests,
exact code evidence or authoritative runtime state.

Do not assume "agent" means free. A framework or prompt asset inherits the cost
of the model/runtime behind it. Local Ollama-style inference avoids per-call
hosted API fees but still consumes local compute and must be qualified for the
task. Claude-Code-specific skills are not automatically portable to a local
model.

Do not bulk-start all available agents. Parallelize only independent state and
use one coordinator to reconcile results.

For broad qualification/review work, follow the Engineering-OS execution trace
contract, not just its general intent:

- emit the required structured routing records from
  `capability-registry/EXECUTION-TRACE.json` in the durable audit/final report,
  including the exact Engineering-OS entry point and route key;
- if the task decomposes into 3+ bounded workstreams and at least 2 remain
  independent, mandatory delegation applies only when a ready no-model/local
  worker route can handle a bounded slice with deterministic verification;
- never spawn a hosted subagent just to satisfy the delegation trigger; hosted
  delegation must pass Engineering-OS `hosted_delegation_roi_gate`;
- "shared project context" alone is not a sufficient reason to skip delegation;
  first carve out read-only slices such as module review, log triage, candidate
  tests, or documentation drift.

When CI is running, prefer a host-native PR/check-suite completion subscription
that can resume the same session. Persist the current SHA, acceptance criteria,
and next action before yielding. While a live completion subscription exists,
do not add a timer, sleep loop, or polling fallback merely to wake for one job;
the suite-completion event is sufficient to resume and inspect all terminal jobs.
Use Engineering-OS `capability-registry/CI-CONTINUATION.md` only when the host
cannot resume from such a subscription.

## Product source of truth

Read before changing pipeline behavior:

1. `README.md` → **Product vision — source of truth**
2. `docs/audit/personal-publishable-reel-completion-plan-20260717.md`
3. `docs/audit/quality-first-4k-perception-and-face-removal-plan-20260721.md`
4. `docs/operator-pipeline-contract.md`

## Non-negotiable runtime rules

- Every eligible athlete receives one primary publishable reel or an explicit evidence-backed rejection.
- Other people may remain visible when the featured athlete stays identifiable, continuous, central, and owns the action.
- Surfing coverage includes every complete readable usable wave exactly once.
- Canonical output is silent, vertical 9:16, at most 90 seconds, and contains only complete actions.
- Production source is 4K/30. Canonical Parts must be 2160x3840 at 30 fps.
- Framing is `contain` by default. Crop/zoom is an exceptional CV-evidence-backed repair; Gemini hints, scores, event type, or another visible surfer cannot authorize it.
- Detector/tracker evidence is mandatory for every analyzed event. Never restore a Gemini-only production fallback.
- Do not add face-photo enrollment, face embeddings, biometric matching RPCs, or automatic account ownership based on a face in footage.
- Privileged mobile actions go through `operatorFetch` and the web-api boundary.
- Do not close footage-level gaps from CI alone. Require real-run artifacts and visual review.

## Required environment surfaces

- GitHub Actions: storage credentials, Gemini, Supabase service role, operator-run correlation, and optional perception overrides.
- Mandatory perception defaults are installed by `pipeline/required_perception_policy.py`; production may override the command/model only with another working detector/tracker producer.
- `SPORTREEL_REQUIRE_PERCEPTION` remains enabled in `.github/workflows/pipeline-run.yml`.

## Database state

- Apply tracked migrations in order.
- `supabase/migrations/20260721_remove_face_recognition.sql` removes historical biometric fields, RPCs, inferred reel ownership, and the `athlete-photos` bucket.
- The destructive migration requires explicit approval, backup awareness, application, and verification through `supabase/verify_schema.sql`.

## Project learning / friction

During normal work, record material project friction in `docs/AI-FRICTION-LOG.md`.
This includes bugs, stale assumptions/docs/config, slow steps, repeated setup,
excessive context/token use, brittle tests, unnecessary complexity, missing
automation/caching/parallelism, and credible simpler or faster approaches.

Do not stop execution merely to report a finding. Fix small in-scope reversible
issues when appropriate; otherwise append an evidence-backed entry. Search the
log before reinvestigating recurring tooling/infrastructure problems. Update
existing entries rather than duplicating them, and mark entries resolved with
the verified commit/PR/run and measured improvement when possible. Never put
secrets or sensitive values in the log.

## Working method

- Bootstrap/verify the project agent tools on a fresh host before substantial work.
- Read current files, PRs, and Actions before making claims.
- Keep changes narrow and update the relevant audit.
- Add deterministic positive and negative regressions.
- Fix all CI/review findings before requesting merge.
- Do not merge without explicit user approval.
