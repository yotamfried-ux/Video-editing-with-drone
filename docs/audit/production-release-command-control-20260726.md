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

The command workflow and the production release workflow share the exact concurrency group `upload-foundation-production-release` with `cancel-in-progress: false`.

The dispatcher holds that group while it:

1. dispatches the release;
2. obtains the resulting workflow run ID;
3. verifies the run uses `workflow_dispatch`, `main`, the authorized exact SHA, and the protected workflow path;
4. verifies the release is still queued/pending/requested/waiting and has not started while the dispatcher owns the shared concurrency group;
5. cancels the release and fails if any identity or held-state check does not match.

Only after successful verification does the dispatcher finish and release the concurrency lock, allowing the protected release workflow to begin.

## Evidence

Every command attempt on the control issue that reaches validation writes a 30-day `production-release-command-<comment_id>` artifact containing:

- command comment and actor identity;
- authorized exact main SHA;
- fixed non-secret inputs;
- current-main verification;
- correlated workflow run ID, URL, path, event, branch, head SHA, and held status;
- sanitized failure and cancellation evidence when applicable;
- `secret_values_recorded=false`.

## Audit state

This control surface is foundation and operational-access work only. **GAP-023 remains open** until the resulting protected production release passes Vercel, Supabase, runtime biometric scan, R2, production API, and EAS stages with retained evidence, and the exact APK is installed on the target Android device. GAP-013, GAP-014, GAP-015, and GAP-016 remain open pending their required live/device evidence.

## Official implementation basis

- GitHub Actions `issue_comment` events execute from the default branch and require the workflow file to exist on that branch.
- GitHub's workflow-dispatch REST endpoint requires Actions write permission and accepts the workflow ref and declared inputs.
- Events created with `GITHUB_TOKEN` normally do not start workflows, but `workflow_dispatch` and `repository_dispatch` are documented exceptions.
- Repository-wide concurrency groups hold workflows from different files when they use the same group name.
