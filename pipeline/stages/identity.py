"""
pipeline/stages/identity.py — Cross-clip identity clustering.
Three-tier Re-ID: CLIP embeddings → Gemini visual → Gemini text → per-clip fallback.
"""

import json
import logging
import os
import re
import time

from langsmith import traceable

import config
from integrations.gemini import genai

logger = logging.getLogger(__name__)

_CLIP_CACHE: dict = {}


def _get_clip_model():
    """Load CLIP model once per process and cache at module level."""
    if not _CLIP_CACHE:
        from transformers import CLIPModel, CLIPProcessor
        processor  = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        model      = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        model.eval()
        _CLIP_CACHE["processor"] = processor
        _CLIP_CACHE["model"]     = model
    return _CLIP_CACHE["processor"], _CLIP_CACHE["model"]


# ── Tier 3: text-only clustering prompt ───────────────────────────────────────

_CLUSTER_PROMPT_TEMPLATE = """\
Here are visual descriptions of people detected across {n} video clip(s).
Group descriptions that likely refer to the same person.

IMPORTANT — DRONE/AERIAL FOOTAGE: These clips were shot from above.
Faces are typically NOT visible (top-down angle). Focus on:
  ✓ Jersey/bib numbers on the back or top — highly visible from above
  ✓ Clothing colors seen from above (shoulders, torso)
  ✓ Equipment color (board, bike, helmet top)
  ✗ Do NOT rely on face description — it is unreliable in aerial shots

Input:
{descriptions_json}

Matching priority (strongest to weakest):
  1. Jersey/bib number — matching numbers = definitely the same person
  2. Clothing color combination (shirt + shorts/pants + accessories)
  3. Equipment (board color/brand, helmet color, bike color)
  4. Hair (color and length — visible from above if not covered)
  5. Build (only when nothing else distinguishes)

When uncertain, create SEPARATE clusters (avoid false merges).
A person appearing in only one clip still gets their own cluster.

For each cluster, set "confidence":
  "high"   — certain match (jersey number, or identical clothing AND equipment)
  "medium" — likely same person but one feature unclear or differs slightly
  "low"    — only one weak feature matches (e.g. generic "black wetsuit" only)
If confidence is "low" AND the cluster spans more than one clip, SPLIT it into
individual single-appearance clusters instead of merging.

FINAL CHECK before answering: review your clusters as a set. If TWO clusters
describe the same clothing+equipment combination, they are almost certainly the
SAME person — merge them. Each real person must appear EXACTLY once in the output.

Return ONLY valid JSON, no markdown:
{{
  "clusters": [
    {{
      "description": "surfer with red board and black wetsuit",
      "confidence": "high",
      "appearances": [
        {{"clip_index": 0, "person_id": "person_A"}},
        {{"clip_index": 2, "person_id": "person_A"}},
        {{"clip_index": 4, "person_id": "person_A"}}
      ]
    }},
    {{
      "description": "surfer with blue board and white rash guard",
      "confidence": "medium",
      "appearances": [
        {{"clip_index": 1, "person_id": "person_B"}}
      ]
    }}
  ]
}}
"""

# ── Tier 2: visual clustering prompt (used with thumbnail images) ─────────────

