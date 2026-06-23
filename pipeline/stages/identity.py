"""
pipeline/stages/identity.py — Cross-clip identity clustering.

The pipeline first asks Gemini to match athletes using the actual per-person
thumbnails, then falls back to text descriptions, then uses a conservative local
CLIP fallback only when Gemini is unavailable. The post-processing layer is
deliberately conservative: it prevents mixed-athlete reels by splitting uncertain
or impossible clusters instead of guessing.
"""

import json
import logging
import os
import re
import time
from collections import defaultdict

from langsmith import traceable

import config
from integrations.gemini import genai

logger = logging.getLogger(__name__)

_CLIP_CACHE: dict = {}
_CLIP_THRESHOLD = 0.86
_CLIP_MARGIN = 0.035


def _get_clip_model():
    """Load CLIP model once per process and cache at module level."""
    if not _CLIP_CACHE:
        from transformers import CLIPModel, CLIPProcessor
        processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        model.eval()
        _CLIP_CACHE["processor"] = processor
        _CLIP_CACHE["model"] = model
    return _CLIP_CACHE["processor"], _CLIP_CACHE["model"]


# ── Tier 2: text-only clustering prompt ───────────────────────────────────────

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

Hard output constraints:
  - Every input pair (clip_index, person_id) must appear in EXACTLY ONE cluster.
  - A cluster may NEVER contain two appearances from the same clip_index.
    Two visible people in the same source clip are different people, even if they
    look similar from above.
  - When uncertain, create separate clusters. A missed merge is better than a
    mixed-athlete reel.
  - Do not invent person IDs that were not in the input.

Matching priority (strongest to weakest):
  1. Jersey/bib number — matching numbers = definitely the same person
  2. Clothing color combination (shirt + shorts/pants + accessories)
  3. Equipment (board color/brand, helmet color, bike color)
  4. Hair (color and length — visible from above if not covered)
  5. Build (only when nothing else distinguishes)

For each cluster, set "confidence":
  "high"   — certain match (jersey number, or identical clothing AND equipment)
  "medium" — likely same person but one feature unclear or differs slightly
  "low"    — only one weak feature matches (e.g. generic "black wetsuit" only)

If confidence is "low" AND the cluster spans more than one clip, SPLIT it into
individual single-appearance clusters instead of merging.

FINAL CHECK before answering: verify that every input pair appears once, and that
no cluster contains two appearances from the same clip.

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

# ── Tier 1: visual clustering prompt (used with thumbnail images) ─────────────

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

Hard output constraints:
  - Every input pair (clip_index, person_id) from the text descriptions must
    appear in EXACTLY ONE cluster.
  - A cluster may NEVER contain two appearances from the same clip_index.
    People seen together in one clip are different people.
  - Use the thumbnails as the source of truth when they contradict text.
  - When uncertain, create separate clusters. A missed merge is better than a
    mixed-athlete reel.
  - Do not invent person IDs that were not in the input.

Matching priority (strongest to weakest):
  1. Jersey/bib number visible from above
  2. Clothing color combination (top-down view of torso/shoulders)
  3. Equipment (board, helmet top, bike frame color)
  4. Hair color and style (if visible from above, not covered by helmet)
  5. Body build

For each cluster, set "confidence":
  "high"   — visually certain (jersey number, or identical clothing AND equipment)
  "medium" — likely same but image quality or angle makes it uncertain
  "low"    — only one weak visual cue matches

If confidence is "low" AND the cluster spans more than one clip, SPLIT it into
individual single-appearance clusters instead of merging.

FINAL CHECK before answering: verify that every input pair appears once, and that
no cluster contains two appearances from the same clip.

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


# ── Shared helpers ────────────────────────────────────────────────────────────

def _norm_desc(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(text).lower()).strip()


def _identity_key(clip_index: int | None, person_id: str | None, path: str | None = None) -> tuple:
    """Stable internal key for one detected person in one source clip."""
    if clip_index is not None and person_id:
        return ("clip", int(clip_index), str(person_id))
    return ("path", path or "", person_id or "")


