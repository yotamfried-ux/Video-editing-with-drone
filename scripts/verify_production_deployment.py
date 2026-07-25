#!/usr/bin/env python3
"""Fail-closed verification of the live Vercel production deployment and env names."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.vercel.com"


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def api_get(path: str, token: str, team_id: str) -> Any:
    separator = "&" if "?" in path else "?"
    url = f"{API}{path}"
    if team_id:
        url = f"{url}{separator}teamId={urllib.parse.quote(team_id)}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def git_contains(minimum: str, deployed: str) -> bool:
    for commit in (minimum, deployed):
        subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], check=True)
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", minimum, deployed],
        check=False,
    ).returncode == 0


def normalize_aliases(payload: Any) -> set[str]:
    rows = payload.get("aliases", payload) if isinstance(payload, dict) else payload
    aliases: set[str] = set()
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, str):
                aliases.add(row.lower())
            elif isinstance(row, dict):
                value = row.get("alias") or row.get("name")
                if value:
                    aliases.add(str(value).lower())
    return aliases


def normalize_envs(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("envs", "environmentVariables", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def has_production_target(row: dict[str, Any]) -> bool:
    target = row.get("target")
    if target == "production":
        return True
    if isinstance(target, list) and "production" in target:
        return True
    return bool(row.get("applyToAllCustomEnvironments")) and target is None


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    evidence_path = Path(os.getenv("VERCEL_EVIDENCE_PATH", "/tmp/vercel-production-evidence.json"))
    evidence: dict[str, Any] = {
        "protocol": "vercel_production_release_gate_v1",
        "checked_environment_variable_values": False,
        "secret_values_recorded": False,
        "result": "pending",
    }
    try:
        token = required("VERCEL_TOKEN")
        project_id = required("VERCEL_PROJECT_ID")
        team_id = os.getenv("VERCEL_TEAM_ID", "").strip()
        production_domain = required("VERCEL_PRODUCTION_DOMAIN").lower().removeprefix("https://").rstrip("/")
        minimum_commit = required("EXPECTED_MINIMUM_COMMIT")
        required_envs = {
            item.strip() for item in required("VERCEL_REQUIRED_ENV_NAMES").split(",") if item.strip()
        }

        deployments = api_get(
            f"/v6/deployments?projectId={urllib.parse.quote(project_id)}&target=production&state=READY&limit=20",
            token,
            team_id,
        )
        rows = deployments.get("deployments", []) if isinstance(deployments, dict) else []
        if not rows:
            raise RuntimeError("No READY Vercel production deployment found")
        rows = sorted(
            [row for row in rows if isinstance(row, dict)],
            key=lambda row: int(row.get("created") or row.get("createdAt") or 0),
            reverse=True,
        )
        deployment = rows[0]
        deployment_id = str(deployment.get("uid") or deployment.get("id") or "").strip()
        if not deployment_id:
            raise RuntimeError("Production deployment has no ID")
        state = str(deployment.get("readyState") or deployment.get("state") or "").upper()
        target = str(deployment.get("target") or "").lower()
        if state != "READY" or target != "production":
            raise RuntimeError(f"Latest deployment is not READY production: state={state}, target={target}")

        detail = api_get(f"/v13/deployments/{urllib.parse.quote(deployment_id)}", token, team_id)
        if not isinstance(detail, dict):
            raise RuntimeError("Vercel deployment detail response is invalid")
        meta = detail.get("meta") if isinstance(detail.get("meta"), dict) else {}
        git_source = detail.get("gitSource") if isinstance(detail.get("gitSource"), dict) else {}
        deployed_commit = str(
            meta.get("githubCommitSha")
            or meta.get("gitCommitSha")
            or git_source.get("sha")
            or ""
        ).strip()
        if len(deployed_commit) != 40:
            raise RuntimeError("Vercel deployment does not expose a 40-character Git commit SHA")
        if not git_contains(minimum_commit, deployed_commit):
            raise RuntimeError(
                f"Deployed commit {deployed_commit} does not contain required commit {minimum_commit}"
            )

        alias_payload = api_get(f"/v2/deployments/{urllib.parse.quote(deployment_id)}/aliases", token, team_id)
        aliases = normalize_aliases(alias_payload)
        if production_domain not in aliases:
            raise RuntimeError(
                f"Production domain {production_domain} is not assigned to deployment {deployment_id}"
            )

        env_payload = api_get(f"/v10/projects/{urllib.parse.quote(project_id)}/env?decrypt=false", token, team_id)
        env_rows = normalize_envs(env_payload)
        production_env_names = {
            str(row.get("key") or "") for row in env_rows if has_production_target(row)
        }
        missing_envs = sorted(required_envs - production_env_names)
        if missing_envs:
            raise RuntimeError(f"Missing Vercel Production environment variable names: {missing_envs}")

        evidence.update({
            "deployment_id": deployment_id,
            "deployment_state": state,
            "deployment_target": target,
            "deployment_url": str(detail.get("url") or deployment.get("url") or ""),
            "deployed_commit": deployed_commit,
            "required_minimum_commit": minimum_commit,
            "minimum_commit_contained": True,
            "production_domain": production_domain,
            "production_domain_alias_matches": True,
            "required_environment_variable_names": sorted(required_envs),
            "production_environment_variable_names_present": sorted(required_envs),
            "result": "success",
        })
        write_evidence(evidence_path, evidence)
        print(f"Vercel production deployment {deployment_id} contains {minimum_commit} and owns {production_domain}")
        return 0
    except Exception as error:
        evidence.update({
            "result": "failure",
            "error_type": type(error).__name__,
            "error": str(error),
        })
        write_evidence(evidence_path, evidence)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