_VISUAL_CLUSTER_PROMPT = """\
You are matching athletes across multiple sports video clips.
Thumbnail images from each clip are shown above, labeled [Clip N, person_X].
Group the images that show the SAME person.

IMPORTANT — DRONE/AERIAL FOOTAGE: These thumbnails were captured from a drone looking down.
Faces are typically NOT visible or reliable for matching.
What IS visible and reliable from above:
  ✓ Jersey/bib number on the back or top of the athlete
  ✓ Clothing colors on shoulders, torso (what's seen from directly above)
  ✓ Equipment: surfboard color/shape, bike color, helmet top
  ✗ Avoid matching on faces — they may not be visible at all

Text descriptions for reference:
{descriptions_json}

Matching priority (strongest to weakest):
  1. Jersey/bib number visible from above
  2. Clothing color combination (top-down view of torso/shoulders)
  3. Equipment (board, helmet top, bike frame color)
  4. Hair color and style (if visible from above, not covered by helmet)
  5. Body build

When uncertain, create SEPARATE clusters. A person in only one clip gets their own cluster.

For each cluster, set "confidence":
  "high"   — visually certain (jersey number, or identical clothing AND equipment)
  "medium" — likely same but image quality or angle makes it uncertain
  "low"    — only one weak visual cue matches
If confidence is "low" AND the cluster spans more than one clip, SPLIT it into
individual single-appearance clusters instead of merging.

FINAL CHECK before answering: review your clusters as a set. If TWO clusters
describe the same clothing+equipment combination, they are almost certainly the
SAME person — merge them. Each real person must appear EXACTLY once in the output.

Return ONLY valid JSON, no markdown:
{{
  "clusters": [
    {{
      "description": "brief description of this person",
      "confidence": "high",
      "appearances": [
        {{"clip_index": 0, "person_id": "person_A"}},
        {{"clip_index": 1, "person_id": "person_B"}}
      ]
    }}
  ]
}}
"""


# ── Shared helper ─────────────────────────────────────────────────────────────

def _build_clusters_from_data(data: dict, clip_analyses: list[dict]) -> list[dict]:
    """
    Convert Gemini cluster JSON into the standard result format.

    Low-confidence clusters that span multiple clips are split into individual
    single-appearance clusters to prevent incorrect person merges.
    """
    result: list[dict] = []
    for cluster in data.get("clusters", []):
        confidence = str(cluster.get("confidence", "medium")).lower()

        # Resolve appearances → (path, events, per-person description) tuples
        resolved: list[dict] = []
        for app in cluster.get("appearances", []):
            idx = app.get("clip_index", -1)
            pid = app.get("person_id", "")
            if not (0 <= idx < len(clip_analyses)):
                continue
            ca      = clip_analyses[idx]
            persons = ca.get("analysis", {}).get("persons", [])
            person  = next((p for p in persons if p["id"] == pid), None)
            if person and person.get("events"):
                resolved.append({
                    "path":        ca["path"],
                    "events":      person["events"],
                    "description": person.get("description", "unknown athlete"),
                    "thumbnail":   person.get("thumbnail", ""),
                })

        if not resolved:
            continue

        # Warn when multi-clip cluster has uncertain confidence — operator should verify reel
        if confidence in ("medium", "low") and len(resolved) > 1:
            logger.warning(
                "⚠️ Cluster '%s' spans %d clips with confidence=%s — check reel for mixed athletes",
                cluster.get("description", "?"), len(resolved), confidence,
            )
            print(f"  ⚠️ Identity confidence={confidence} for '{cluster.get('description','?')[:40]}' "
                  f"across {len(resolved)} clip(s) — verify reel has no mixed athletes")

        # Low-confidence clusters spanning multiple clips are split to avoid false merges
        if confidence == "low" and len(resolved) > 1:
            for app in resolved:
                result.append({
                    "description": app["description"],
                    "appearances": [{"path": app["path"], "events": app["events"],
                                     "thumbnail": app.get("thumbnail", "")}],
                })
        else:
            result.append({
                "description": cluster.get("description", "unknown athlete"),
                "appearances": [{"path": a["path"], "events": a["events"],
                                 "thumbnail": a.get("thumbnail", "")} for a in resolved],
            })
    return result


