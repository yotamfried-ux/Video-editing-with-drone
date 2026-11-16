"""Runtime policy registry: what actually runs, measured after bootstrap (RC-09).

The pipeline installs ordered monkey-patches (`pipeline.bootstrap`). A unit test of one function does not show that
the function is the one a tracked run calls. After `install_post_orchestrator_patches` this module resolves, for each
safety-critical stage, the effective function and its wrapper chain (following each wrapper's `original` / `__wrapped__`),
records the install flags, checks that every mandatory policy is in the chain, and writes the result as a run artifact
(`runtime_policy_registry.json`). A missing mandatory policy makes the bootstrap fail before any footage is processed.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

SCHEMA = "sportreel.runtime_policy_registry.v1"

# stage -> (module, attribute, mandatory policies: substrings that must appear in the effective wrapper chain)
STAGES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "identity_verification": ("pipeline.stages.identity", "_verify_multi_clusters", ("pipeline.identity_failsafe",)),
    # context_qa_gate reimplements _compile_clusters and calls the gate inline: proven by the execution probe below.
    "identity_gate": ("pipeline.orchestrator", "_compile_clusters", ()),
    "final_qa_gate": ("pipeline.orchestrator", "_qa_gate", ("pipeline.publishable_qa_evidence",
                                                            "pipeline.publishable_reel_policy",
                                                            "pipeline.qa_gate_policy")),
    "draft_lineage_and_qa_task": ("pipeline.orchestrator", "_save_reel_metadata", ("pipeline.draft_identity_metadata",
                                                                                   "pipeline.qa_gate_policy")),
    "publication_manifest": ("pipeline.orchestrator", "upload_draft", ("pipeline.publishable_reel_policy",)),
    "output_qualification": ("pipeline.publishable_reel_policy", "record_athlete_outcome", ()),
    "render_window": ("pipeline.stages.editor", "cut_clip", ("pipeline.qa_reedit_window_contract",
                                                              "pipeline.complete_action_window_policy",
                                                              "pipeline.quality_preserving_framing")),
}

_ORIGINAL_NAMES = ("original", "base", "inner", "wrapped", "prior", "previous", "fn", "func")


def _next_in_chain(fn: Any) -> Any:
    wrapped = getattr(fn, "__wrapped__", None)
    if callable(wrapped):
        return wrapped
    code, closure = getattr(fn, "__code__", None), getattr(fn, "__closure__", None) or ()
    if code is None or not closure:
        return None
    cells = dict(zip(code.co_freevars, closure))
    for name in code.co_freevars:  # a free variable named like the wrapped function
        if any(token in name.lower() for token in _ORIGINAL_NAMES):
            try:
                value = cells[name].cell_contents
            except ValueError:
                continue
            if inspect.isfunction(value) or inspect.ismethod(value):
                return value
    functions = []
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if inspect.isfunction(value):
            functions.append(value)
    return functions[0] if len(functions) == 1 else None


def chain(fn: Any, limit: int = 30) -> list[str]:
    out: list[str] = []
    seen: set[int] = set()
    while fn is not None and id(fn) not in seen and len(out) < limit:
        seen.add(id(fn))
        out.append(f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', getattr(fn, '__name__', '?'))}")
        fn = _next_in_chain(fn)
    return out


class _ProbeReached(Exception):
    pass


def probe_identity_gate() -> dict[str, Any]:
    """Execution proof that the effective _compile_clusters calls real_identity_gate.enforce_identity_gate first.

    The gate is replaced by a sentinel for one call with no clusters; the original is always restored. Nothing is
    rendered: the sentinel stops the call before any work.
    """
    import pipeline.orchestrator as orchestrator
    from pipeline import real_identity_gate

    original = real_identity_gate.enforce_identity_gate

    def sentinel(clusters):
        raise _ProbeReached()

    real_identity_gate.enforce_identity_gate = sentinel
    try:
        orchestrator._compile_clusters([], "surfing", {})
        reached = False
    except _ProbeReached:
        reached = True
    except Exception as exc:  # the wrapper re-raises the gate's exception wrapped: look through the cause chain
        reached = False
        cause: BaseException | None = exc
        while cause is not None:
            if isinstance(cause, _ProbeReached):
                reached = True
                break
            cause = cause.__cause__ or cause.__context__
    finally:
        real_identity_gate.enforce_identity_gate = original
    return {"policy": "pipeline.real_identity_gate.enforce_identity_gate", "reached_by_execution": reached}


def probe_output_qualification() -> dict[str, Any]:
    """Execution proof that the manifest recorder derives qualification issues (an empty part is withheld)."""
    from pipeline import publishable_reel_policy
    issues = publishable_reel_policy._qualification_inputs([], "surfing")["issues"]
    return {"policy": "pipeline.output_qualification.build_inputs", "reached_by_execution": any("no_shots" in i for i in issues)}


PROBES = {"identity_gate": probe_identity_gate, "output_qualification": probe_output_qualification}


def snapshot() -> dict[str, Any]:
    stages: dict[str, Any] = {}
    problems: list[str] = []
    for stage, (module_name, attr, required) in STAGES.items():
        module = sys.modules.get(module_name)
        fn = getattr(module, attr, None) if module is not None else None
        links = chain(fn) if fn is not None else []
        missing = [policy for policy in required if not any(link.startswith(policy + ".") for link in links)]
        stages[stage] = {"target": f"{module_name}.{attr}", "effective": links[0] if links else None,
                         "chain": links, "required_policies": list(required), "missing_policies": missing}
        if stage in PROBES and fn is not None:
            try:
                proof = PROBES[stage]()
            except Exception as exc:  # noqa: BLE001 - a probe that cannot run proves nothing
                proof = {"reached_by_execution": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            stages[stage]["execution_probe"] = proof
            if proof.get("reached_by_execution") is not True:
                problems.append(f"{stage}: execution probe did not reach {proof.get('policy', 'the policy')}")
        if fn is None:
            problems.append(f"{stage}: {module_name}.{attr} not loaded")
        problems.extend(f"{stage}: mandatory policy {policy} not in the effective call chain" for policy in missing)
    flags = sorted(f"{name}.{key}" for name, module in list(sys.modules.items())
                   if name.startswith(("pipeline", "integrations")) and module is not None
                   for key in list(vars(module)) if key.startswith("_sportreel_") and key.endswith("installed")
                   and getattr(module, key, False) is True)
    body = {"schema": SCHEMA, "entrypoint": os.path.basename(sys.argv[0] or "") or None, "stages": stages,
            "install_flags": flags, "problems": problems}
    body["digest"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def record_and_enforce(path: str | None = None) -> dict[str, Any]:
    """Write the registry artifact; raise when a mandatory policy is not effective (fail before processing)."""
    body = snapshot()
    target = Path(path or os.path.join(os.getenv("TMP_DIR", "/tmp/dtor"), "pipeline-debug", "runtime_policy_registry.json"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, indent=2), encoding="utf-8")
    except OSError:
        pass
    if body["problems"]:
        raise RuntimeError("runtime policy registry: " + "; ".join(body["problems"]))
    return body
