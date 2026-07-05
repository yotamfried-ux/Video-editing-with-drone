"""Run-level athlete canonicalization.

Implements the first REAL-ATHLETE-001 guardrail:
- assign a stable athlete_id to every detected person/cluster;
- merge clusters only when strong deterministic identity evidence matches;
- preserve weak/uncertain cases as separate athletes but make the evidence status
  explicit in draft metadata and candidate ledgers.

This does not guess that two visually similar surfers are the same person. It only
canonicalizes across clusters when existing track/athlete evidence says so.
"""
from __future__ import annotations

import hashlib
import re
import sys
from typing import Any

_ANALYZER_FLAG = "_sportreel_athlete_canonicalization_analyzer_installed"
_IDENTITY_FLAG = "_sportreel_athlete_canonicalization_identity_installed"


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def _source_name(path: Any) -> str:
    return str(path or "unknown")


def _strong_event_tokens(event: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return merge tokens and evidence-only tokens for an event.

    `track_id` is cross-source deterministic evidence and can merge clusters by
    itself. Existing non-generated `athlete_id` can also merge clusters. Generated
    single-source IDs and per-source person IDs are evidence, but must not make the
    equivalence key stricter because that prevents shared `track_id` matches from
    merging across files.
    """
    merge_tokens: list[str] = []
    evidence_tokens: list[str] = []

    track_id = str(event.get("track_id") or "").strip()
    if track_id:
        token = f"track_id:{track_id}"
        merge_tokens.append(token)
        evidence_tokens.append(token)

    athlete_id = str(event.get("athlete_id") or "").strip()
    evidence_status = str(event.get("athlete_canonical_evidence_status") or "").strip()
    generated = athlete_id.startswith("ath_") or evidence_status in {"single_source", "weak"}
    if athlete_id:
        token = f"athlete_id:{athlete_id}"
        evidence_tokens.append(token)
        if not generated:
            merge_tokens.append(token)

    person_id = str(event.get("person_id") or "").strip()
    if person_id:
        evidence_tokens.append(f"person_id:{person_id}")

    return merge_tokens, evidence_tokens


def _cluster_strong_tokens(cluster: dict[str, Any]) -> list[str]:
    tokens: set[str] = set()
    for app in cluster.get("appearances", []) or []:
        for event in app.get("events", []) or []:
            if isinstance(event, dict):
                merge_tokens, _ = _strong_event_tokens(event)
                tokens.update(merge_tokens)
    return sorted(tokens)


def _fallback_cluster_key(cluster: dict[str, Any], index: int) -> str:
    parts = [_norm(cluster.get("description", "unknown athlete")) or "unknown"]
    for app in cluster.get("appearances", []) or []:
        source = _source_name(app.get("path"))
        spans = []
        evidence_tokens: list[str] = []
        for event in app.get("events", []) or []:
            if not isinstance(event, dict):
                continue
            spans.append(f"{event.get('type','')}:{event.get('start')}:{event.get('end')}")
            _, event_evidence = _strong_event_tokens(event)
            evidence_tokens.extend(event_evidence)
        parts.append(source + "|" + ",".join(spans[:5]) + "|" + ",".join(sorted(evidence_tokens)[:5]))
    return f"weak:{index}:{'|'.join(parts)}"


def _athlete_id_from_key(key: str) -> str:
    return "ath_" + _short_hash(key)


def _annotate_event(event: dict[str, Any], athlete_id: str, key: str, status: str, duplicate_group: str | None = None) -> None:
    event["athlete_id"] = athlete_id
    event["athlete_canonical_key"] = key
    event["athlete_canonical_evidence_status"] = status
    if duplicate_group:
        event["athlete_duplicate_group"] = duplicate_group
        event.setdefault("dedup_dropped_duplicates", []).append({
            "type": "DUPLICATE_ATHLETE",
            "defect_type": "DUPLICATE_ATHLETE",
            "severity": "critical",
            "blocking": True,
            "note": "same canonical athlete evidence appeared in multiple clusters",
            "athlete_id": athlete_id,
            "athlete_duplicate_group": duplicate_group,
        })


def _annotate_cluster(cluster: dict[str, Any], athlete_id: str, key: str, status: str, duplicate_group: str | None = None) -> dict[str, Any]:
    out = dict(cluster)
    out["athlete_id"] = athlete_id
    out["athlete_canonical_key"] = key
    out["athlete_canonical_evidence_status"] = status
    if duplicate_group:
        out["athlete_duplicate_group"] = duplicate_group
    for app in out.get("appearances", []) or []:
        for event in app.get("events", []) or []:
            if isinstance(event, dict):
                _annotate_event(event, athlete_id, key, status, duplicate_group)
    return out


def _merge_key(tokens: list[str]) -> str:
    track_tokens = sorted(token for token in tokens if token.startswith("track_id:"))
    if track_tokens:
        return "strong:" + "|".join(track_tokens)
    return "strong:" + "|".join(sorted(tokens))


def canonicalize_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign athlete_id and merge clusters when strong evidence is identical.

    Strong evidence currently means cross-source `track_id` or existing non-generated
    `athlete_id` on events. Weak fallback IDs are stable for metadata but are never
    used to merge clusters.
    """
    registry: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    weak_out: list[dict[str, Any]] = []

    for index, cluster in enumerate(clusters or []):
        tokens = _cluster_strong_tokens(cluster)
        if tokens:
            key = _merge_key(tokens)
            athlete_id = _athlete_id_from_key(key)
            duplicate_group = "dup_" + _short_hash(key)
            annotated = _annotate_cluster(cluster, athlete_id, key, "strong")
            if key in registry:
                existing = registry[key]
                existing.setdefault("appearances", []).extend(annotated.get("appearances", []) or [])
                existing["athlete_collection_policy"] = "merged_same_athlete"
                existing["athlete_duplicate_group"] = duplicate_group
                for app in existing.get("appearances", []) or []:
                    for event in app.get("events", []) or []:
                        if isinstance(event, dict):
                            _annotate_event(event, athlete_id, key, "strong", duplicate_group)
            else:
                registry[key] = annotated
                order.append(key)
            continue

        key = _fallback_cluster_key(cluster, index)
        athlete_id = _athlete_id_from_key(key)
        weak_out.append(_annotate_cluster(cluster, athlete_id, key, "weak"))

    strong_out = [registry[key] for key in order]
    return strong_out + weak_out


def annotate_session_persons(session: dict[str, Any], source_path: str = "") -> dict[str, Any]:
    persons = session.get("persons") if isinstance(session, dict) else None
    if not isinstance(persons, list):
        return session
    for index, person in enumerate(persons):
        if not isinstance(person, dict):
            continue
        pid = str(person.get("id") or f"person_{index:03d}")
        key = f"single_source:{_source_name(source_path)}:{pid}:{_norm(person.get('description',''))}"
        athlete_id = person.get("athlete_id") or _athlete_id_from_key(key)
        person["athlete_id"] = athlete_id
        person["athlete_canonical_key"] = key
        person["athlete_canonical_evidence_status"] = "single_source"
        for event in person.get("events", []) or []:
            if isinstance(event, dict):
                event.setdefault("person_id", pid)
                _annotate_event(event, athlete_id, key, "single_source")
    return session


def _patch_analyzer(analyzer: Any) -> None:
    if getattr(analyzer, _ANALYZER_FLAG, False):
        return
    original = analyzer.analyze_session

    def analyze_with_athlete_ids(path, *args, **kwargs):
        session = original(path, *args, **kwargs)
        if isinstance(session, dict):
            return annotate_session_persons(session, str(path))
        return session

    analyzer.analyze_session = analyze_with_athlete_ids
    setattr(analyzer, _ANALYZER_FLAG, True)


def _patch_identity(identity: Any) -> None:
    if getattr(identity, _IDENTITY_FLAG, False):
        return
    original = identity.cluster_clips

    def cluster_with_athlete_ids(clip_analyses, *args, **kwargs):
        clusters = original(clip_analyses, *args, **kwargs)
        return canonicalize_clusters(clusters)

    identity.cluster_clips = cluster_with_athlete_ids
    setattr(identity, _IDENTITY_FLAG, True)


def install() -> None:
    analyzer = sys.modules.get("pipeline.stages.analyzer")
    if analyzer is None:
        import pipeline.stages.analyzer as analyzer  # type: ignore[no-redef]
    _patch_analyzer(analyzer)

    identity = sys.modules.get("pipeline.stages.identity")
    if identity is None:
        import pipeline.stages.identity as identity  # type: ignore[no-redef]
    _patch_identity(identity)