def _retry_gemini(fn, attempts: int = 3, base_delay: int = 4) -> str:
    """Call fn() with exponential back-off on transient Gemini errors."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            transient = any(x in str(e).lower()
                            for x in ["429", "quota", "503", "unavailable", "resource exhausted"])
            if not transient or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Gemini cluster retry %d/%d in %ds: %s", attempt, attempts, delay, e)
            time.sleep(delay)
    raise RuntimeError("unreachable")


@traceable(run_type="llm", name="gemini-cluster-visual")
def _gemini_call_cluster_visual(content: list, model_name: str, n_clips: int) -> str:
    """Traced Gemini visual-clustering call — inputs/output logged to LangSmith."""
    model = genai.GenerativeModel(model_name=model_name)
    return _retry_gemini(lambda: model.generate_content(
        content, request_options={"timeout": 120}
    ).text.strip())


@traceable(run_type="llm", name="gemini-cluster-text")
def _gemini_call_cluster_text(prompt: str, model_name: str, n_clips: int) -> str:
    """Traced Gemini text-clustering call — inputs/output logged to LangSmith."""
    model = genai.GenerativeModel(model_name=model_name)
    return _retry_gemini(lambda: model.generate_content(
        prompt, request_options={"timeout": 120}
    ).text.strip())


# ── Tier 1: CLIP Re-ID (optional — requires torch + transformers + Pillow) ────

def _try_clip_cluster(clip_analyses: list[dict]) -> list[dict] | None:
    """
    Tier 1: cosine-similarity clustering using CLIP visual embeddings.
    Returns None if torch/transformers/Pillow are not installed, or if thumbnails
    are missing, or if the model fails to load.
    """
    try:
        import torch
        from PIL import Image as PILImage
    except ImportError:
        logger.debug("CLIP Re-ID unavailable (install torch + transformers + Pillow to enable)")
        return None

    # Collect persons that have extracted thumbnails
    entries = [
        {"clip_index": i, "person_id": p["id"], "thumbnail": p.get("thumbnail", "")}
        for i, ca in enumerate(clip_analyses)
        for p in ca.get("analysis", {}).get("persons", [])
        if p.get("thumbnail") and os.path.exists(p.get("thumbnail", ""))
    ]
    if len(entries) < 2:
        return None  # nothing useful to cluster

    try:
        processor, clip_model = _get_clip_model()
    except Exception as e:
        logger.warning("CLIP model load failed: %s", e)
        return None

    valid_entries: list[dict] = []
    embeddings: list = []
    for entry in entries:
        try:
            img    = PILImage.open(entry["thumbnail"]).convert("RGB")
            inputs = processor(images=img, return_tensors="pt")
            with torch.no_grad():
                emb = clip_model.get_image_features(**inputs)
                emb = emb / emb.norm(dim=-1, keepdim=True)
            embeddings.append(emb.squeeze(0))
            valid_entries.append(entry)
        except Exception as img_err:
            logger.debug("CLIP embed failed for %s: %s", entry["thumbnail"], img_err)

    if len(valid_entries) < 2:
        return None

    # Cosine similarity matrix → union-find clustering at threshold 0.78
    emb_matrix = torch.stack(embeddings)
    sim_matrix  = (emb_matrix @ emb_matrix.T).tolist()
    _THRESHOLD  = 0.78

    n      = len(valid_entries)
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i][j] >= _THRESHOLD:
                # persons in the same clip are by definition different people — never merge
                if valid_entries[i]["clip_index"] == valid_entries[j]["clip_index"]:
                    continue
                pi, pj = _find(i), _find(j)
                if pi != pj:
                    parent[pi] = pj

    from collections import defaultdict
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[_find(i)].append(i)

    result: list[dict] = []
    for group_idxs in groups.values():
        appearances: list[dict] = []
        for idx in group_idxs:
            entry  = valid_entries[idx]
            ca     = clip_analyses[entry["clip_index"]]
            person = next((p for p in ca.get("analysis", {}).get("persons", [])
                           if p["id"] == entry["person_id"]), None)
            if person and person.get("events"):
                appearances.append({"path": ca["path"], "events": person["events"],
                                    "thumbnail": person.get("thumbnail", "")})
        if appearances:
            first    = valid_entries[group_idxs[0]]
            first_ca = clip_analyses[first["clip_index"]]
            first_p  = next((p for p in first_ca.get("analysis", {}).get("persons", [])
                             if p["id"] == first["person_id"]), None)
            desc = first_p["description"] if first_p else "unknown athlete"
            result.append({"description": desc, "appearances": appearances})

    return result or None


# ── Tier 2: Gemini visual clustering (thumbnails uploaded to Files API) ───────

def _try_visual_cluster(descriptions: list[dict], clip_analyses: list[dict]) -> list[dict] | None:
    """
    Tier 2: Gemini clustering with thumbnail images alongside text descriptions.
    Uploads JPEG thumbnails to the Gemini Files API, then asks Gemini to visually
    group persons. Returns None if no thumbnails are available.
    """
    # Find persons with extracted thumbnails
    thumb_map: dict[tuple[int, str], str] = {}
    for i, ca in enumerate(clip_analyses):
        for p in ca.get("analysis", {}).get("persons", []):
            thumb = p.get("thumbnail", "")
            if thumb and os.path.exists(thumb):
                thumb_map[(i, p["id"])] = thumb

    if not thumb_map:
        return None

    uploaded: list[dict] = []
    try:
        for (ci, pid), thumb_path in thumb_map.items():
            try:
                gfile = genai.upload_file(path=thumb_path, mime_type="image/jpeg")
                uploaded.append({"clip_index": ci, "person_id": pid, "file": gfile})
            except Exception as e:
                logger.debug("Thumbnail upload failed for clip %d %s: %s", ci, pid, e)

        if not uploaded:
            return None

        # Build multimodal content: [label, image, label, image, ..., prompt]
        content: list = []
        for uf in uploaded:
            content.append(f"[Clip {uf['clip_index']}, {uf['person_id']}]:")
            content.append(uf["file"])

        content.append(_VISUAL_CLUSTER_PROMPT.format(
            descriptions_json=json.dumps(descriptions, indent=2)
        ))

        model = genai.GenerativeModel(model_name=config.GEMINI_MODEL)
        raw   = _gemini_call_cluster_visual(
            content=content,
            model_name=config.GEMINI_MODEL,
            n_clips=len(clip_analyses),
        )

        raw  = re.sub(r"^```(?:json)?\s*", "", raw)
        raw  = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return _build_clusters_from_data(data, clip_analyses)

    finally:
        for uf in uploaded:
            try:
                genai.delete_file(uf["file"].name)
            except Exception:
                pass


# ── Tier 3: Gemini text-only clustering ──────────────────────────────────────

def _text_cluster(descriptions: list[dict], clip_analyses: list[dict]) -> list[dict]:
    """Tier 3: Gemini text-only clustering. May raise on persistent Gemini errors."""
    prompt = _CLUSTER_PROMPT_TEMPLATE.format(
        n=len(clip_analyses),
        descriptions_json=json.dumps(descriptions, indent=2),
    )
    raw   = _gemini_call_cluster_text(
        prompt=prompt,
        model_name=config.GEMINI_MODEL,
        n_clips=len(clip_analyses),
    )

    raw  = re.sub(r"^```(?:json)?\s*", "", raw)
    raw  = re.sub(r"\s*```$", "", raw)
    data = json.loads(raw)
    return _build_clusters_from_data(data, clip_analyses)


# ── Post-clustering safeguards ────────────────────────────────────────────────

def _merge_duplicate_clusters(clusters: list[dict]) -> list[dict]:
    """Merge clusters whose descriptions are effectively identical.

    Fixes the operator-reported bug where the SAME athlete gets two reels titled
    as different people (clustering split them across tiers/chunks). Never merges
    two clusters that share a source clip — two people in one clip are by
    definition different. False merges are caught by _verify_multi_clusters.
    """
    def _norm(d: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", d.lower()).strip()

    merged: dict[str, dict] = {}
    order: list[str] = []
    for c in clusters:
        key = _norm(c.get("description", ""))
        if key and key in merged:
            existing_paths = {a["path"] for a in merged[key]["appearances"]}
            if any(a["path"] in existing_paths for a in c["appearances"]):
                # same clip appears in both → different people with similar looks
                key = key + f"#{len(order)}"
                merged[key] = c
                order.append(key)
                continue
            logger.info("Merging duplicate-description clusters: '%s'", c.get("description", "?")[:40])
            print(f"  🔗 Merged duplicate identity '{c.get('description','?')[:40]}' "
                  f"(+{len(c['appearances'])} clip(s))")
            merged[key]["appearances"].extend(c["appearances"])
        else:
            merged[key or f"#{len(order)}"] = c
            order.append(key or f"#{len(order)}")
    return [merged[k] for k in order]


_VERIFY_PROMPT = """\
The thumbnail images above were grouped as showing the SAME athlete across
different drone video clips. Verify this grouping.

