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
    def verify_multi_clusters(clusters: list[dict]) -> list[dict]:
        verified: list[dict] = []
        for cluster in clusters:
            apps = cluster.get("appearances", []) or []
            thumbs = [a.get("thumbnail", "") for a in apps]
            if len(apps) < 2:
                verified.append(cluster)
                continue
            if not all(t and os.path.exists(t) for t in thumbs):
                verified.extend(identity._split_cluster_to_singles(
                    cluster,
                    "missing thumbnails for identity verification",
                ))
                continue

            uploaded: list = []
            try:
                content: list = []
                for i, thumb_path in enumerate(thumbs):
                    gfile = identity.genai.upload_file(path=thumb_path, mime_type="image/jpeg")
                    uploaded.append(gfile)
                    content.append(f"[Image {i}]:")
                    content.append(gfile)
                content.append(identity._VERIFY_PROMPT)

                model = identity.genai.GenerativeModel(model_name="gemini-2.5-flash")
                raw = identity._retry_gemini(lambda: model.generate_content(
                    content, request_options={"timeout": 60}
                ).text.strip())
                parsed = identity._parse_json_response(raw)
                same_person = bool(parsed.get("same_person", not parsed.get("mismatched_indices")))
                bad = {
                    int(i) for i in parsed.get("mismatched_indices", [])
                    if isinstance(i, (int, float)) and 0 <= int(i) < len(apps)
                }

                if same_person and not bad:
                    verified.append(cluster)
                    continue

                if not bad or len(bad) >= len(apps):
                    verified.extend(identity._split_cluster_to_singles(
                        cluster,
                        "visual verifier could not confirm same athlete",
                    ))
                    continue

                keep = [a for i, a in enumerate(apps) if i not in bad]
                split = [a for i, a in enumerate(apps) if i in bad]
                print(
                    f"  ✂️  Identity verification split {len(split)} clip(s) out of "
                    f"'{cluster.get('description','?')[:40]}' — different athlete detected"
                )
                logger.warning(
                    "Identity verify: split %d/%d appearance(s) from '%s'",
                    len(split), len(apps), cluster.get("description", "?"),
                )
                verified.append({**cluster, "appearances": keep})
                for app in split:
                    verified.append({
                        "description": app.get("_description")
                        or cluster.get("description", "unknown athlete") + " (separated)",
                        "appearances": [app],
                    })
            except Exception as exc:
                logger.warning(
                    "Cluster verification failed (%s) — splitting risky multi-appearance cluster",
                    exc,
                )
                verified.extend(identity._split_cluster_to_singles(
                    cluster,
                    "identity verifier error",
                ))
            finally:
                for gfile in uploaded:
                    try:
                        identity.genai.delete_file(gfile.name)
                    except Exception:
                        pass

        return verified

    return verify_multi_clusters


def install() -> None:
    """Patch identity clustering before orchestrator imports cluster_clips."""
    import pipeline.stages.identity as identity

    if getattr(identity, _INSTALLED_FLAG, False):
        return

    identity._build_clusters_from_data = _wrap_build_clusters(identity)
    identity._verify_multi_clusters = _wrap_verify_multi_clusters(identity)
    setattr(identity, _INSTALLED_FLAG, True)
