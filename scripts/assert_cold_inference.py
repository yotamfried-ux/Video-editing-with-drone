"""Fail-closed inference isolation gate for the SportReel CI runner.

Run AFTER checkout and BEFORE pipeline inference, on an ephemeral runner.
Do not invoke on a developer's workstation: --prepare removes copied
evaluation fixtures from the checked-out working tree, never from Git or R2.

This gate is deliberately scoped to per-source memory; pretrained model
weights and installation caches are permitted. It is NOT proof of an unseen
footage holdout.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

# Do not modify these paths on a production asset store. They exist only
# inside the ephemeral GitHub Actions repository checkout.
EVALUATION_INPUTS = (
    "evaluation/ground_truth",
    "evaluation/qualification",
    "evaluation/identity_reviews",
)
KNOWN_MEMORY_DIRS = ("/tmp/llm-cache", "/tmp/llm-cache-cold-no-memory")


def _inside(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def enforce(root: Path, *, prepare: bool = False) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Cold-inference preparation is GitHub Actions only")
    if os.environ.get("SPORTREEL_STRICT_COLD_INFERENCE") != "1":
        raise RuntimeError("SPORTREEL_STRICT_COLD_INFERENCE=1 is required")
    if os.environ.get("LLM_CACHE", "").strip().lower() not in ("0", "false", "off", "no"):
        raise RuntimeError("Per-source AI and perception cache must be disabled")
    if os.environ.get("SPORTREEL_IDENTITY_REVIEW_DECISIONS", "").strip():
        raise RuntimeError("Prior manually confirmed identity decisions cannot be injected")
    if not (root / ".git").is_dir():
        raise RuntimeError("Not a Git checkout; refusing to remove evaluation fixtures")

    for relative in EVALUATION_INPUTS:
        path = root / relative
        if not _inside(path, root):
            raise RuntimeError(f"Unsafe evaluation path: {relative}")
        if prepare and path.exists():
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"Evaluation-only information visible to inference: {relative}")

    for relative in KNOWN_MEMORY_DIRS:
        path = Path(relative)
        if prepare and (path.exists() or path.is_symlink()):
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"Previous-run analysis cache remains: {relative}")

    # Important: this checks local fixture and cache access only. Operational
    # storage (R2/Supabase) and model prompts require separate provenance audits.
    print("COLD_INFERENCE_LOCAL_GATE_PASS: per-source cache disabled; no old local evaluation data")


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--prepare", action="store_true")
    args = cli.parse_args()
    try:
        enforce(Path.cwd(), prepare=args.prepare)
    except RuntimeError as exc:
        print(f"COLD_INFERENCE_GATE_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
