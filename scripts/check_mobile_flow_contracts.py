#!/usr/bin/env python3
"""Static contract check for mobile Maestro flows and React Native component testIDs.

Validates that:
1. All Maestro YAML flow definitions parse as valid YAML documents.
2. All interactive testIDs referenced in the core mobile user journey flows exist
   in the React Native application source (mobile/src/**/*.tsx).
3. Reports runtime device capability (KVM/ADB) and points to GitHub Actions
   CI (.github/workflows/upl-01-android-app-upload-e2e.yml) for live E2E runs.

Run: python scripts/check_mobile_flow_contracts.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOBILE_DIR = ROOT / "mobile"
MAESTRO_DIR = MOBILE_DIR / ".maestro"


def check_flow_syntax() -> tuple[int, list[str]]:
    try:
        import yaml
    except ImportError:
        return 0, ["PyYAML is required but not installed. Install via: pip install pyyaml"]

    errors = []
    flow_files = sorted(MAESTRO_DIR.rglob("*.yaml"))
    if not flow_files:
        errors.append(f"No maestro YAML flows found in {MAESTRO_DIR}")
        return 0, errors

    for flow in flow_files:
        try:
            with flow.open("r", encoding="utf-8") as f:
                docs = list(yaml.safe_load_all(f))
                if not docs:
                    errors.append(f"{flow.name}: empty YAML document")
        except Exception as exc:
            errors.append(f"{flow.name}: YAML parse error: {exc}")

    return len(flow_files), errors


def check_testid_bindings() -> tuple[int, list[str]]:
    errors = []
    app_tsx = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (MOBILE_DIR / "src").rglob("*.tsx")
    )

    required_testids = [
        "login-email",
        "login-password",
        "login-submit",
        "login-create-account",
        "register-have-account",
        "register-name",
        "register-finish",
        "profile-name-input",
        "profile-contact-support",
        "support-message-input",
        "support-cancel",
        "support-send",
        "profile-suggest",
        "suggestion-message-input",
        "suggestion-cancel",
        "profile-sign-out",
        "operator-secret-input",
        "operator-secret-save",
        "pipeline-upload-gallery",
    ]

    for test_id in required_testids:
        pattern = rf'testID=["\']{re.escape(test_id)}["\']'
        if not re.search(pattern, app_tsx):
            errors.append(f"Missing testID binding in mobile app source: {test_id}")

    return len(required_testids), errors


def get_runtime_environment() -> dict:
    adb_cmd = shutil.which("adb")
    maestro_cmd = shutil.which("maestro")

    devices = []
    if adb_cmd:
        try:
            out = subprocess.check_output([adb_cmd, "devices"], text=True, timeout=5)
            lines = out.strip().splitlines()[1:]
            devices = [l.split()[0] for l in lines if "\tdevice" in l]
        except Exception:
            pass

    has_kvm = os.path.exists("/dev/kvm")
    return {
        "maestro_cli": maestro_cmd is not None,
        "adb_cli": adb_cmd is not None,
        "attached_devices": devices,
        "has_kvm": has_kvm,
    }


def main() -> int:
    print("=" * 65)
    print("Mobile Maestro Flow Contract & TestID Binding Verification")
    print("=" * 65)

    # 1. Flow syntax verification
    count_flows, syntax_errors = check_flow_syntax()
    if syntax_errors:
        print("[FAIL] Flow syntax errors:")
        for err in syntax_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"[PASS] Flow Syntax: All {count_flows} Maestro YAML flow files parsed successfully.")

    # 2. TestID binding verification
    count_testids, binding_errors = check_testid_bindings()
    if binding_errors:
        print("[FAIL] TestID binding errors:")
        for err in binding_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"[PASS] TestID Bindings: All {count_testids} user-journey testIDs exist in mobile/src.")

    # 3. Environment qualification note
    env = get_runtime_environment()
    print("\n--- Runtime Device Environment ---")
    print(f"  Maestro CLI installed: {env['maestro_cli']}")
    print(f"  ADB CLI installed:     {env['adb_cli']}")
    print(f"  Connected devices:     {env['attached_devices'] if env['attached_devices'] else 'None'}")
    print(f"  KVM acceleration:      {'Available' if env['has_kvm'] else 'Not available (cloud container)'}")

    if not env["attached_devices"]:
        print("\n[NOTE] No connected device or emulator available in current environment.")
        print("  - Cloud container lacks /dev/kvm and adb daemon (interactive exploration is blocked).")
        print("  - Full UI interaction runs on developer workstation with Android device/emulator.")
        print("  - Deterministic CI verification runs in GitHub Actions on ubuntu-24.04 with KVM")
        print("    via workflow: .github/workflows/upl-01-android-app-upload-e2e.yml")

    print("\n[PASS] Mobile flow contract verification succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
