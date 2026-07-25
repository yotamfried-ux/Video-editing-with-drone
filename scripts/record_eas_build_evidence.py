#!/usr/bin/env python3
"""Validate EAS cloud build JSON and produce redacted immutable APK evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def first_build(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict):
        for key in ("builds", "data"):
            rows = payload.get(key)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                return rows[0]
        return payload
    raise RuntimeError("EAS build output is not a build object")


def nested(row: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = row
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if value not in (None, ""):
            return value
    return None


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-json", required=True)
    parser.add_argument("--apk", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args()

    evidence_path = Path(args.evidence)
    evidence: dict[str, Any] = {
        "protocol": "eas_android_preview_release_gate_v1",
        "native_module_required": "SportReelSourceReader",
        "installed_on_device": False,
        "secret_values_recorded": False,
        "result": "pending",
    }
    try:
        expected_commit = os.getenv("GITHUB_SHA", "").strip()
        if len(expected_commit) != 40:
            raise RuntimeError("GITHUB_SHA must be the exact 40-character release commit")
        row = first_build(json.loads(Path(args.build_json).read_text(encoding="utf-8")))
        build_id = str(row.get("id") or "").strip()
        status = str(row.get("status") or "").upper().replace("-", "_")
        platform = str(row.get("platform") or "").upper()
        profile = str(row.get("buildProfile") or row.get("build_profile") or "").strip()
        commit = str(nested(
            row,
            ("gitCommitHash",),
            ("git_commit_hash",),
            ("metadata", "gitCommitHash"),
        ) or "").strip()
        runtime = str(nested(
            row,
            ("runtimeVersion",),
            ("runtime_version",),
            ("metadata", "runtimeVersion"),
        ) or "").strip()
        channel = str(nested(row, ("channel",), ("metadata", "channel")) or "").strip()
        distribution = str(row.get("distribution") or "").upper()

        if not build_id:
            raise RuntimeError("EAS build output has no build ID")
        if status not in {"FINISHED", "COMPLETED", "SUCCESS"}:
            raise RuntimeError(f"EAS build is not finished successfully: {status}")
        if platform != "ANDROID":
            raise RuntimeError(f"EAS build platform is not ANDROID: {platform}")
        if profile != "preview":
            raise RuntimeError(f"EAS build profile is not preview: {profile}")
        if commit != expected_commit:
            raise RuntimeError(f"EAS build commit mismatch: expected {expected_commit}, got {commit or 'missing'}")
        if not runtime:
            raise RuntimeError("EAS build output has no runtime version")
        if channel != "preview":
            raise RuntimeError(f"EAS build channel mismatch: expected preview, got {channel or 'missing'}")
        if distribution != "INTERNAL":
            raise RuntimeError(f"EAS build distribution is not internal: {distribution or 'missing'}")

        apk = Path(args.apk)
        if not apk.is_file() or apk.stat().st_size <= 0:
            raise RuntimeError("Downloaded APK artifact is missing or empty")
        digest = hashlib.sha256(apk.read_bytes()).hexdigest()
        evidence.update({
            "build_id": build_id,
            "status": status,
            "platform": platform,
            "profile": profile,
            "distribution": distribution,
            "git_commit_hash": commit,
            "runtime_version": runtime,
            "channel": channel,
            "artifact_filename": apk.name,
            "artifact_size_bytes": apk.stat().st_size,
            "artifact_sha256": digest,
            "result": "success",
        })
        write_evidence(evidence_path, evidence)
        if args.github_output:
            with Path(args.github_output).open("a", encoding="utf-8") as output:
                output.write(f"build_id={build_id}\n")
        print(f"EAS Android preview build verified: {build_id}")
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
