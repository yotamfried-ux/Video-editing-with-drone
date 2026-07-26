#!/usr/bin/env python3
"""Authorize an owner-only issue command and dispatch the protected production release."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

EXPECTED_REPOSITORY = "yotamfried-ux/Video-editing-with-drone"
EXPECTED_ISSUE_NUMBER = 199
EXPECTED_ISSUE_TITLE = "SportReel Production Release Control"
EXPECTED_ACTOR = "yotamfried-ux"
EXPECTED_AUTHOR_ASSOCIATION = "OWNER"
EXPECTED_REF = "refs/heads/main"
RELEASE_WORKFLOW = "upload-foundation-release.yml"
API_VERSION = "2026-03-10"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_ACTIVE_STATUSES = {"in_progress", "pending", "queued", "requested", "waiting"}


class CommandError(RuntimeError):
    """Raised when the command cannot be accepted safely."""


@dataclass(frozen=True)
class AuthorizedCommand:
    repository: str
    issue_number: int
    comment_id: int
    actor: str
    expected_main_sha: str
    command: str


def _as_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CommandError(f"{label} must be an object")
    return value


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise CommandError(f"{label} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"{label} must be an integer") from exc


def validate_command_event(payload: dict[str, Any], environ: dict[str, str]) -> AuthorizedCommand:
    event_name = environ.get("GITHUB_EVENT_NAME", "")
    repository_env = environ.get("GITHUB_REPOSITORY", "")
    ref = environ.get("GITHUB_REF", "")
    sha = environ.get("GITHUB_SHA", "").lower()

    if event_name != "issue_comment":
        raise CommandError("event must be issue_comment")
    if payload.get("action") != "created":
        raise CommandError("issue comment action must be created")
    if repository_env != EXPECTED_REPOSITORY:
        raise CommandError("GITHUB_REPOSITORY is not the protected repository")
    if ref != EXPECTED_REF:
        raise CommandError("command workflow must run from refs/heads/main")
    if not SHA_PATTERN.fullmatch(sha):
        raise CommandError("GITHUB_SHA must be a full lowercase commit SHA")

    repository = _as_dict(payload.get("repository"), "repository")
    if repository.get("full_name") != EXPECTED_REPOSITORY:
        raise CommandError("event repository does not match the protected repository")

    issue = _as_dict(payload.get("issue"), "issue")
    if _as_int(issue.get("number"), "issue.number") != EXPECTED_ISSUE_NUMBER:
        raise CommandError("command was not posted on the production release control issue")
    if issue.get("title") != EXPECTED_ISSUE_TITLE:
        raise CommandError("production release control issue title mismatch")
    if issue.get("state") != "open":
        raise CommandError("production release control issue must be open")
    if "pull_request" in issue:
        raise CommandError("production release commands are not accepted on pull requests")

    comment = _as_dict(payload.get("comment"), "comment")
    actor = _as_dict(comment.get("user"), "comment.user").get("login")
    if actor != EXPECTED_ACTOR:
        raise CommandError("production release command actor is not the repository owner")
    if comment.get("author_association") != EXPECTED_AUTHOR_ASSOCIATION:
        raise CommandError("production release command must have OWNER author association")

    sender = _as_dict(payload.get("sender"), "sender").get("login")
    if sender != EXPECTED_ACTOR:
        raise CommandError("event sender does not match the repository owner")

    comment_id = _as_int(comment.get("id"), "comment.id")
    expected_command = f"/sportreel-production-release {sha}"
    if comment.get("body") != expected_command:
        raise CommandError("command body must contain only the exact current main SHA")

    return AuthorizedCommand(
        repository=EXPECTED_REPOSITORY,
        issue_number=EXPECTED_ISSUE_NUMBER,
        comment_id=comment_id,
        actor=EXPECTED_ACTOR,
        expected_main_sha=sha,
        command=expected_command,
    )


def release_inputs() -> dict[str, str]:
    return {
        "confirm_release": "RELEASE",
        "confirm_biometric_removal": "REMOVE_BIOMETRICS",
        "production_domain": "video-editing-with-drone.vercel.app",
        "browser_upload_origin": "",
    }


class GitHubClient:
    def __init__(self, *, api_url: str, token: str, repository: str) -> None:
        if not token:
            raise CommandError("GITHUB_TOKEN is missing")
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.repository = repository

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "sportreel-production-release-command",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            message = raw.decode("utf-8", errors="replace")[:1000]
            raise CommandError(f"GitHub API {method} {path} failed with HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise CommandError(f"GitHub API {method} {path} failed: {exc.reason}") from exc

        if status not in expected:
            raise CommandError(f"GitHub API {method} {path} returned unexpected HTTP {status}")
        if not raw:
            return status, None
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CommandError(f"GitHub API {method} {path} returned invalid JSON") from exc

    def main_sha(self) -> str:
        _, payload = self.request("GET", f"/repos/{self.repository}/git/ref/heads/main")
        ref_object = _as_dict(_as_dict(payload, "main ref response").get("object"), "main ref object")
        value = str(ref_object.get("sha") or "").lower()
        if not SHA_PATTERN.fullmatch(value):
            raise CommandError("GitHub main ref returned an invalid commit SHA")
        return value

    def active_release_runs(self) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"per_page": "20"})
        _, payload = self.request(
            "GET",
            f"/repos/{self.repository}/actions/workflows/{RELEASE_WORKFLOW}/runs?{query}",
        )
        rows = _as_dict(payload, "workflow runs response").get("workflow_runs")
        if not isinstance(rows, list):
            raise CommandError("workflow runs response has no workflow_runs list")
        return [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("status") or "") in ALLOWED_ACTIVE_STATUSES
        ]

    def dispatch_release(self) -> tuple[int | None, datetime]:
        started_at = datetime.now(timezone.utc)
        status, payload = self.request(
            "POST",
            f"/repos/{self.repository}/actions/workflows/{RELEASE_WORKFLOW}/dispatches",
            body={"ref": "main", "inputs": release_inputs()},
            expected=(200, 204),
        )
        if status == 200:
            response = _as_dict(payload, "workflow dispatch response")
            run_id = _as_int(response.get("workflow_run_id"), "workflow_run_id")
            if run_id <= 0:
                raise CommandError("workflow dispatch returned an invalid run ID")
            return run_id, started_at
        return None, started_at

    def find_dispatched_run(self, *, expected_sha: str, started_at: datetime) -> int:
        threshold = started_at - timedelta(seconds=5)
        query = urllib.parse.urlencode(
            {"event": "workflow_dispatch", "branch": "main", "per_page": "20"}
        )
        for _ in range(15):
            _, payload = self.request(
                "GET",
                f"/repos/{self.repository}/actions/workflows/{RELEASE_WORKFLOW}/runs?{query}",
            )
            rows = _as_dict(payload, "workflow runs response").get("workflow_runs")
            if not isinstance(rows, list):
                raise CommandError("workflow runs response has no workflow_runs list")
            candidates: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                created_raw = str(row.get("created_at") or "")
                try:
                    created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if created_at < threshold:
                    continue
                if str(row.get("head_sha") or "").lower() != expected_sha:
                    continue
                if row.get("event") != "workflow_dispatch":
                    continue
                candidates.append(row)
            if len(candidates) == 1:
                return _as_int(candidates[0].get("id"), "workflow run id")
            if len(candidates) > 1:
                raise CommandError("workflow dispatch fallback found multiple matching runs")
            time.sleep(2)
        raise CommandError("workflow dispatch did not expose a correlated run ID")

    def get_run(self, run_id: int) -> dict[str, Any]:
        _, payload = self.request("GET", f"/repos/{self.repository}/actions/runs/{run_id}")
        return _as_dict(payload, "workflow run response")

    def cancel_run(self, run_id: int) -> None:
        try:
            self.request(
                "POST",
                f"/repos/{self.repository}/actions/runs/{run_id}/cancel",
                expected=(202, 409),
            )
        except CommandError:
            pass

    def add_reaction(self, comment_id: int) -> None:
        self.request(
            "POST",
            f"/repos/{self.repository}/issues/comments/{comment_id}/reactions",
            body={"content": "rocket"},
            expected=(200, 201),
        )

    def update_issue_comment(self, comment_id: int, body: str) -> None:
        self.request(
            "PATCH",
            f"/repos/{self.repository}/issues/comments/{comment_id}",
            body={"body": body},
            expected=(200,),
        )


def verify_release_run(run: dict[str, Any], expected_sha: str) -> dict[str, Any]:
    run_id = _as_int(run.get("id"), "workflow run id")
    head_sha = str(run.get("head_sha") or "").lower()
    head_branch = run.get("head_branch")
    event = run.get("event")
    status = str(run.get("status") or "")
    conclusion = run.get("conclusion")
    path = str(run.get("path") or "")
    html_url = str(run.get("html_url") or "")

    if head_sha != expected_sha:
        raise CommandError("dispatched release run head SHA does not match the authorized main SHA")
    if head_branch != "main":
        raise CommandError("dispatched release run is not on main")
    if event != "workflow_dispatch":
        raise CommandError("dispatched release run event is not workflow_dispatch")
    if RELEASE_WORKFLOW not in path:
        raise CommandError("dispatched run does not use the protected release workflow")
    if status not in ALLOWED_ACTIVE_STATUSES or conclusion is not None:
        raise CommandError("dispatched release run is not active or already has a conclusion")
    if not html_url.startswith("https://github.com/"):
        raise CommandError("dispatched release run has no canonical GitHub URL")

    return {
        "run_id": run_id,
        "run_url": html_url,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "event": event,
        "status_after_dispatch": status,
        "conclusion_after_dispatch": conclusion,
        "workflow_path": path,
    }


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence: dict[str, Any] = {
        "protocol": "sportreel_production_release_command_v1",
        "result": "failed",
        "secret_values_recorded": False,
        "fixed_release_inputs": release_inputs(),
    }
    run_id: int | None = None
    client: GitHubClient | None = None
    command: AuthorizedCommand | None = None

    try:
        payload = json.loads(args.event.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CommandError("event payload must be a JSON object")
        command = validate_command_event(payload, dict(os.environ))
        evidence["authorization"] = asdict(command)

        client = GitHubClient(
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            token=os.environ.get("GITHUB_TOKEN", ""),
            repository=command.repository,
        )
        main_sha = client.main_sha()
        evidence["main_sha_before_dispatch"] = main_sha
        if main_sha != command.expected_main_sha:
            raise CommandError("main changed after the command comment was created")

        active_before = client.active_release_runs()
        evidence["active_release_run_ids_before_dispatch"] = [
            _as_int(row.get("id"), "active workflow run id") for row in active_before
        ]
        if active_before:
            raise CommandError("another protected production release is already active")

        run_id, started_at = client.dispatch_release()
        if run_id is None:
            run_id = client.find_dispatched_run(
                expected_sha=command.expected_main_sha,
                started_at=started_at,
            )

        run: dict[str, Any] | None = None
        for _ in range(15):
            run = client.get_run(run_id)
            if run.get("status"):
                break
            time.sleep(2)
        if run is None:
            raise CommandError("dispatched release run could not be read")

        release = verify_release_run(run, command.expected_main_sha)
        evidence["release_run"] = release
        evidence["result"] = "success"
        write_evidence(args.evidence, evidence)

        client.add_reaction(command.comment_id)
        client.update_issue_comment(
            command.comment_id,
            f"{command.command}\n\n"
            "✅ Protected production release command accepted.\n\n"
            f"Workflow run: {release['run_url']}\n\n"
            "The existing release workflow retains its fixed inputs and all fail-closed gates.",
        )
        print(f"Dispatched protected production release run {run_id} for {command.expected_main_sha}")
        return 0
    except Exception as exc:
        if run_id is not None and client is not None:
            client.cancel_run(run_id)
            evidence["cancel_requested_for_run_id"] = run_id
        evidence["error_type"] = type(exc).__name__
        evidence["error"] = str(exc)
        write_evidence(args.evidence, evidence)
        if command is not None and client is not None:
            try:
                client.update_issue_comment(
                    command.comment_id,
                    f"{command.command}\n\n"
                    "❌ Protected production release command failed closed. "
                    "No validation was bypassed. Inspect the command-dispatch workflow artifact and logs.",
                )
            except Exception:
                pass
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
