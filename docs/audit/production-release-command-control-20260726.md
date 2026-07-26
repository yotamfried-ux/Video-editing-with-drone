# Production release command control — 2026-07-26

## Scope

This change adds an audited GitHub Issue command surface for launching the existing protected `Upload Foundation Production Release` workflow from ChatGPT's connected GitHub account. It does not add a feature, tune the pipeline, alter Ground Truth, or weaken any existing production release gate.

Control issue: **Issue #199 — SportReel Production Release Control**.

Accepted command:

```text
/sportreel-production-release <exact-current-main-sha>
```

## Authorization and identity contract

The command fails closed unless all of the following are true:

- the event is a newly created `issue_comment` event;
- the workflow is running from `refs/heads/main` in `yotamfried-ux/Video-editing-with-drone`;
- the comment is on open Issue #199, not on a pull request;
- the issue title remains `SportReel Production Release Control`;
- the comment author and webhook sender are exactly `yotamfried-ux` with `OWNER` association;
- the command contains only the exact `GITHUB_SHA` supplied by GitHub for the default branch event;
- a fresh GitHub API read confirms `refs/heads/main` still points to that same SHA.

## Dispatch contract

The command workflow uses the repository-scoped `GITHUB_TOKEN` with only:

- `contents: read`;
- `issues: write` for the auditable acknowledgement and reaction;
- `actions: write` for the documented `workflow_dispatch` REST endpoint.

It dispatches the existing workflow with these fixed inputs and no user-controlled substitutions:

- `confirm_release=RELEASE`;
- `confirm_biometric_removal=REMOVE_BIOMETRICS`;
- `production_domain=video-editing-with-drone.vercel.app`;
- `browser_upload_origin=` (empty, native Android only).

No PAT, new secret family, secret value, bypass, or alternate workflow is introduced.

## Race and concurrency contract

The command workflow uses its own `sportreel-production-release-command` concurrency group with `queue: max`, so command attempts are serialized instead of replacing one another. Before dispatch, it lists the protected release workflow runs and fails closed if any release is already active.

The dispatch request sets `return_run_details=true`, so the accepted API response returns the exact workflow run ID synchronously. After dispatch, the command verifies the correlated run uses `workflow_dispatch`, `main`, the authorized exact SHA, the protected workflow path, a recognized status, and a status/conclusion combination that is internally consistent.

Any post-dispatch identity mismatch triggers retried cancellation and requires a verified `completed/cancelled` terminal state before cancellation is recorded as successful. Cancellation request failures and polling failures remain visible in evidence instead of being swallowed.

The command result is written by editing the original command comment. The workflow listens only for newly created comments, so its acknowledgement cannot create another dispatcher run or displace a pending release. Acknowledgement failures are recorded separately and do not rewrite a successfully verified dispatch as a failed release command.

## Evidence

Every command attempt on the control issue that reaches validation writes a 30-day `production-release-command-<comment_id>` artifact containing:

- command comment and actor identity;
- authorized exact main SHA;
- fixed non-secret inputs;
- current-main verification;
- active-run precheck plus correlated workflow run ID, URL, path, event, branch, head SHA, and post-dispatch status;
- acknowledgement outcome;
- sanitized failure evidence and verified cancellation state when applicable;
- `secret_values_recorded=false`.

## Audit state

This control surface is foundation and operational-access work only. **GAP-023 remains open** until the resulting protected production release passes Vercel, Supabase, runtime biometric scan, R2, production API, and EAS stages with retained evidence, and the exact APK is installed on the target Android device. GAP-013, GAP-014, GAP-015, and GAP-016 remain open pending their required live/device evidence.

## Official implementation basis

- GitHub Actions `issue_comment` events execute from the default branch and require the workflow file to exist on that branch.
- GitHub's workflow-dispatch REST endpoint requires Actions write permission, accepts the workflow ref and declared inputs, and returns the exact run ID when `return_run_details=true`.
- Events created with `GITHUB_TOKEN` normally do not start workflows, but `workflow_dispatch` and `repository_dispatch` are documented exceptions.
- GitHub concurrency `queue: max` serializes multiple pending command runs instead of replacing an existing pending run.
