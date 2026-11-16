"""Fail-safe identity clustering guards for the production pipeline entrypoint.

The core identity stage still asks Gemini/CLIP for grouping suggestions. This
runtime guard makes the dangerous cases deterministic: uncertain multi-clip
clusters without perception evidence are split, and verifier failures split
multi-appearance clusters instead of keeping risky mixed-athlete reels.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_MIN_VISIBLE_RATIO = 0.35
_INSTALLED_FLAG = "_sportreel_identity_failsafe_installed"


def _score_visible_ratio(event: dict[str, Any]) -> float:
    try:
        return float(event.get("visible_ratio", 1.0))
    except (TypeError, ValueError):
        return 0.0


def _event_has_perception_evidence(event: dict[str, Any]) -> bool:
    if event.get("bbox_xyxy") is None:
        return False
    if event.get("perception_crop_usable") is False:
        return False
    return _score_visible_ratio(event) >= _MIN_VISIBLE_RATIO


def _appearance_has_perception_evidence(app: dict[str, Any]) -> bool:
    return any(_event_has_perception_evidence(ev) for ev in app.get("events", []) or [])


def _cluster_has_perception_evidence(cluster: dict[str, Any]) -> bool:
    apps = cluster.get("appearances", []) or []
    return bool(apps) and all(_appearance_has_perception_evidence(app) for app in apps)


def _confidence(cluster: dict[str, Any]) -> str:
    return str(cluster.get("_identity_confidence", "medium")).lower()


def _wrap_build_clusters(identity):
    def build_clusters_from_data(data: dict, clip_analyses: list[dict]) -> list[dict]:
        result: list[dict] = []
        used: set[tuple] = set()

        for cluster in data.get("clusters", []):
            confidence = str(cluster.get("confidence", "medium")).lower()
            resolved: list[dict] = []

            for app in cluster.get("appearances", []):
                entry = identity._resolve_model_appearance(app, clip_analyses)
                if not entry:
                    continue
                if entry["key"] in used:
                    logger.warning(
                        "Duplicate identity appearance ignored: clip=%s person=%s",
                        entry["clip_index"], entry["person_id"],
                    )
                    continue
                used.add(entry["key"])
                appearance = identity._appearance_from_entry(entry)
                appearance["_description"] = entry.get("description", "unknown athlete")
                resolved.append(appearance)

            if not resolved:
                continue

            out_cluster = {
                "description": cluster.get("description", "unknown athlete"),
                "appearances": resolved,
                "_identity_confidence": confidence,
            }

            if confidence in ("medium", "low") and len(resolved) > 1:
                logger.warning(
                    "⚠️ Cluster '%s' spans %d clips with confidence=%s — fail-safe checks apply",
                    cluster.get("description", "?"), len(resolved), confidence,
                )
                print(
                    f"  ⚠️ Identity confidence={confidence} for "
                    f"'{cluster.get('description','?')[:40]}' across {len(resolved)} clip(s)"
                )

            if confidence == "low" and len(resolved) > 1:
                result.extend(identity._split_cluster_to_singles(out_cluster, "low model confidence"))
            elif confidence == "medium" and len(resolved) > 1 and not _cluster_has_perception_evidence(out_cluster):
                result.extend(identity._split_cluster_to_singles(
                    out_cluster,
                    "medium confidence without bbox perception evidence",
                ))
            elif identity._cluster_has_same_clip_conflict(out_cluster):
                result.extend(identity._split_cluster_to_singles(
                    out_cluster,
                    "same source clip contains multiple people",
                ))
            elif identity._cluster_has_number_conflict(out_cluster):
                result.extend(identity._split_cluster_to_singles(
                    out_cluster,
                    "conflicting jersey/bib numbers",
                ))
            else:
                result.append(out_cluster)

        return result

    return build_clusters_from_data


def _wrap_verify_multi_clusters(identity):
    """Same single verifier as identity._verify_multi_clusters (pairwise consensus, fail-closed): the model access is
    looked up on `identity` at call time so there is exactly one prompt and one decision rule in the whole pipeline."""
    def verify_multi_clusters(clusters: list[dict]) -> list[dict]:
        from pipeline import identity_pair_consensus
        return identity_pair_consensus.verify_multi_clusters(
            clusters, ask=identity._consensus_ask, split_to_singles=identity._split_cluster_to_singles)

    return verify_multi_clusters


def install() -> None:
    """Patch identity clustering before orchestrator imports cluster_clips."""
    import pipeline.stages.identity as identity

    if getattr(identity, _INSTALLED_FLAG, False):
        return

    identity._build_clusters_from_data = _wrap_build_clusters(identity)
    identity._verify_multi_clusters = _wrap_verify_multi_clusters(identity)
    setattr(identity, _INSTALLED_FLAG, True)
