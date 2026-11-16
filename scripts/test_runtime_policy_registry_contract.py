#!/usr/bin/env python3
"""Runtime policy registry (RC-09, T11): the real bootstrap's effective policies, measured by execution.

 RP1 After the real bootstrap every safety-critical stage resolves to a chain that contains its mandatory policies,
     the identity gate and the output qualification are reached by an execution probe, and the artifact is written.
 RP2 Removing an installed wrapper (identity failsafe) or bypassing the identity gate makes the registry refuse.
 RP3 Every pipeline entrypoint runs the same bootstrap pair, so the same registry check applies to all of them.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("supabase", types.SimpleNamespace(create_client=lambda *a, **k: None, Client=object))
os.environ.setdefault("GEMINI_API_KEY", "test-only")

ENTRYPOINTS = ("run.py", "run_surf.py", "scripts/run_tracked.py", "scripts/reset_and_rerun.py")


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(message)


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        os.environ["TMP_DIR"] = folder
        import pipeline.bootstrap as bootstrap
        bootstrap.install_pre_orchestrator_patches()
        import pipeline.orchestrator  # noqa: F401
        bootstrap.install_post_orchestrator_patches()  # runs record_and_enforce: raises if a policy is not effective
        artifact = Path(folder) / "pipeline-debug" / "runtime_policy_registry.json"
        check(artifact.is_file(), "RP1: the registry artifact was not written")
        body = json.loads(artifact.read_text())
        check(not body["problems"], f"RP1: {body['problems']}")
        for stage in ("identity_gate", "output_qualification"):
            check(body["stages"][stage]["execution_probe"]["reached_by_execution"] is True,
                  f"RP1: {stage} not reached by execution")
        check(body["stages"]["identity_verification"]["effective"].startswith("pipeline.identity_failsafe."),
              "RP1: the identity verifier is not the failsafe")

        from pipeline import real_identity_gate, runtime_policy_registry
        from pipeline.stages import identity
        installed = identity._verify_multi_clusters
        identity._verify_multi_clusters = lambda clusters: clusters  # an entrypoint that skipped the failsafe
        try:
            runtime_policy_registry.record_and_enforce(str(Path(folder) / "r1.json"))
            raise SystemExit("RP2: a missing identity failsafe was not refused")
        except RuntimeError as exc:
            check("identity_verification" in str(exc), f"RP2: wrong refusal: {exc}")
        finally:
            identity._verify_multi_clusters = installed
        import pipeline.orchestrator as orchestrator
        compiled = orchestrator._compile_clusters
        orchestrator._compile_clusters = lambda clusters, activity, fn_to_id=None: 0  # gate bypassed
        try:
            runtime_policy_registry.record_and_enforce(str(Path(folder) / "r2.json"))
            raise SystemExit("RP2: a bypassed identity gate was not refused")
        except RuntimeError as exc:
            check("identity_gate" in str(exc), f"RP2: wrong refusal: {exc}")
        finally:
            orchestrator._compile_clusters = compiled
        check(real_identity_gate.enforce_identity_gate.__name__ == "enforce_identity_gate",
              "RP2: the probe did not restore the identity gate")

    for path in ENTRYPOINTS:
        text = (ROOT / path).read_text(encoding="utf-8")
        pre, post = text.find("install_pre_orchestrator_patches()"), text.find("install_post_orchestrator_patches()")
        check(0 <= pre < post, f"RP3: {path} does not run the bootstrap pair in order")
    print("PASS: runtime policy registry (effective chains, execution probes, fail-closed, all entrypoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