def _person_entries(clip_analyses: list[dict],
                    require_thumbnail: bool = False) -> list[dict]:
    """Flatten clip analyses to one entry per person with usable events."""
    entries: list[dict] = []
    for clip_index, ca in enumerate(clip_analyses):
        for person in ca.get("analysis", {}).get("persons", []):
            person_id = str(person.get("id", "")).strip()
            events = person.get("events") or []
            if not person_id or not events:
                continue
            thumbnail = person.get("thumbnail", "") or ""
            if require_thumbnail and not (thumbnail and os.path.exists(thumbnail)):
                continue
            entries.append({
                "clip_index": clip_index,
                "person_id": person_id,
                "path": ca.get("path", ""),
                "description": person.get("description", "unknown athlete"),
                "events": events,
                "thumbnail": thumbnail,
                "key": _identity_key(clip_index, person_id, ca.get("path", "")),
            })
    return entries


def _appearance_from_entry(entry: dict) -> dict:
    """Create an appearance while retaining internal IDs for safety checks."""
    return {
        "path": entry["path"],
        "events": entry["events"],
        "thumbnail": entry.get("thumbnail", ""),
        "_clip_index": entry.get("clip_index"),
        "_person_id": entry.get("person_id"),
    }


def _cluster_from_entry(entry: dict, description: str | None = None) -> dict:
    return {
        "description": description or entry.get("description", "unknown athlete"),
        "appearances": [_appearance_from_entry(entry)],
    }


def _fallback_clusters(clip_analyses: list[dict]) -> list[dict]:
    """Conservative fallback: one output cluster per detected person."""
    return [_cluster_from_entry(entry) for entry in _person_entries(clip_analyses)]


def _appearance_key(app: dict) -> tuple:
    return _identity_key(app.get("_clip_index"), app.get("_person_id"), app.get("path"))


def _strip_internal_fields(clusters: list[dict]) -> list[dict]:
    """Remove internal matching metadata before handing clusters to the editor."""
    clean: list[dict] = []
    for cluster in clusters:
        appearances: list[dict] = []
        for app in cluster.get("appearances", []):
            out = {
                "path": app.get("path"),
                "events": app.get("events", []),
            }
            if app.get("thumbnail"):
                out["thumbnail"] = app["thumbnail"]
            appearances.append(out)
        if appearances:
            clean.append({
                "description": cluster.get("description", "unknown athlete"),
                "appearances": appearances,
            })
    return clean


