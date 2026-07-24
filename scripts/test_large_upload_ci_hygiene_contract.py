#!/usr/bin/env python3
"""Fail closed if PR validation can mutate the branch or validate a synthetic merge ref."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/large-upload-foundation-check.yml"
ONE_SHOT_PATHS = (
    ROOT / ".github/workflows/apply-final-upload-review-fixes.yml",
    ROOT / "scripts/apply_final_upload_review_fixes.py",
    ROOT / "scripts/fix_final_upload_patch_type_errors.py",
)


def main() -> int:
    source = WORKFLOW.read_text(encoding="utf-8")

    required = [
        "permissions:\n  contents: read",
        "github.event.pull_request.head.sha",
        "git diff --check \"$BASE_SHA\"...HEAD -- . ':(exclude)*.md'",
        "python scripts/test_large_upload_foundation_contract.py",
        "python scripts/test_upload_batch_verified_gate_contract.py",
        "python scripts/test_upload_foundation_release_contract.py",
        "python scripts/test_multi_upload_batch_contract.py",
        "python scripts/test_exact_source_upload_dedup_contract.py",
        "python scripts/test_batch_scope_contract.py",
        "npm test -- --runInBand src/features/operator/lib/uploadQueue.test.ts",
        "expo-modules-autolinking resolve --platform android",
        "./gradlew :app:compileDebugKotlin --no-daemon --stacktrace",
    ]
    missing = [token for token in required if token not in source]
    if missing:
        raise SystemExit(f"large-upload CI hygiene contract missing: {missing}")

    forbidden = [
        "contents: write",
        "apply-final-review-fixes",
        "git push",
        "apply_final_upload_review_fixes.py",
        "fix_final_upload_patch_type_errors.py",
    ]
    present = [token for token in forbidden if token in source]
    if present:
        raise SystemExit(f"large-upload CI contains mutable one-shot machinery: {present}")

    leftovers = [str(path.relative_to(ROOT)) for path in ONE_SHOT_PATHS if path.exists()]
    if leftovers:
        raise SystemExit(f"one-shot patch files must not remain in the final PR: {leftovers}")

    print("Large-upload CI hygiene contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
