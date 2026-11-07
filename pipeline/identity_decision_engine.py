"""Unified Identity Decision Engine (OPT-03).

Consolidates all athlete identity signals into one calibrated, reproducible decision
layer returning one of three verdicts:
  - "MATCH": verified same athlete across appearances/clusters
  - "NO_MATCH": hard conflict or distinct athletes
  - "UNCERTAIN": ambiguous evidence; must NOT be auto-merged or auto-published without confirmation

Invariants:
  1. Two appearances from the same source video are NEVER merged ("same_source_clip_conflict").
  2. Identical numeric `track_id` values from DIFFERENT source videos are completely independent
     tracker counters and NEVER contribute positive identity evidence ("cross_source_numeric_track_id_ignored").
  3. Equipment similarity alone is never sufficient proof of identity without compatible athlete apparel/features.
  4. Every decision produces a deterministic `evidence_trace` dictionary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class IdentityDecision:
    decision: str  # "MATCH" | "NO_MATCH" | "UNCERTAIN"
    score: float
    uncertainty: float
    reasons: list[str] = field(default_factory=list)
    evidence_trace: dict[str, Any] = field(default_factory=dict)
    auto_publish_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "score": round(self.score, 4),
            "uncertainty": round(self.uncertainty, 4),
            "reasons": list(self.reasons),
            "auto_publish_allowed": self.auto_publish_allowed,
            "evidence_trace": dict(self.evidence_trace),
        }


def _source_name(item: Mapping[str, Any]) -> str:
    for key in ("source", "path", "source_video", "_src"):
        val = item.get(key)
        if val:
            return Path(str(val)).name
    if item.get("_clip_index") is not None:
        return f"clip_{item.get('_clip_index')}"
    return ""


def _person_key(item: Mapping[str, Any]) -> str:
    if item.get("source_person_key"):
        return str(item["source_person_key"])
    for ev in item.get("events", []) or []:
        if isinstance(ev, Mapping) and ev.get("source_person_key"):
            return str(ev["source_person_key"])
    src = _source_name(item)
    pid = str(item.get("_person_id") or item.get("person_id") or item.get("id") or "")
    return f"{src}::{pid}" if (src or pid) else ""


def _scoped_track_ids(item: Mapping[str, Any]) -> list[str]:
    src = _source_name(item)
    tids: set[str] = set()
    if item.get("track_id") is not None:
        tids.add(f"{src}::track_{item.get('track_id')}")
    for ev in item.get("events", []) or []:
        if isinstance(ev, Mapping):
            tid = ev.get("target_track_id") or ev.get("track_id")
            if tid is not None:
                ev_src = _source_name(ev) or src
                tids.add(f"{ev_src}::track_{tid}")
    return sorted(tids)


def _raw_numeric_track_ids(item: Mapping[str, Any]) -> set[str]:
    tids: set[str] = set()
    if item.get("track_id") is not None:
        tids.add(str(item.get("track_id")))
    for ev in item.get("events", []) or []:
        if isinstance(ev, Mapping):
            tid = ev.get("target_track_id") or ev.get("track_id")
            if tid is not None:
                tids.add(str(tid))
    return tids


class IdentityDecisionEngine:
    """Calibrated central engine for pairwise and cluster-level athlete identity decisions."""

    def __init__(
        self,
        *,
        match_threshold: float = 0.85,
        uncertain_floor: float = 0.50,
    ) -> None:
        self.match_threshold = float(match_threshold)
        self.uncertain_floor = float(uncertain_floor)

    def evaluate_pair(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        *,
        embedding_similarity: float | None = None,
        semantic_decision: str | None = None,
        semantic_confidence: str | None = None,
        visual_verified: bool | None = None,
    ) -> IdentityDecision:
        """Evaluate whether `left` and `right` represent the same athlete."""
        from pipeline.stages.identity import (
            _sleeve_styles_compatible,
            _top_colors_compatible,
            extract_structured_attributes,
            score_structured_identity_match,
        )

        src_left = _source_name(left)
        src_right = _source_name(right)
        clip_idx_left = left.get("_clip_index", left.get("clip_index"))
        clip_idx_right = right.get("_clip_index", right.get("clip_index"))
        key_left = _person_key(left)
        key_right = _person_key(right)
        scoped_tracks_left = _scoped_track_ids(left)
        scoped_tracks_right = _scoped_track_ids(right)
        raw_tracks_left = _raw_numeric_track_ids(left)
        raw_tracks_right = _raw_numeric_track_ids(right)

        same_numeric_track_diff_source = bool(
            src_left
            and src_right
            and src_left != src_right
            and (raw_tracks_left & raw_tracks_right)
        )

        desc_left = str(left.get("_description") or left.get("description") or "")
        desc_right = str(right.get("_description") or right.get("description") or "")
        attrs_left = extract_structured_attributes(desc_left)
        attrs_right = extract_structured_attributes(desc_right)
        struct_score = score_structured_identity_match(desc_left, desc_right)

        reasons: list[str] = []
        base_trace: dict[str, Any] = {
            "left_person_key": key_left,
            "right_person_key": key_right,
            "left_source": src_left,
            "right_source": src_right,
            "left_scoped_tracks": scoped_tracks_left,
            "right_scoped_tracks": scoped_tracks_right,
            "cross_source_numeric_track_overlap": sorted(raw_tracks_left & raw_tracks_right) if same_numeric_track_diff_source else [],
            "cross_source_numeric_track_id_ignored": True,
            "structured_score": round(struct_score, 4),
            "embedding_similarity": None if embedding_similarity is None else round(float(embedding_similarity), 4),
            "semantic_decision": semantic_decision,
            "semantic_confidence": semantic_confidence,
            "visual_verified": visual_verified,
            "left_attributes": {k: (sorted(v) if isinstance(v, set) else v) for k, v in attrs_left.items()},
            "right_attributes": {k: (sorted(v) if isinstance(v, set) else v) for k, v in attrs_right.items()},
        }

        # 1. Exact same source_person_key in the same source clip
        if key_left and key_left == key_right and (src_left == src_right) and src_left:
            return IdentityDecision(
                decision="MATCH",
                score=1.0,
                uncertainty=0.0,
                reasons=["identical_source_person_key"],
                evidence_trace=base_trace,
                auto_publish_allowed=True,
            )

        # 2. Hard conflict: two distinct appearances in the SAME source clip
        same_clip = (
            (clip_idx_left is not None and clip_idx_right is not None and clip_idx_left == clip_idx_right)
            or (src_left and src_right and src_left == src_right)
        )
        if same_clip:
            return IdentityDecision(
                decision="NO_MATCH",
                score=0.0,
                uncertainty=0.0,
                reasons=["same_source_clip_conflict"],
                evidence_trace=base_trace,
                auto_publish_allowed=False,
            )

        # 3. Jersey / bib number hard rules
        nums_l = attrs_left.get("numbers") or set()
        nums_r = attrs_right.get("numbers") or set()
        if nums_l and nums_r:
            if nums_l != nums_r:
                return IdentityDecision(
                    decision="NO_MATCH",
                    score=0.0,
                    uncertainty=0.0,
                    reasons=["conflicting_jersey_or_bib_numbers"],
                    evidence_trace=base_trace,
                    auto_publish_allowed=False,
                )
            reasons.append("matching_jersey_or_bib_number")
            return IdentityDecision(
                decision="MATCH",
                score=0.99,
                uncertainty=0.01,
                reasons=reasons,
                evidence_trace=base_trace,
                auto_publish_allowed=True,
            )

        # 4. Explicit visual verifier rejection
        if visual_verified is False or semantic_decision == "NO_MATCH":
            reasons.append("rejected_by_semantic_or_visual_verifier")
            return IdentityDecision(
                decision="NO_MATCH",
                score=0.0,
                uncertainty=0.05,
                reasons=reasons,
                evidence_trace=base_trace,
                auto_publish_allowed=False,
            )

        # 5. Hard structured conflict (companion mismatch, swimwear/wetsuit conflict, conflicting top/board color)
        if struct_score == 0.0 and (not attrs_left.get("empty") and not attrs_right.get("empty")):
            # Check whether it's a hard conflict vs merely insufficient overlap
            if attrs_left.get("companion") != attrs_right.get("companion"):
                reasons.append("companion_solo_vs_tandem_conflict")
                return IdentityDecision(
                    decision="NO_MATCH",
                    score=0.0,
                    uncertainty=0.0,
                    reasons=reasons,
                    evidence_trace=base_trace,
                    auto_publish_allowed=False,
                )
            if attrs_left.get("gender_age") and attrs_right.get("gender_age") and attrs_left["gender_age"] != attrs_right["gender_age"]:
                reasons.append("incompatible_swimwear_or_category")
                return IdentityDecision(
                    decision="NO_MATCH",
                    score=0.0,
                    uncertainty=0.0,
                    reasons=reasons,
                    evidence_trace=base_trace,
                    auto_publish_allowed=False,
                )
            if not _sleeve_styles_compatible(attrs_left.get("sleeve_style"), attrs_right.get("sleeve_style")):
                reasons.append("wetsuit_vs_bare_or_swimsuit_conflict")
                return IdentityDecision(
                    decision="NO_MATCH",
                    score=0.0,
                    uncertainty=0.0,
                    reasons=reasons,
                    evidence_trace=base_trace,
                    auto_publish_allowed=False,
                )
            if (
                attrs_left.get("equip_color")
                and attrs_right.get("equip_color")
                and attrs_left["equip_color"] != attrs_right["equip_color"]
                and {attrs_left["equip_color"], attrs_right["equip_color"]} != {"red", "pink"}
            ):
                reasons.append("conflicting_equipment_color")
                return IdentityDecision(
                    decision="NO_MATCH",
                    score=0.0,
                    uncertainty=0.05,
                    reasons=reasons,
                    evidence_trace=base_trace,
                    auto_publish_allowed=False,
                )

        # 6. Equipment-only guard (OPT-01 / OPT-03): never match solely because both have a surfboard
        has_apparel_match = bool(
            (
                attrs_left.get("sleeve_style")
                and attrs_right.get("sleeve_style")
                and _sleeve_styles_compatible(attrs_left.get("sleeve_style"), attrs_right.get("sleeve_style"))
            )
            or (
                attrs_left.get("top_color")
                and attrs_right.get("top_color")
                and _top_colors_compatible(attrs_left.get("top_color"), attrs_right.get("top_color"))
            )
            or (
                attrs_left.get("bottom_color")
                and attrs_right.get("bottom_color")
                and attrs_left.get("bottom_color") == attrs_right.get("bottom_color")
            )
        )

        # Combine structured score, semantic model signal, and visual embedding similarity
        combined = struct_score
        if embedding_similarity is not None:
            if embedding_similarity < 0.25:
                reasons.append("low_visual_embedding_similarity")
                combined = min(combined, 0.40)
            elif embedding_similarity >= 0.85 and struct_score >= 0.80:
                reasons.append("strong_visual_embedding_and_attribute_agreement")
                combined = max(combined, min(0.98, 0.65 * struct_score + 0.35 * embedding_similarity))

        if semantic_decision == "MATCH":
            conf_norm = str(semantic_confidence or "medium").lower()
            if conf_norm == "high" and (struct_score >= 0.85 or has_apparel_match):
                reasons.append("semantic_high_confidence_with_compatible_attributes")
                combined = max(combined, 0.92)
            elif conf_norm == "medium" and struct_score >= 0.85:
                reasons.append("semantic_medium_confidence_with_structured_match")
                combined = max(combined, 0.88)
            elif conf_norm == "low":
                reasons.append("semantic_low_confidence_requires_verification")
                combined = min(combined, 0.65)

        if visual_verified is True and combined >= 0.70:
            reasons.append("confirmed_by_visual_verifier")
            combined = max(combined, 0.91)

        if not has_apparel_match and combined < 0.90:
            reasons.append("insufficient_apparel_or_feature_agreement")
            combined = min(combined, 0.60)

        uncertainty = round(max(0.0, 1.0 - abs(2.0 * combined - 1.0)), 4)

        if combined >= self.match_threshold:
            if not reasons:
                reasons.append("structured_attribute_and_visual_match")
            return IdentityDecision(
                decision="MATCH",
                score=combined,
                uncertainty=uncertainty,
                reasons=reasons,
                evidence_trace=base_trace,
                auto_publish_allowed=True,
            )
        if combined >= self.uncertain_floor:
            if not reasons:
                reasons.append("partial_attribute_overlap_uncertain")
            return IdentityDecision(
                decision="UNCERTAIN",
                score=combined,
                uncertainty=max(0.35, uncertainty),
                reasons=reasons,
                evidence_trace=base_trace,
                auto_publish_allowed=False,
            )
        if not reasons:
            reasons.append("insufficient_identity_similarity")
        return IdentityDecision(
            decision="NO_MATCH",
            score=combined,
            uncertainty=uncertainty,
            reasons=reasons,
            evidence_trace=base_trace,
            auto_publish_allowed=False,
        )

    def evaluate_clusters(
        self,
        cluster_a: Mapping[str, Any],
        cluster_b: Mapping[str, Any],
        *,
        embedding_similarity: float | None = None,
    ) -> IdentityDecision:
        """Evaluate whether two multi-appearance clusters can be safely merged."""
        apps_a = list(cluster_a.get("appearances") or [])
        apps_b = list(cluster_b.get("appearances") or [])
        sources_a = {_source_name(a) or str(a.get("_clip_index")) for a in apps_a}
        sources_b = {_source_name(b) or str(b.get("_clip_index")) for b in apps_b}
        if sources_a & sources_b:
            return IdentityDecision(
                decision="NO_MATCH",
                score=0.0,
                uncertainty=0.0,
                reasons=["cluster_source_clip_overlap"],
                evidence_trace={
                    "overlapping_sources": sorted(sources_a & sources_b),
                    "cross_source_numeric_track_id_ignored": True,
                },
                auto_publish_allowed=False,
            )
        rep_a = {
            "description": cluster_a.get("description", ""),
            "path": apps_a[0].get("path", "") if apps_a else "",
            "_person_id": apps_a[0].get("_person_id", "") if apps_a else "",
            "events": [ev for a in apps_a for ev in (a.get("events") or [])],
        }
        rep_b = {
            "description": cluster_b.get("description", ""),
            "path": apps_b[0].get("path", "") if apps_b else "",
            "_person_id": apps_b[0].get("_person_id", "") if apps_b else "",
            "events": [ev for b in apps_b for ev in (b.get("events") or [])],
        }
        return self.evaluate_pair(
            rep_a,
            rep_b,
            embedding_similarity=embedding_similarity,
            visual_verified=bool(cluster_a.get("_visual_verified") and cluster_b.get("_visual_verified")) or None,
        )


__all__ = [
    "IdentityDecision",
    "IdentityDecisionEngine",
]