def _parse_json_response(raw: str) -> dict:
    """Parse a model JSON response, tolerating markdown fences."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _resolve_model_appearance(app: dict, clip_analyses: list[dict]) -> dict | None:
    """Resolve one model appearance reference back to the pipeline person object."""
    try:
        idx = int(app.get("clip_index", -1))
    except (TypeError, ValueError):
        return None
    pid = str(app.get("person_id", "")).strip()
    if not (0 <= idx < len(clip_analyses)) or not pid:
        return None

    ca = clip_analyses[idx]
    persons = ca.get("analysis", {}).get("persons", [])
    person = next((p for p in persons if str(p.get("id", "")) == pid), None)
    if not person or not person.get("events"):
        return None

    return {
        "clip_index": idx,
        "person_id": pid,
        "path": ca.get("path", ""),
        "events": person["events"],
        "description": person.get("description", "unknown athlete"),
        "thumbnail": person.get("thumbnail", "") or "",
        "key": _identity_key(idx, pid, ca.get("path", "")),
    }


def _cluster_has_same_clip_conflict(cluster: dict) -> bool:
    """A same-person cluster cannot contain two people from one source clip."""
    seen: set[object] = set()
    for app in cluster.get("appearances", []):
        source = app.get("_clip_index")
        if source is None:
            source = app.get("path")
        if source in seen:
            return True
        seen.add(source)
    return False


def _numbers_in_description(text: str) -> set[str]:
    """Extract jersey/bib style numbers, avoiding arbitrary years/timestamps."""
    text = str(text).lower()
    numbers = set(re.findall(r"(?:#|number\s+|no\.\s*|bib\s+|jersey\s+)(\d{1,3})", text))
    # Also catch short descriptions like "player 7 in red shirt" but avoid long numbers.
    numbers.update(re.findall(r"\bplayer\s+(\d{1,3})\b", text))
    return numbers


def _cluster_has_number_conflict(cluster: dict) -> bool:
    """Different visible jersey/bib numbers are a strong identity contradiction."""
    seen: set[str] = set()
    for app in cluster.get("appearances", []):
        nums = _numbers_in_description(app.get("_description", ""))
        if seen and nums and seen.isdisjoint(nums):
            return True
        seen.update(nums)
    return False


def _split_cluster_to_singles(cluster: dict, reason: str) -> list[dict]:
    """Safest repair when a cluster is known to be impossible or too uncertain."""
    apps = cluster.get("appearances", [])
    if len(apps) <= 1:
        return [cluster]
    logger.warning("Splitting identity cluster '%s' into singles: %s",
                   cluster.get("description", "?"), reason)
    print(f"  ✂️  Split identity '{cluster.get('description','?')[:40]}' "
          f"into {len(apps)} separate athlete(s): {reason}")
    result: list[dict] = []
    for app in apps:
        result.append({
            "description": app.get("_description") or cluster.get("description", "unknown athlete"),
            "appearances": [app],
        })
    return result


def _build_clusters_from_data(data: dict, clip_analyses: list[dict]) -> list[dict]:
    """
    Convert Gemini cluster JSON into the standard result format.

    Safeguards:
      - an input appearance can only be used once;
      - same-clip appearances are never allowed in one cluster;
      - low-confidence multi-clip clusters are split;
      - visibly conflicting jersey/bib numbers are split.
    """
    result: list[dict] = []
    used: set[tuple] = set()

    for cluster in data.get("clusters", []):
        confidence = str(cluster.get("confidence", "medium")).lower()
        resolved: list[dict] = []

        for app in cluster.get("appearances", []):
            entry = _resolve_model_appearance(app, clip_analyses)
            if not entry:
                continue
            if entry["key"] in used:
                logger.warning("Duplicate identity appearance ignored: clip=%s person=%s",
                               entry["clip_index"], entry["person_id"])
                continue
            used.add(entry["key"])
            appearance = _appearance_from_entry(entry)
            appearance["_description"] = entry.get("description", "unknown athlete")
            resolved.append(appearance)

        if not resolved:
            continue

        out_cluster = {
            "description": cluster.get("description", "unknown athlete"),
            "appearances": resolved,
        }

        if confidence in ("medium", "low") and len(resolved) > 1:
            logger.warning(
                "⚠️ Cluster '%s' spans %d clips with confidence=%s — check reel for mixed athletes",
                cluster.get("description", "?"), len(resolved), confidence,
            )
            print(f"  ⚠️ Identity confidence={confidence} for "
                  f"'{cluster.get('description','?')[:40]}' across "
                  f"{len(resolved)} clip(s)")

        if confidence == "low" and len(resolved) > 1:
            result.extend(_split_cluster_to_singles(out_cluster, "low model confidence"))
        elif _cluster_has_same_clip_conflict(out_cluster):
            result.extend(_split_cluster_to_singles(out_cluster, "same source clip contains multiple people"))
        elif _cluster_has_number_conflict(out_cluster):
            result.extend(_split_cluster_to_singles(out_cluster, "conflicting jersey/bib numbers"))
        else:
            result.append(out_cluster)

    return result


def _ensure_all_event_persons_present(clusters: list[dict],
                                      clip_analyses: list[dict]) -> list[dict]:
    """
    Add conservative single-person clusters for any analyzed person omitted by a tier.

    This fixes the failure mode where a thumbnail-based tier succeeds for only a
    subset of people and the pipeline accidentally drops the rest.
    """
    present = {_appearance_key(app)
               for cluster in clusters
               for app in cluster.get("appearances", [])}

    out = list(clusters)
    missing: list[dict] = []
    for entry in _person_entries(clip_analyses):
        if entry["key"] not in present:
            missing.append(entry)

    if missing:
        logger.warning("Identity clustering omitted %d detected person(s); adding singleton clusters",
                       len(missing))
        print(f"  ➕ Preserved {len(missing)} unclustered detected person(s) as separate athlete(s)")
        out.extend(_cluster_from_entry(entry) for entry in missing)

    return out


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


# ── Tier 1: Gemini visual clustering (thumbnails uploaded to Files API) ───────

def _try_visual_cluster(descriptions: list[dict], clip_analyses: list[dict]) -> list[dict] | None:
    """
    Preferred Re-ID tier: Gemini sees both per-person thumbnails and text labels.
    Returns None if no thumbnails are available.
    """
    thumb_map: dict[tuple[int, str], str] = {}
    for entry in _person_entries(clip_analyses, require_thumbnail=True):
        thumb_map[(entry["clip_index"], entry["person_id"])] = entry["thumbnail"]

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

        content: list = []
        for uf in uploaded:
            content.append(f"[Clip {uf['clip_index']}, {uf['person_id']}]:")
            content.append(uf["file"])

        content.append(_VISUAL_CLUSTER_PROMPT.format(
            descriptions_json=json.dumps(descriptions, indent=2)
        ))

        raw = _gemini_call_cluster_visual(
            content=content,
            model_name=config.GEMINI_MODEL,
            n_clips=len(clip_analyses),
        )

        data = _parse_json_response(raw)
        return _build_clusters_from_data(data, clip_analyses)

    finally:
        for uf in uploaded:
            try:
                genai.delete_file(uf["file"].name)
            except Exception:
                pass


# ── Tier 2: Gemini text-only clustering ──────────────────────────────────────

def _text_cluster(descriptions: list[dict], clip_analyses: list[dict]) -> list[dict]:
    """Gemini text-only clustering. May raise on persistent Gemini errors."""
    prompt = _CLUSTER_PROMPT_TEMPLATE.format(
        n=len(clip_analyses),
        descriptions_json=json.dumps(descriptions, indent=2),
    )
    raw = _gemini_call_cluster_text(
        prompt=prompt,
        model_name=config.GEMINI_MODEL,
        n_clips=len(clip_analyses),
    )

    data = _parse_json_response(raw)
    return _build_clusters_from_data(data, clip_analyses)


# ── Tier 3: conservative local CLIP fallback ──────────────────────────────────

def _best_non_conflicting_match(i: int, sim_matrix: list[list[float]],
                                entries: list[dict]) -> tuple[int | None, float, float]:
    """Return the best different-clip match and the margin over the runner-up."""
    scored: list[tuple[float, int]] = []
    for j, score in enumerate(sim_matrix[i]):
        if i == j:
            continue
        if entries[i]["clip_index"] == entries[j]["clip_index"]:
            continue
        scored.append((float(score), j))
    if not scored:
        return None, 0.0, 0.0
    scored.sort(reverse=True)
    best_score, best_j = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    return best_j, best_score, best_score - runner_up


def _descriptions_have_strong_conflict(a: str, b: str) -> bool:
    """Deterministic veto for CLIP matches when visible numbers contradict."""
    nums_a = _numbers_in_description(a)
    nums_b = _numbers_in_description(b)
    return bool(nums_a and nums_b and nums_a.isdisjoint(nums_b))


def _try_clip_cluster(clip_analyses: list[dict]) -> list[dict] | None:
    """
    Conservative local fallback using CLIP embeddings.

    CLIP is not a true person Re-ID model, so it is intentionally not used before
    Gemini. It only merges mutual nearest-neighbor pairs above a high threshold
    and leaves every uncertain person as a singleton.
    """
    try:
        import torch
        from PIL import Image as PILImage
    except ImportError:
        logger.debug("CLIP Re-ID unavailable (install torch + transformers + Pillow to enable)")
        return None

    entries = _person_entries(clip_analyses, require_thumbnail=True)
    if len(entries) < 2:
        return None

    try:
        processor, clip_model = _get_clip_model()
    except Exception as e:
        logger.warning("CLIP model load failed: %s", e)
        return None

    valid_entries: list[dict] = []
    embeddings: list = []
    for entry in entries:
        try:
            img = PILImage.open(entry["thumbnail"]).convert("RGB")
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

    emb_matrix = torch.stack(embeddings)
    sim_matrix = (emb_matrix @ emb_matrix.T).tolist()

    n = len(valid_entries)
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    best = [_best_non_conflicting_match(i, sim_matrix, valid_entries) for i in range(n)]
    for i in range(n):
        j, score, margin = best[i]
        if j is None:
            continue
        reverse_j, _, _ = best[j]
        if reverse_j != i:
            continue
        if score < _CLIP_THRESHOLD or margin < _CLIP_MARGIN:
            continue
        if _descriptions_have_strong_conflict(valid_entries[i]["description"],
                                              valid_entries[j]["description"]):
            continue

        pi, pj = _find(i), _find(j)
        if pi != pj:
            parent[pi] = pj

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[_find(i)].append(i)

    result: list[dict] = []
    for group_idxs in groups.values():
        apps = []
        for idx in group_idxs:
            entry = valid_entries[idx]
            app = _appearance_from_entry(entry)
            app["_description"] = entry.get("description", "unknown athlete")
            apps.append(app)

        cluster = {
            "description": valid_entries[group_idxs[0]].get("description", "unknown athlete"),
            "appearances": apps,
        }
        if _cluster_has_same_clip_conflict(cluster) or _cluster_has_number_conflict(cluster):
            result.extend(_split_cluster_to_singles(cluster, "CLIP conflict safeguard"))
        else:
            result.append(cluster)

    return result or None


# ── Post-clustering safeguards ────────────────────────────────────────────────

def _merge_duplicate_clusters(clusters: list[dict]) -> list[dict]:
    """Merge clusters whose descriptions are effectively identical.

    Never merges two clusters that share a source clip; two people in one clip are
    different even if their descriptions are similar.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []

    for c in clusters:
        key = _norm_desc(c.get("description", ""))
        if key and key in merged:
            existing_sources = {
                app.get("_clip_index", app.get("path"))
                for app in merged[key].get("appearances", [])
            }
            incoming_sources = {
                app.get("_clip_index", app.get("path"))
                for app in c.get("appearances", [])
            }
            if existing_sources & incoming_sources:
                unique_key = f"{key}#{len(order)}"
                merged[unique_key] = c
                order.append(unique_key)
                continue

            logger.info("Merging duplicate-description clusters: '%s'",
                        c.get("description", "?")[:40])
            print(f"  🔗 Merged duplicate identity '{c.get('description','?')[:40]}' "
                  f"(+{len(c.get('appearances', []))} clip(s))")
            merged[key]["appearances"].extend(c.get("appearances", []))
        else:
            unique_key = key or f"#{len(order)}"
            merged[unique_key] = c
            order.append(unique_key)

    return [merged[k] for k in order]