DRONE/AERIAL footage: do not rely on faces. Compare clothing colors (top-down
view of torso/shoulders), equipment (board/bike/helmet color and shape), and
jersey/bib numbers when visible.

Return ONLY valid JSON, no markdown:
{"mismatched_indices": [<image numbers that show a DIFFERENT person than the majority>]}

Return an empty list when all images plausibly show the same person.
Only flag an index when you are CONFIDENT it is a different person (clearly
different clothing AND equipment) — borderline cases stay in the group.
"""


def _verify_multi_clusters(clusters: list[dict]) -> list[dict]:
    """Visual verification pass for multi-clip clusters (anti mixed-athlete reels).

    For each cluster spanning 2+ clips with thumbnails, asks Gemini flash to
    confirm every appearance shows the same person; confidently-mismatched
    appearances are split into their own clusters. Fail-open: any error keeps
    the cluster unchanged.
    """
    verified: list[dict] = []
    for cluster in clusters:
        apps   = cluster.get("appearances", [])
        thumbs = [a.get("thumbnail", "") for a in apps]
        if len(apps) < 2 or not all(t and os.path.exists(t) for t in thumbs):
            verified.append(cluster)
            continue

        uploaded: list = []
        try:
            content: list = []
            for i, t in enumerate(thumbs):
                gfile = genai.upload_file(path=t, mime_type="image/jpeg")
                uploaded.append(gfile)
                content.append(f"[Image {i}]:")
                content.append(gfile)
            content.append(_VERIFY_PROMPT)

            model = genai.GenerativeModel(model_name="gemini-2.5-flash")
            raw   = _retry_gemini(lambda: model.generate_content(
                content, request_options={"timeout": 60}
            ).text.strip())
            raw  = re.sub(r"^```(?:json)?\s*", "", raw)
            raw  = re.sub(r"\s*```$", "", raw)
            bad  = {int(i) for i in json.loads(raw).get("mismatched_indices", [])
                    if isinstance(i, (int, float)) and 0 <= int(i) < len(apps)}

            if not bad or len(bad) >= len(apps):  # all flagged = unreliable answer
                verified.append(cluster)
                continue

            keep  = [a for i, a in enumerate(apps) if i not in bad]
            split = [a for i, a in enumerate(apps) if i in bad]
            print(f"  ✂️  Identity verification split {len(split)} clip(s) out of "
                  f"'{cluster.get('description','?')[:40]}' — different athlete detected")
            logger.warning("Identity verify: split %d/%d appearance(s) from '%s'",
                           len(split), len(apps), cluster.get("description", "?"))
            verified.append({**cluster, "appearances": keep})
            for a in split:
                verified.append({
                    "description": cluster.get("description", "unknown athlete") + " (separated)",
                    "appearances": [a],
                })
        except Exception as e:
            logger.debug("Cluster verification skipped (%s) — keeping as-is", e)
            verified.append(cluster)
        finally:
            for gfile in uploaded:
                try:
                    genai.delete_file(gfile.name)
                except Exception:
                    pass
    return verified


def _post_process_clusters(clusters: list[dict]) -> list[dict]:
    """Shared safety pass: merge duplicate identities, then visually verify
    multi-clip clusters so one reel never mixes two athletes."""
    if not clusters:
        return clusters
    clusters = _merge_duplicate_clusters(clusters)
    clusters = _verify_multi_clusters(clusters)
    return clusters


# ── Thumbnail cleanup ─────────────────────────────────────────────────────────

def _cleanup_thumbnails(clip_analyses: list[dict]) -> None:
    """Remove per-person thumbnail files created during analyze_session."""
    for ca in clip_analyses:
        for person in ca.get("analysis", {}).get("persons", []):
            thumb = person.get("thumbnail", "")
            if thumb:
                try:
                    os.remove(thumb)
                except OSError:
                    pass


# ── Public API ────────────────────────────────────────────────────────────────

@traceable(name="cluster-clips")
def cluster_clips(clip_analyses: list[dict]) -> list[dict]:
    """
    Groups persons from multiple short clips by identity.

    Tries four tiers in order:
      1. CLIP Re-ID — cosine similarity on visual embeddings (requires torch + transformers + Pillow)
      2. Gemini visual — Gemini with thumbnail images (requires extracted thumbnails)
      3. Gemini text — Gemini with text descriptions only (always available if API is reachable)
      4. Per-clip fallback — each person becomes their own cluster (offline / API error)

    Args:
        clip_analyses: list of {"path": str, "analysis": {"activity": str, "persons": [...]}}

    Returns:
        list of {"description": str, "appearances": [{"path": str, "events": [...]}]}
    """
    if not clip_analyses:
        return []

    try:
        # Single clip — return directly without any clustering call
        if len(clip_analyses) == 1:
            persons = clip_analyses[0].get("analysis", {}).get("persons", [])
            return [
                {
                    "description": p["description"],
                    "appearances": [{"path": clip_analyses[0]["path"], "events": p["events"]}],
                }
                for p in persons
                if p.get("events")
            ]

        # Build flat description list for text/visual prompts
        descriptions = [
            {
                "clip_index":  i,
                "person_id":   p["id"],
                "description": p["description"],
            }
            for i, ca in enumerate(clip_analyses)
            for p in ca.get("analysis", {}).get("persons", [])
        ]

        if not descriptions:
            return []

        # ── Tier 1: CLIP Re-ID ────────────────────────────────────────────────
        try:
            result = _try_clip_cluster(clip_analyses)
            if result is not None:
                logger.info("Identity clustering: CLIP Re-ID succeeded (%d clusters)", len(result))
                return _post_process_clusters(result)
        except Exception as e:
            logger.warning("CLIP clustering error: %s", e)

        # ── Tier 2: Gemini visual (thumbnails) ────────────────────────────────
        try:
            result = _try_visual_cluster(descriptions, clip_analyses)
            if result:
                logger.info("Identity clustering: Gemini visual succeeded (%d clusters)", len(result))
                return _post_process_clusters(result)
        except Exception as e:
            logger.warning("Gemini visual clustering error: %s", e)

        # ── Tier 3: Gemini text ───────────────────────────────────────────────
        try:
            result = _text_cluster(descriptions, clip_analyses)
            if result:
                logger.info("Identity clustering: Gemini text succeeded (%d clusters)", len(result))
                return _post_process_clusters(result)
        except Exception as e:
            logger.error("Identity clustering failed at all Gemini tiers, falling back: %s", e)

        # ── Tier 4: per-clip fallback ─────────────────────────────────────────
        result = []
        for ca in clip_analyses:
            for p in ca.get("analysis", {}).get("persons", []):
                if p.get("events"):
                    result.append({
                        "description": p["description"],
                        "appearances": [{"path": ca["path"], "events": p["events"]}],
                    })
        return result

    finally:
        _cleanup_thumbnails(clip_analyses)
