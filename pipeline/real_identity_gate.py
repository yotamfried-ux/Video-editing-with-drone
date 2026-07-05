"""Real-output identity gate for mixed-athlete prevention."""
from __future__ import annotations

import sys
from typing import Any

_INSTALLED_FLAG = "_sportreel_real_identity_gate_installed"
_QA_WRAPPED = "_sportreel_real_identity_gate_wrapped_qa"


def _event_id(event: dict[str, Any], index: int) -> str:
    return str(event.get("event_id") or event.get("id") or f"event_{index:03d}")


def _track_ids(app: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for event in app.get("events", []) or []:
        tid = event.get("track_id")
        if tid is not None and str(tid).strip():
            out.add(str(tid))
    return out


def _appearance_summary(app: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": app.get("path"),
        "track_ids": sorted(_track_ids(app)),
        "event_ids": [_event_id(event, idx) for idx, event in enumerate(app.get("events", []) or [])],
    }


def _stable_track(cluster: dict[str, Any]) -> str | None:
    apps = cluster.get("appearances", []) or []
    if len(apps) <= 1:
        return None
    per_app = [_track_ids(app) for app in apps]
    if not all(len(ids) == 1 for ids in per_app):
        return None
    all_ids = {next(iter(ids)) for ids in per_app}
    return next(iter(all_ids)) if len(all_ids) == 1 else None


def _identity_gate(reason: str, decision: str, cluster: dict[str, Any], app: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason": reason,
        "cluster_description": cluster.get("description", "unknown athlete"),
        "cluster_appearance_count": len(cluster.get("appearances", []) or []),
        "appearance": _appearance_summary(app),
    }


def _annotate_app(app: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    events = [{**event, "identity_gate": gate} for event in app.get("events", []) or []]
    return {**app, "events": events}


def enforce_identity_gate(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for cluster in clusters:
        apps = cluster.get("appearances", []) or []
        if len(apps) <= 1:
            result.append(cluster)
            continue
        stable = _stable_track(cluster)
        if stable:
            passed = []
            for app in apps:
                gate = _identity_gate("stable_track", "pass", cluster, app)
                gate["stable_track_id"] = stable
                passed.append(_annotate_app(app, gate))
            result.append({**cluster, "appearances": passed, "_identity_gate": "pass", "_stable_track_id": stable})
            continue
        reason = "missing_track_evidence"
        track_sets = [_track_ids(app) for app in apps]
        if any(track_sets) and len(set().union(*track_sets)) > 1:
            reason = "conflicting_track_ids"
        for index, app in enumerate(apps, start=1):
            gate = _identity_gate(reason, "split_to_single_appearance", cluster, app)
            result.append({
                "description": f"{cluster.get('description', 'unknown athlete')} identity-split {index}",
                "appearances": [_annotate_app(app, gate)],
                "_identity_gate": "split_to_single_appearance",
                "_identity_gate_reason": reason,
            })
    return result


def _patch_orchestrator(orchestrator: Any) -> None:
    if getattr(orchestrator, _INSTALLED_FLAG, False):
        return
    original = orchestrator._compile_clusters
    def wrapped(clusters, activity, fn_to_id=None):
        gated = enforce_identity_gate(clusters)
        if len(gated) != len(clusters):
            print(f"  Identity gate split {len(clusters)} cluster(s) into {len(gated)} safe cluster(s)")
        return original(gated, activity, fn_to_id)
    orchestrator._compile_clusters = wrapped
    setattr(orchestrator, _INSTALLED_FLAG, True)


def _wrap_existing_hook() -> bool:
    policy = sys.modules.get("pipeline.qa_gate_policy")
    if policy is None or getattr(policy, _QA_WRAPPED, False):
        return False
    original = getattr(policy, "_patch_orchestrator", None)
    if original is None:
        return False
    def patch_both(orchestrator: Any) -> None:
        original(orchestrator)
        _patch_orchestrator(orchestrator)
    policy._patch_orchestrator = patch_both
    setattr(policy, _QA_WRAPPED, True)
    return True


def install() -> None:
    module = sys.modules.get("pipeline.orchestrator")
    if module is not None:
        _patch_orchestrator(module)
        return
    if _wrap_existing_hook():
        return
    import pipeline.qa_gate_policy as policy
    policy.install()
    _wrap_existing_hook()
