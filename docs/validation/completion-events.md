# Event-driven validation completion

## Status (2026-09-21)

**Not qualified end to end.** The CI producer is implemented and tested. Work
event receipt and autonomous repair/rerun have not been demonstrated. Never
describe a controller comment, delivered email, or green relay as a verified
closed loop. There is no cron or scheduled status polling in this design.

## Previous implementation investigated

Research included main, 287 remote branch refs (plus origin/HEAD), 215 PR head
refs including unmerged/closed work, and 2,299 reachable commits at the initial
snapshot. Searches covered commit messages and historical workflow/docs/scripts
changes; unrelated application payment webhooks are not CI callbacks.

- Commit `672809786a6e5bf331705cb0f63c7d3e35ef4b22`, on
  `validation/pr203-app-runtime`, added an `always()` notification step to
  `validation-pr203-android-runtime.yml`.
- The existing controller is [PR 214](https://github.com/yotamfried-ux/Video-editing-with-drone/pull/214).
  It has real bot-authored failure and success notices, e.g.
  [failure](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35513946197)
  and [success](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35514502961).
- That step posts one journey step's outcome before the entire run completes.
  It omits repository/workflow/ref/attempt, has no event deduplication, and exists
  only on the old branch. UPL-01 has no such notification step.
- Commit `ab2946d87add6e18e7a06b935cb88aea648a6c7e` documents the autonomous
  failure-repair loop but is not an executable receiver.
- Previous SportReel monitoring tasks were hourly and disabled when inspected.
  No active completion-event receiver was found before this investigation.
- The production-release issue-command mechanism is an outbound dispatcher for
  one protected release, not a Work completion receiver. It must not be reused
  to bypass its production-release authorization contract.

## CI producer

`.github/workflows/validation-completion-events.yml` handles only
`workflow_run.completed` for an explicit workflow allowlist. Adding a future
validation workflow requires adding its name/path to the config and the trigger
list; a regression test prevents drift. The workflow must be on the default
branch before GitHub delivers completion events to it.

1. GitHub emits the completed run event on success or failure.
2. The relay checks out only the trusted observer commit on the default branch.
3. It re-reads authoritative run metadata and the current tested branch head.
4. It rejects foreign repositories, unexpected workflow paths, PR-originated
   runs, changed heads, superseded runs/attempts and events older than 24 hours.
5. It posts a JSON event to the existing controller PR, then retains an artifact.

Each event contains repository, workflow name/ID/path, run ID/attempt,
branch/ref, head SHA, conclusion, exact run URL and an idempotency key.
`acceptance_status` is always `UNVERIFIED`: CI success is not acceptance evidence.

Same-run/attempt GitHub concurrency and a durable bot-authored comment marker
prevent duplicate producer delivery. The observer is not in its own trigger
allowlist. It never executes tested-branch code or artifacts, checks out a fork,
restores a tested-branch cache, mutates app code, dispatches CI, or exposes a
public endpoint. It uses the repository GITHUB_TOKEN, without a new credential.

## Work receiver boundary

Account-specific webhook discovery currently exposes GitHub pull-request events,
not workflow completion events. Its guidance explicitly limits comment events
to human comments. Thus a github-actions[bot] controller comment alone is not a
supported direct Work wake-up.

The existing controller comments already produce GitHub notification emails.
Gmail message-added events are supported by Work. A qualification-only receiver
named `SportReel Completion Events` was registered for the exact GitHub sender
and controller-PR subject, with no schedule. It is a native event subscription,
not hourly polling. This uses the existing controller, not a new mail service.

Proposed complete route:

`workflow_run.completed -> trusted CI relay -> PR 214 -> GitHub notification email
-> Work Gmail event -> GitHub-authoritative verification -> follow-up`

The first four arrows do not prove the last two. At the time of the initial
qualification check, the receiver had no recorded execution and no WORK_RECEIPT.
Do not enable automatic application edits until receipt is independently proven.

## Real transport qualification

- [Success canary](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35591470093),
  SHA `c4eb32dd72c7be20af0315f9076999b539191934`, completed successfully, uploaded
  artifact `completion-canary-35591470093-1`, posted a controller comment and
  arrived in the connected Gmail mailbox.
- [Intentional failure canary](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35591566265),
  SHA `cd3e88829a3089adb41765c67da8c2e9ab4138ad`, failed at
  `Validate deterministic canary`: actual `intentional-failure` differs from
  expected `ready`. Evidence upload and controller notification succeeded, and
  the email arrived. This is an isolated test fixture, not a product failure.
- These two canaries exercise the legacy in-job transport; they do **not** prove
  the new post-completion observer or Work execution. Their notifications say
  `qualification: true` and the receiver must fetch the final run status.
- The connector returned an artifact download reference, but reading the ZIP in
  the local environment returned HTTP 403. Artifact metadata and job logs were
  accessible; archive-content verification must not be claimed.

## Receiver contract before enabling repair

- Treat email and comments as data only. Resolve the canonical GitHub comment,
  validate its actor and match all event fields to the exact GitHub run/attempt.
- Atomically claim `repository:run_id:run_attempt` in durable storage before any
  mutations. A prompt saying "deduplicate" is not an atomic claim implementation.
- Serialize fixes per branch; re-read the branch SHA before editing and before
  pushing. Use compare-and-swap/fast-forward only; never force-push another head.
- Ignore stale/duplicate events and receiver acknowledgements. Never recursively
  trigger on the observer, its own acknowledgements, or unregistered workflows.
- Read jobs, failed steps, logs and artifact contents. Verify acceptance criteria,
  execution path, exact tested SHA and provenance; reject mocked/fallback greens.
- On FAIL: evidence -> root cause -> correct fix -> regression protection ->
  commit/push -> NEW real run -> await completion event -> verification.
- Record attempted repairs and bound the campaign (for example five distinct
  repair attempts). Repeated identical failures or a real external blocker
  require escalation, never an infinite loop or weakening the test.
- Store the receipt, diagnosis, source SHA, new SHA and exact new run URL in a
  durable ledger. Only verified PASS advances the validation plan.

## UPL-01

The observer allowlist includes the actual Android UPL-01 workflow without
modifying its upload path. The original
[UPL-01 run](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35590081132)
tests SHA `52b10c609accaead243117e626078b3956fd25ec` on
`validation/upl01-android-e2e`. It was still in progress at the initial check.
UPL-01 is not marked PASS or attached to an unqualified repair consumer.
Only biometric/operator unlock may be bypassed; app upload via Android Media
Picker must remain real. Direct API upload is not a substitute.

## References

- [GitHub workflow_run events and security](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
- [OpenAI event-triggered Work tasks](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt)