_VERIFY_PROMPT = """\
The thumbnail images above were grouped as showing the SAME athlete across
different drone video clips. Verify this grouping.

DRONE/AERIAL footage: do not rely on faces. Compare clothing colors (top-down
view of torso/shoulders), equipment (board/bike/helmet color and shape), and
jersey/bib numbers when visible.

Return ONLY valid JSON, no markdown:
{
  "same_person": true,
  "mismatched_indices": [],
  "reason": "short visual explanation"
}

Rules:
- same_person=true only when all images plausibly show the same athlete.
- If one or more images clearly differ from the majority, set same_person=false
  and list those image numbers in mismatched_indices.
- If there is no clear majority but the images do not look like one athlete,
  set same_person=false and return an empty mismatched_indices list; the caller
  will split the whole group.
- Borderline cases stay together only when clothing/equipment are plausibly the
  same from the drone angle.
"""


def _verify_multi_clusters(clusters: list[dict]) -> list[dict]:
    """Visual verification pass for multi-clip clusters.

    Fail-safe behavior is intentionally conservative:
      - if Gemini identifies specific mismatches, split only those appearances;
      - if Gemini says the group is not one person but cannot isolate a mismatch,
        split the full group into singleton clusters;
      - if verification cannot run, keep the cluster unchanged.
    """
    verified: list[dict] = []
    for cluster in clusters:
        apps = cluster.get("appearances", [])
        thumbs = [a.get("thumbnail", "") for a in apps]
        if len(apps) < 2 or not all(t and os.path.exists(t) for t in thumbs):
            verified.append(cluster)
            continue

        uploaded: list = []
        try:
            content: list = []
            for i, thumb_path in enumerate(thumbs):
                gfile = genai.upload_file(path=thumb_path, mime_type="image/jpeg")
                uploaded.append(gfile)
                content.append(f"[Image {i}]:")
                content.append(gfile)
            content.append(_VERIFY_PROMPT)

            model = genai.GenerativeModel(model_name="gemini-2.5-flash")
            raw = _retry_gemini(lambda: model.generate_content(
                content, request_options={"timeout": 60}
            ).text.strip())
            parsed = _parse_json_response(raw)
            same_person = bool(parsed.get("same_person", not parsed.get("mismatched_indices")))
            bad = {int(i) for i in parsed.get("mismatched_indices", [])
                   if isinstance(i, (int, float)) and 0 <= int(i) < len(apps)}

            if same_person and not bad:
                verified.append(cluster)
                continue

            if not bad or len(bad) >= len(apps):
                verified.extend(_split_cluster_to_singles(
                    cluster, "visual verifier could not confirm same athlete"))
                continue

            keep = [a for i, a in enumerate(apps) if i not in bad]
            split = [a for i, a in enumerate(apps) if i in bad]
            print(f"  ✂️  Identity verification split {len(split)} clip(s) out of "
                  f"'{cluster.get('description','?')[:40]}' — different athlete detected")
            logger.warning("Identity verify: split %d/%d appearance(s) from '%s'",
                           len(split), len(apps), cluster.get("description", "?"))
            verified.append({**cluster, "appearances": keep})
            for app in split:
                verified.append({
                    "description": app.get("_description")
                                   or cluster.get("description", "unknown athlete") + " (separated)",
                    "appearances": [app],
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


def _split_impossible_clusters(clusters: list[dict]) -> list[dict]:
    """Apply deterministic no-guessing safeguards before expensive verification."""
    out: list[dict] = []
    for cluster in clusters:
        if _cluster_has_same_clip_conflict(cluster):
            out.extend(_split_cluster_to_singles(
                cluster, "same source clip contains multiple people"))
        elif _cluster_has_number_conflict(cluster):
            out.extend(_split_cluster_to_singles(
                cluster, "conflicting jersey/bib numbers"))
        else:
            out.append(cluster)
    return out


def _post_process_clusters(clusters: list[dict], clip_analyses: list[dict]) -> list[dict]:
    """Shared safety pass before reels are compiled."""
    if not clusters:
        return clusters

    clusters = _ensure_all_event_persons_present(clusters, clip_analyses)
    clusters = _split_impossible_clusters(clusters)
    clusters = _merge_duplicate_clusters(clusters)
    clusters = _split_impossible_clusters(clusters)
    clusters = _verify_multi_clusters(clusters)
    clusters = _split_impossible_clusters(clusters)
    return _strip_internal_fields(clusters)


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

    Tries tiers in order:
      1. Gemini visual — thumbnails + text descriptions.
      2. Gemini text — text descriptions only.
      3. Conservative CLIP fallback — local embeddings only when Gemini fails.
      4. Per-clip fallback — each person becomes their own cluster.

    Returns:
        list of {"description": str, "appearances": [{"path": str, "events": [...]}]}
    """
    if not clip_analyses:
        return []

    try:
        if len(clip_analyses) == 1:
            return _strip_internal_fields(_fallback_clusters(clip_analyses))

        descriptions = [
            {
                "clip_index": entry["clip_index"],
                "person_id": entry["person_id"],
                "description": entry["description"],
            }
            for entry in _person_entries(clip_analyses)
        ]

        if not descriptions:
            return []

        # ── Tier 1: Gemini visual (thumbnails) ────────────────────────────────
        try:
            result = _try_visual_cluster(descriptions, clip_analyses)
            if result:
                logger.info("Identity clustering: Gemini visual succeeded (%d clusters)", len(result))
                return _post_process_clusters(result, clip_analyses)
        except Exception as e:
            logger.warning("Gemini visual clustering error: %s", e)

        # ── Tier 2: Gemini text ───────────────────────────────────────────────
        try:
            result = _text_cluster(descriptions, clip_analyses)
            if result:
                logger.info("Identity clustering: Gemini text succeeded (%d clusters)", len(result))
                return _post_process_clusters(result, clip_analyses)
        except Exception as e:
            logger.error("Gemini text clustering failed, trying local CLIP fallback: %s", e)

        # ── Tier 3: Conservative CLIP fallback ────────────────────────────────
        try:
            result = _try_clip_cluster(clip_analyses)
            if result:
                logger.info("Identity clustering: CLIP fallback succeeded (%d clusters)", len(result))
                return _post_process_clusters(result, clip_analyses)
        except Exception as e:
            logger.warning("CLIP clustering error: %s", e)

        # ── Tier 4: per-clip fallback ─────────────────────────────────────────
        logger.warning("Identity clustering fell back to one cluster per detected person")
        return _strip_internal_fields(_fallback_clusters(clip_analyses))

    finally:
        _cleanup_thumbnails(clip_analyses)
