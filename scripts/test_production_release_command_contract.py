#!/usr/bin/env python3
"""Positive and negative contracts for the owner-only production release command."""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_module():
    path = ROOT / "scripts/production_release_command.py"
    spec = importlib.util.spec_from_file_location("production_release_command", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load production release command module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def require(source: str, tokens: list[str], label: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise AssertionError(f"{label} missing: {missing}")


def forbid(source: str, tokens: list[str], label: str) -> None:
    present = [token for token in tokens if token in source]
    if present:
        raise AssertionError(f"{label} contains forbidden patterns: {present}")


def valid_payload(sha: str) -> dict:
    return {
        "action": "created",
        "repository": {"full_name": "yotamfried-ux/Video-editing-with-drone"},
        "issue": {
            "number": 199,
            "title": "SportReel Production Release Control",
            "state": "open",
        },
        "comment": {
            "id": 5081716095,
            "body": f"/sportreel-production-release {sha}",
            "author_association": "OWNER",
            "user": {"login": "yotamfried-ux"},
        },
        "sender": {"login": "yotamfried-ux"},
    }


def valid_env(sha: str) -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": "issue_comment",
        "GITHUB_REPOSITORY": "yotamfried-ux/Video-editing-with-drone",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": sha,
    }


def expect_rejected(module, payload: dict, env: dict[str, str], label: str) -> None:
    try:
        module.validate_command_event(payload, env)
    except module.CommandError:
        return
    raise AssertionError(f"negative command fixture was accepted: {label}")


def main() -> int:
    workflow = read(".github/workflows/production-release-command.yml")
    release = read(".github/workflows/upload-foundation-release.yml")
    command_source = read("scripts/production_release_command.py")
    audit = read("docs/audit/production-release-command-control-20260726.md")

    require(
        workflow,
        [
            "issue_comment:",
            "types: [created]",
            "contents: read",
            "issues: write",
            "actions: write",
            "group: sportreel-production-release-command",
            "queue: max",
            "cancel-in-progress: false",
            "github.event.issue.number == 199",
            "github.event.issue.pull_request == null",
            "startsWith(github.event.comment.body, '/sportreel-production-release ')",
            "production_release_command.py",
            "if-no-files-found: error",
            "retention-days: 30",
        ],
        "command workflow",
    )
    require(
        release,
        [
            "group: upload-foundation-production-release",
            "workflow_dispatch:",
            "confirm_release",
            "confirm_biometric_removal",
            "production_domain",
            "browser_upload_origin",
        ],
        "protected release workflow",
    )
    require(
        command_source,
        [
            'EXPECTED_REPOSITORY = "yotamfried-ux/Video-editing-with-drone"',
            "EXPECTED_ISSUE_NUMBER = 199",
            'EXPECTED_ACTOR = "yotamfried-ux"',
            'EXPECTED_AUTHOR_ASSOCIATION = "OWNER"',
            'EXPECTED_REF = "refs/heads/main"',
            'RELEASE_WORKFLOW = "upload-foundation-release.yml"',
            '"confirm_release": "RELEASE"',
            '"confirm_biometric_removal": "REMOVE_BIOMETRICS"',
            '"production_domain": "video-editing-with-drone.vercel.app"',
            '"browser_upload_origin": ""',
            "/git/ref/heads/main",
            "/actions/workflows/{RELEASE_WORKFLOW}/dispatches",
            "/actions/runs/{run_id}/cancel",
            '"return_run_details": True',
            "cancel_and_verify",
            "ALLOWED_ACTIVE_STATUSES",
            "active_release_runs",
            "another protected production release is already active",
            "update_issue_comment",
            'evidence["result"] = "failed"',
            'evidence["result"] = "success"',
            '"secret_values_recorded": False',
        ],
        "command implementation",
    )
    require(
        audit,
        [
            "Issue #199",
            "workflow_dispatch",
            "queue: max",
            "return_run_details=true",
            "GAP-023 remains open",
        ],
        "focused audit",
    )
    forbid(
        workflow + command_source,
        [
            "pull_request_target",
            "repository_dispatch",
            "personal access token",
            "GITHUB_DISPATCH_TOKEN",
            "continue-on-error: true",
            "|| true",
            "/issues/{issue_number}/comments",
            "find_dispatched_run",
            "cancel_requested_for_run_id",
        ],
        "release command surface",
    )

    module = load_module()
    sha = "a" * 40
    accepted = module.validate_command_event(valid_payload(sha), valid_env(sha))
    if accepted.expected_main_sha != sha or accepted.comment_id != 5081716095:
        raise AssertionError("valid owner command did not preserve exact identity")
    if module.release_inputs() != {
        "confirm_release": "RELEASE",
        "confirm_biometric_removal": "REMOVE_BIOMETRICS",
        "production_domain": "video-editing-with-drone.vercel.app",
        "browser_upload_origin": "",
    }:
        raise AssertionError("release inputs are not fixed exactly")

    mutations = []

    payload = valid_payload(sha)
    payload["issue"]["number"] = 200
    mutations.append((payload, valid_env(sha), "wrong issue"))

    payload = valid_payload(sha)
    payload["issue"]["pull_request"] = {"url": "https://example.invalid"}
    mutations.append((payload, valid_env(sha), "pull request comment"))

    payload = valid_payload(sha)
    payload["comment"]["user"]["login"] = "other-user"
    mutations.append((payload, valid_env(sha), "wrong actor"))

    payload = valid_payload(sha)
    payload["comment"]["author_association"] = "COLLABORATOR"
    mutations.append((payload, valid_env(sha), "non-owner association"))

    payload = valid_payload(sha)
    payload["comment"]["body"] += " "
    mutations.append((payload, valid_env(sha), "trailing whitespace"))

    payload = valid_payload(sha)
    payload["comment"]["body"] = f"/sportreel-production-release {'b' * 40}"
    mutations.append((payload, valid_env(sha), "stale or mismatched SHA"))

    env = valid_env(sha)
    env["GITHUB_REF"] = "refs/heads/feature"
    mutations.append((valid_payload(sha), env, "non-main ref"))

    env = valid_env(sha)
    env["GITHUB_REPOSITORY"] = "attacker/fork"
    mutations.append((valid_payload(sha), env, "wrong repository"))

    env = valid_env(sha)
    env["GITHUB_EVENT_NAME"] = "pull_request"
    mutations.append((valid_payload(sha), env, "wrong event"))

    for payload, env, label in mutations:
        expect_rejected(module, copy.deepcopy(payload), dict(env), label)

    good_run = {
        "id": 123,
        "head_sha": sha,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "requested",
        "conclusion": None,
        "path": ".github/workflows/upload-foundation-release.yml@refs/heads/main",
        "html_url": "https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/123",
    }
    verified = module.verify_release_run(good_run, sha)
    if verified["run_id"] != 123:
        raise AssertionError("valid active release run was not preserved")

    for field, value in [
        ("head_sha", "b" * 40),
        ("head_branch", "feature"),
        ("event", "push"),
        ("status", "unknown"),
        ("conclusion", "success"),
        ("path", ".github/workflows/other.yml@refs/heads/main"),
    ]:
        bad = dict(good_run)
        bad[field] = value
        try:
            module.verify_release_run(bad, sha)
        except module.CommandError:
            continue
        raise AssertionError(f"unsafe release run was accepted: {field}={value}")

    completed = dict(good_run)
    completed["status"] = "completed"
    completed["conclusion"] = "failure"
    if module.verify_release_run(completed, sha)["conclusion_after_dispatch"] != "failure":
        raise AssertionError("correlated fast terminal release was not retained")

    class CancelClient:
        def __init__(self, terminal_conclusion: str) -> None:
            self.repository = "yotamfried-ux/Video-editing-with-drone"
            self.calls = 0
            self.terminal_conclusion = terminal_conclusion

        def request(self, method, path, *, expected):
            self.calls += 1
            if self.calls == 1:
                raise module.CommandError("transient cancel failure")
            return 202, None

        def get_run(self, run_id):
            return {"id": run_id, "status": "completed", "conclusion": self.terminal_conclusion}

    original_sleep = module.time.sleep
    module.time.sleep = lambda _: None
    try:
        cancellation = module.GitHubClient.cancel_and_verify(CancelClient("cancelled"), 123)
        if not cancellation["verified"] or not cancellation["cancel_request_errors"]:
            raise AssertionError("verified cancellation did not retain transient request evidence")
        try:
            module.GitHubClient.cancel_and_verify(CancelClient("success"), 124)
        except module.CommandError:
            pass
        else:
            raise AssertionError("non-cancelled terminal release was accepted as cancelled")
    finally:
        module.time.sleep = original_sleep

    print("PASS: owner-only production release command is exact-main, serialized, fixed-input, and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
