#!/usr/bin/env python3
"""Verify narrow R2 browser CORS only when a browser upload origin is configured.

The Android native client does not automatically require browser CORS. When a browser
origin is declared, this verifier fails unless PUT is allowed for that exact origin,
ETag is exposed, and no wildcard origin broadens access.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    origin = os.getenv("R2_BROWSER_UPLOAD_ORIGIN", "").strip().rstrip("/")
    evidence_path = Path(os.getenv("R2_CORS_EVIDENCE_PATH", "/tmp/r2-cors-evidence.json"))
    evidence: dict[str, Any] = {
        "protocol": "r2_cors_release_gate_v1",
        "browser_upload_origin": origin or None,
        "secret_values_recorded": False,
        "result": "pending",
    }

    try:
        if not origin:
            evidence.update({
                "cors_required": False,
                "reason": "native_android_upload_client",
                "etag_exposure_device_verification_pending": True,
                "result": "not_applicable",
            })
        else:
            account_id = required("R2_ACCOUNT_ID")
            bucket = required("R2_BUCKET")
            token = required("CLOUDFLARE_API_TOKEN")
            url = (
                "https://api.cloudflare.com/client/v4/accounts/"
                f"{urllib.parse.quote(account_id)}/r2/buckets/{urllib.parse.quote(bucket)}/cors"
            )
            request = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not payload.get("success"):
                raise RuntimeError("Cloudflare did not return a successful R2 CORS response")
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            rules = result.get("rules") if isinstance(result.get("rules"), list) else []
            matched = False
            wildcard = False
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                allowed = rule.get("allowed") if isinstance(rule.get("allowed"), dict) else {}
                origins = {str(value).rstrip("/") for value in allowed.get("origins") or []}
                methods = {str(value).upper() for value in allowed.get("methods") or []}
                exposed = {str(value).lower() for value in rule.get("exposeHeaders") or []}
                wildcard = wildcard or "*" in origins
                if origin in origins and "PUT" in methods and "etag" in exposed:
                    matched = True
            if wildcard:
                raise RuntimeError("R2 browser CORS contains a wildcard origin")
            if not matched:
                raise RuntimeError(
                    "R2 browser CORS does not allow the exact origin with PUT and exposed ETag"
                )
            evidence.update({
                "cors_required": True,
                "exact_origin_present": True,
                "put_allowed": True,
                "etag_exposed": True,
                "wildcard_origin_absent": True,
                "result": "success",
            })

        write_evidence(evidence_path, evidence)
        print(f"R2 CORS gate result: {evidence['result']}")
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
