#!/usr/bin/env python3
"""Prove removed biometric identifiers are absent from live application surfaces."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIERS = (
    "face_embedding",
    "photo_path",
    "matched_athlete",
    "match_athlete_face",
    "athlete-photos",
)
SURFACES = {
    "registration": ("mobile/src/app/(auth)/register.tsx",),
    "login": ("mobile/src/app/(auth)/login.tsx",),
    "profile": ("mobile/src/app/(tabs)/profile.tsx", "mobile/src/features/profile"),
    "discover": ("mobile/src/app/(tabs)/discover.tsx", "mobile/src/features/discover", "web-api/src/app/api/discover"),
    "checkout": ("mobile/src/app/checkout", "mobile/src/features/payment", "web-api/src/app/api/checkout"),
    "support": ("mobile/src/app/support", "web-api/src/app/api/support"),
    "delivery": ("services/delivery.py", "web-api/src/app/api/delivery", "mobile/src/features/video"),
}
LIVE_ROOTS = (ROOT / "mobile" / "src", ROOT / "web-api" / "src", ROOT / "services")


def text_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    return [
        item for item in path.rglob("*")
        if item.is_file() and item.suffix.lower() in {".ts", ".tsx", ".js", ".jsx", ".py"}
    ]


def scan(paths: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted(set(paths)):
        source = path.read_text(encoding="utf-8", errors="replace")
        for identifier in IDENTIFIERS:
            if identifier in source:
                findings.append({"path": str(path.relative_to(ROOT)), "identifier": identifier})
    return findings


def main() -> int:
    evidence_path = Path(os.getenv("NO_BIOMETRIC_EVIDENCE_PATH", "/tmp/no-biometric-runtime-evidence.json"))
    evidence: dict[str, Any] = {
        "protocol": "no_biometric_runtime_dependencies_v1",
        "identifiers": list(IDENTIFIERS),
        "surfaces": {},
        "result": "pending",
    }
    all_findings: list[dict[str, Any]] = []

    for name, configured in SURFACES.items():
        files: list[Path] = []
        for relative in configured:
            files.extend(text_files(ROOT / relative))
        files = sorted(set(files))
        if not files:
            raise RuntimeError(f"No live files were resolved for required surface: {name}")
        findings = scan(files)
        evidence["surfaces"][name] = {
            "files_checked": [str(path.relative_to(ROOT)) for path in files],
            "obsolete_identifier_findings": findings,
        }
        all_findings.extend(findings)

    broad_files: list[Path] = []
    for root in LIVE_ROOTS:
        broad_files.extend(text_files(root))
    broad_findings = scan(broad_files)
    evidence["broad_runtime_scan"] = {
        "file_count": len(set(broad_files)),
        "obsolete_identifier_findings": broad_findings,
    }
    all_findings.extend(broad_findings)

    if all_findings:
        unique = sorted({(row["path"], row["identifier"]) for row in all_findings})
        raise RuntimeError(f"Obsolete biometric runtime identifiers remain: {unique}")

    evidence["result"] = "success"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    print("No removed biometric identifiers remain in registration, login, profile, Discover, checkout, support, delivery, or other live runtime paths")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        path = Path(os.getenv("NO_BIOMETRIC_EVIDENCE_PATH", "/tmp/no-biometric-runtime-evidence.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps({
                "protocol": "no_biometric_runtime_dependencies_v1",
                "result": "failure",
                "error_type": type(error).__name__,
                "error": str(error),
            }, indent=2, sort_keys=True), encoding="utf-8")
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
