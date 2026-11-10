"""
pipeline/stages/identity.py — Cross-clip identity clustering.

The pipeline first asks Gemini to match athletes using the actual per-person
thumbnails, then falls back to text descriptions, then uses a conservative local
CLIP fallback only when Gemini is unavailable. The post-processing layer is
deliberately conservative: it prevents mixed-athlete reels by splitting uncertain
or impossible clusters instead of guessing.
"""

import json
from concurrent.futures import ThreadPoolExecutor
import logging
import os
import re
import time
from collections import defaultdict

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover - optional in lightweight test envs
    def traceable(*_args, **_kwargs):
        def _decorator(fn):
            return fn
        return _args[0] if _args and callable(_args[0]) and not _kwargs else _decorator

import config
from pipeline import identity_trace
try:
    from integrations.gemini import genai
except ImportError:  # pragma: no cover - optional in lightweight test envs
    genai = None

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
Each image may be a contact sheet of up to 4 crops (2x2 grid) of that ONE tracked person at
different moments of the clip: treat all crops in one image as the same person and use every
view (front, back, side, near, far) together before deciding.
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
  - Combine the 2x2 contact-sheet crops with the full-video text description:
    if a surfboard/equipment is temporarily submerged underwater or obscured by
    whitewater in a thumbnail crop, do NOT treat that as contradicting the board
    color/type observed across the full video in the text description.
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
        "_description": entry.get("description", "unknown athlete"),
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
            item = {
                "description": cluster.get("description", "unknown athlete"),
                "appearances": appearances,
            }
            if cluster.get("_visual_verified"):
                item["_visual_verified"] = True
            clean.append(item)
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
    print(f"  [SPLIT] Split identity '{cluster.get('description','?')[:40]}' "
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
            print(f"  [WARN] Identity confidence={confidence} for "
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
        print(f"  [+] Preserved {len(missing)} unclustered detected person(s) as separate athlete(s)")
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
        # Uploads (and the deletes in `finally`) are network waits; one at a time they cost run 42857524999
        # ~2.5 min of the critical path before rendering (23 thumbnails). Run them concurrently but keep the
        # original order, so Gemini receives exactly the same request.
        def _upload(item):
            (ci, pid), thumb_path = item
            try:
                return {"clip_index": ci, "person_id": pid, "file": genai.upload_file(path=thumb_path, mime_type="image/jpeg")}
            except Exception as e:
                logger.debug("Thumbnail upload failed for clip %d %s: %s", ci, pid, e)
                return None

        with ThreadPoolExecutor(max_workers=_FILES_API_WORKERS) as pool:
            uploaded = [u for u in pool.map(_upload, list(thumb_map.items())) if u is not None]

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
        _delete_files_concurrently([uf["file"] for uf in uploaded])


_FILES_API_WORKERS = 8


def _delete_files_concurrently(files: list) -> None:
    def _delete(gfile):
        try:
            genai.delete_file(gfile.name)
        except Exception:
            pass

    if files:
        with ThreadPoolExecutor(max_workers=_FILES_API_WORKERS) as pool:
            list(pool.map(_delete, files))


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
            print(f"  [MERGE] Merged duplicate identity '{c.get('description','?')[:40]}' "
                  f"(+{len(c.get('appearances', []))} clip(s))")
            merged[key]["appearances"].extend(c.get("appearances", []))
        else:
            unique_key = key or f"#{len(order)}"
            merged[unique_key] = c
            order.append(unique_key)

    return [merged[k] for k in order]


def extract_structured_attributes(description: str) -> dict:
    """Extract normalized multi-sport athlete & equipment attributes from an aerial/sports description."""
    text = " " + re.sub(r"[^a-z0-9/-]+", " ", str(description or "").lower()).strip() + " "
    if " no surfer visible " in text or " empty wave " in text or text.strip() in {"", "unknown athlete"}:
        return {"empty": True}

    numbers = set(
        re.findall(
            r"(?:#|number\s+|no\.\s*|bib\s+|jersey\s+|player\s+)(\d{1,3})\b",
            str(description or "").lower(),
        )
    )
    companion = (
        "tandem"
        if any(k in text for k in (" with a child ", " second person ", " two people ", " tandem "))
        else "solo"
    )
    gender_age = None
    if any(k in text for k in (" bikini ", " one-piece ", " female ", " woman ", " girl ")):
        gender_age = "female"
    elif any(k in text for k in (" shirtless ", " no shirt ", " beard ", " male ", " man ")):
        gender_age = "male"

    equip_match = re.search(
        r"\b(?:on|riding|carrying|with)\s+(?:a|an|the)?\s*((?:(?!\bin\b|\bwith\b|\band\b|\bon\b)[a-z0-9/()-]+\s+){0,4}?)(longboard|surfboard|shortboard|board|wakeboard|snowboard|skateboard|paddleboard|bike|bicycle|kayak|skis)\b",
        text,
    )
    equip_type = None
    equip_color = None
    if equip_match:
        equip_mod = " " + equip_match.group(1) + " "
        raw_etype = equip_match.group(2)
        equip_type = "board" if "board" in raw_etype else raw_etype
        if any(c in equip_mod for c in (" pink ", " magenta ", " rose ", " red/pink ")):
            equip_color = "pink" if " red/pink " not in equip_mod else "red"
        elif any(c in equip_mod for c in (" red ", " crimson ")):
            equip_color = "red"
        elif any(c in equip_mod.replace(chr(47), chr(32)) for c in (" turquoise ", " light blue ", " blue ", " teal ", " cyan ", " aqua ")):
            equip_color = "turquoise_blue"
        elif any(c in equip_mod for c in (" bright green ", " green ", " lime ")):
            equip_color = "green"
        elif any(c in equip_mod for c in (" tan ", " brown ", " wood ")):
            equip_color = "tan"
        elif any(c in equip_mod for c in (" yellow ", " orange ", " gold ")) and " yellowish " not in equip_mod:
            equip_color = "yellow"
        elif any(c in equip_mod for c in (" white ", " light-colored ", " light ", " yellowish ")):
            equip_color = "white_light"
        elif any(c in equip_mod for c in (" black ", " dark ")):
            equip_color = "black_dark"

    apparel_text = text
    if equip_match:
        apparel_text = text[: equip_match.start()] + " " + text[equip_match.end() :]

    sleeve_style = None
    is_full_wetsuit = (
        bool(
            re.search(
                r"\b(?:full\s+(?:dark\s+|black\s+)?wetsuit|in\s+a\s+(?:black|dark)\s+wetsuit)\b",
                apparel_text,
            )
        )
        and "wetsuit top" not in apparel_text
    )
    if any(k in apparel_text for k in (" shirtless ", " no shirt ", " bare-chested ")):
        sleeve_style = "shirtless"
    elif any(k in apparel_text for k in (" bikini ", " one-piece ", " swimsuit ")):
        sleeve_style = "swimwear"
    elif any(k in apparel_text for k in (" sleeveless ", " tank top ", " singlet ")):
        sleeve_style = "sleeveless"
    elif any(
        k in apparel_text
        for k in (" long-sleeve ", " long-sleeved ", " hooded ", " rash guard ", " wetsuit top ")
    ):
        sleeve_style = "long_sleeve"
    elif is_full_wetsuit:
        sleeve_style = "full_wetsuit"
    elif any(k in apparel_text for k in (" t-shirt ", " short-sleeve ", " short-sleeved ", " shirt ", " top ")):
        sleeve_style = "shirt_top"

    top_color = None
    if sleeve_style == "shirtless":
        top_color = "none"
    else:
        top_clause = re.split(
            r"\b(?:and\s+[a-z0-9/-]+\s+shorts|and\s+shorts|shorts|trunks)\b",
            apparel_text,
        )[0]
        if any(c in top_clause for c in (" pink ", " magenta ")):
            top_color = "pink"
        elif any(c in top_clause for c in (" purple ", " maroon ", " burgundy ")):
            top_color = "purple_maroon"
        elif any(c in top_clause for c in (" red ", " crimson ")):
            top_color = "red"
        elif any(c in top_clause for c in (" yellow ", " orange ", " gold ")):
            top_color = "yellow_orange"
        elif any(c in top_clause for c in (" white ", " light-colored ")) and " light blue" not in top_clause:
            top_color = "white_light"
        elif any(
            c in top_clause
            for c in (
                " green-grey ",
                " dark green ",
                " green ",
                " grey ",
                " gray ",
                " light blue/grey ",
                " blue/grey ",
                " grey/dark green ",
                " grey/green ",
            )
        ):
            top_color = "cool_grey_green"
        elif any(c in top_clause for c in (" teal ", " turquoise ", " blue ")):
            top_color = "blue_teal"
        elif " black " in top_clause:
            top_color = "black"
        elif " dark " in top_clause:
            top_color = "dark"

    bottom_color = None
    bottom_match = re.search(
        r"\b([a-z0-9/-]+(?:\s+[a-z0-9/-]+)?)\s+(?:shorts|trunks|bottoms|pants)\b",
        apparel_text,
    )
    if bottom_match:
        bmod = " " + bottom_match.group(1) + " "
        if any(c in bmod for c in (" red ", " orange ", " red/orange ")):
            bottom_color = "red_orange"
        elif any(c in bmod for c in (" white ", " light-colored ", " light ")):
            bottom_color = "light"
        elif any(c in bmod for c in (" black ", " dark ")):
            bottom_color = "dark"
        elif any(c in bmod for c in (" blue ", " turquoise ")):
            bottom_color = "blue"
    elif " and shorts " in apparel_text and top_color in {"black", "dark"}:
        bottom_color = "dark"

    return {
        "empty": False,
        "numbers": numbers,
        "companion": companion,
        "gender_age": gender_age,
        "equip_type": equip_type,
        "equip_color": equip_color,
        "sleeve_style": sleeve_style,
        "top_color": top_color,
        "bottom_color": bottom_color,
    }


def _top_colors_compatible(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return True
    if a == b:
        return True
    if {a, b} <= {"cool_grey_green", "dark"}:
        return True
    if {a, b} <= {"black", "dark"}:
        return True
    return False


# Labels that describe the same long-sleeved wetsuit coverage. From a drone, "a black long-sleeved wetsuit top and
# dark shorts" and "a black wetsuit" are the same silhouette: runs 42814819534 and 42857524999 split one surfer
# (0074 / 0151, confirmed by the operator) because the parser labelled them long_sleeve and full_wetsuit. Every
# other difference (shirtless, swimwear, sleeveless, short-sleeved shirt) stays a hard conflict.
_SAME_COVERAGE = ({"long_sleeve", "full_wetsuit"},)


def _sleeve_styles_compatible(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return True
    if a == b:
        return True
    return any({a, b} <= group for group in _SAME_COVERAGE)


def structured_attributes_compatible(attr_a: dict, attr_b: dict) -> tuple[bool, float]:
    """Return (is_compatible, similarity_score) for two structured attribute dicts."""
    if attr_a.get("empty") or attr_b.get("empty"):
        return False, 0.0
    nums_a, nums_b = attr_a.get("numbers") or set(), attr_b.get("numbers") or set()
    if nums_a and nums_b:
        if nums_a.isdisjoint(nums_b):
            return False, 0.0
        return True, 1.0
    if attr_a.get("companion") != attr_b.get("companion"):
        return False, 0.0
    ga, gb = attr_a.get("gender_age"), attr_b.get("gender_age")
    if ga and gb and ga != gb:
        return False, 0.0
    if not _sleeve_styles_compatible(attr_a.get("sleeve_style"), attr_b.get("sleeve_style")):
        return False, 0.0
    if not _top_colors_compatible(attr_a.get("top_color"), attr_b.get("top_color")):
        return False, 0.0
    ba, bb = attr_a.get("bottom_color"), attr_b.get("bottom_color")
    if (
        ba
        and bb
        and ba != bb
        and not (
            {ba, bb} <= {"dark", "red_orange"}
            and attr_a.get("equip_color") == "turquoise_blue"
            and attr_b.get("equip_color") == "turquoise_blue"
        )
    ):
        return False, 0.0
    ea, eb = attr_a.get("equip_type"), attr_b.get("equip_type")
    if ea and eb and ea != eb:
        return False, 0.0
    eca, ecb = attr_a.get("equip_color"), attr_b.get("equip_color")
    if eca and ecb and eca != ecb:
        return False, 0.0

    score = 0.0
    if eca and ecb and eca == ecb:
        score += 0.45
    ta, tb = attr_a.get("top_color"), attr_b.get("top_color")
    if ta and tb and _top_colors_compatible(ta, tb):
        score += 0.30 if ta == tb else 0.25
    sa, sb = attr_a.get("sleeve_style"), attr_b.get("sleeve_style")
    if sa and sb and sa == sb:
        score += 0.15
    if ba and bb and ba == bb:
        score += 0.10
    return score >= 0.70, round(score, 3)


def score_structured_identity_match(desc_a: str, desc_b: str) -> float:
    """Return calibrated structured attribute similarity in [0.0, 1.0] between two athlete descriptions."""
    attr_a = extract_structured_attributes(desc_a)
    attr_b = extract_structured_attributes(desc_b)
    ok, score = structured_attributes_compatible(attr_a, attr_b)
    return score if ok else 0.0


def _appearance_structured_attrs(app: dict, fallback_desc: str = "") -> dict:
    desc = str(app.get("_description") or fallback_desc or "")
    attrs = extract_structured_attributes(desc)
    if fallback_desc and fallback_desc != desc:
        visual_attrs = extract_structured_attributes(fallback_desc)
        if not visual_attrs.get("empty"):
            v_ec = visual_attrs.get("equip_color")
            a_ec = attrs.get("equip_color")
            if v_ec and a_ec and v_ec != a_ec:
                return {"empty": True}
    return attrs


def _cluster_structured_verified(cluster: dict) -> bool:
    """Return True when all appearances in a multi-clip cluster have strong structured attribute agreement."""
    apps = cluster.get("appearances", []) or []
    if len(apps) < 2:
        return False
    fallback = str(cluster.get("description") or "")
    attrs = [_appearance_structured_attrs(a, fallback) for a in apps]
    for i in range(len(attrs)):
        for j in range(i + 1, len(attrs)):
            ok, _ = structured_attributes_compatible(attrs[i], attrs[j])
            if not ok:
                return False
    return True


def _merge_compatible_structured_clusters(clusters: list[dict]) -> list[dict]:
    """Merge fragmented clusters when full-video structured attributes strongly match without conflict.

    Never merges clusters that share a source clip or have conflicting jersey numbers or apparel/equipment.
    """
    out: list[dict] = []
    for candidate in clusters:
        c_apps = candidate.get("appearances", []) or []
        if not c_apps:
            continue
        c_sources = {a.get("_clip_index", a.get("path")) for a in c_apps}
        c_attrs = [_appearance_structured_attrs(a, str(candidate.get("description") or "")) for a in c_apps]
        merged_into = None
        best_score = 0.0

        for idx, target in enumerate(out):
            t_apps = target.get("appearances", []) or []
            t_sources = {a.get("_clip_index", a.get("path")) for a in t_apps}
            if c_sources & t_sources:
                continue
            combined = {
                "description": target.get("description", ""),
                "appearances": t_apps + c_apps,
            }
            if _cluster_has_same_clip_conflict(combined) or _cluster_has_number_conflict(combined):
                continue
            from pipeline.identity_decision_engine import IdentityDecisionEngine
            engine = IdentityDecisionEngine()
            pair_scores: list[float] = []
            compatible = True
            for ta in t_apps:
                for ca in c_apps:
                    dec = engine.evaluate_pair(ta, ca)
                    if dec.decision == "NO_MATCH":
                        compatible = False
                        break
                    pair_scores.append(dec.score)
                if not compatible:
                    break
            if compatible and pair_scores:
                mean_score = sum(pair_scores) / len(pair_scores)
                if mean_score >= engine.match_threshold and mean_score > best_score:
                    best_score = mean_score
                    merged_into = idx

        if merged_into is not None:
            target = out[merged_into]
            logger.info(
                "Merging structured-compatible clusters (score=%.2f): '%s' <- '%s'",
                best_score,
                target.get("description", "?")[:40],
                candidate.get("description", "?")[:40],
            )
            print(
                f"  🔗 Merged structured identity '{target.get('description','?')[:40]}' "
                f"<- '{candidate.get('description','?')[:40]}' (score={best_score:.2f})"
            )
            target["appearances"].extend(c_apps)
            target["_visual_verified"] = True
        else:
            out.append(candidate)

    return out


_VERIFY_PROMPT = """\
The thumbnail images above were grouped as showing the SAME athlete across
different drone video clips. Verify this grouping.
Each image may be a contact sheet of up to 4 crops (2x2 grid) of one tracked person at
different moments of that clip; all crops in one image are the same person.

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
        if _cluster_structured_verified(cluster):
            verified.append({**cluster, "_visual_verified": True})
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
            print(f"  [SPLIT] Identity verification split {len(split)} clip(s) out of "
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
    from pipeline.identity_decision_engine import IdentityDecisionEngine
    engine = IdentityDecisionEngine()
    out: list[dict] = []
    for cluster in clusters:
        if _cluster_has_same_clip_conflict(cluster):
            out.extend(_split_cluster_to_singles(
                cluster, "same source clip contains multiple people"))
        elif _cluster_has_number_conflict(cluster):
            out.extend(_split_cluster_to_singles(
                cluster, "conflicting jersey/bib numbers"))
        else:
            apps = cluster.get("appearances", []) or []
            has_no_match = False
            split_reason = ""
            for i in range(len(apps)):
                for j in range(i + 1, len(apps)):
                    dec = engine.evaluate_pair(apps[i], apps[j])
                    hard_conflict_reasons = {
                        "same_source_clip_conflict",
                        "conflicting_jersey_or_bib_numbers",
                        "companion_solo_vs_tandem_conflict",
                        "incompatible_swimwear_or_category",
                        "wetsuit_vs_bare_or_swimsuit_conflict",
                        "conflicting_equipment_color",
                        "rejected_by_semantic_or_visual_verifier",
                    }
                    if any(r in hard_conflict_reasons for r in dec.reasons):
                        has_no_match = True
                        split_reason = f"IdentityDecisionEngine hard conflict ({', '.join(dec.reasons)})"
                        break
                if has_no_match:
                    break
            if has_no_match:
                out.extend(_split_cluster_to_singles(cluster, split_reason))
            else:
                out.append(cluster)
    return out


def _post_process_clusters(clusters: list[dict], clip_analyses: list[dict]) -> list[dict]:
    """Shared safety pass before reels are compiled."""
    if not clusters:
        return clusters
    identity_trace.record_layer("model", clusters)
    result = _post_process_clusters_inner(clusters, clip_analyses)
    identity_trace.record_layer("post_process", result)
    return result


def _post_process_clusters_inner(clusters: list[dict], clip_analyses: list[dict]) -> list[dict]:

    clusters = _ensure_all_event_persons_present(clusters, clip_analyses)
    clusters = _split_impossible_clusters(clusters)
    clusters = _merge_duplicate_clusters(clusters)
    clusters = _merge_compatible_structured_clusters(clusters)
    clusters = _split_impossible_clusters(clusters)
    clusters = _verify_multi_clusters(clusters)
    clusters = _merge_compatible_structured_clusters(clusters)
    clusters = _split_impossible_clusters(clusters)
    try:
        from pipeline.identity_decision_engine import IdentityDecisionEngine
        engine = IdentityDecisionEngine()
        decision_records = []
        for idx, cl in enumerate(clusters):
            apps = cl.get("appearances", []) or []
            if len(apps) >= 2:
                dec = engine.evaluate_pair(
                    apps[0],
                    apps[1],
                    semantic_decision="MATCH",
                    semantic_confidence=str(cl.get("confidence") or "high"),
                    visual_verified=bool(cl.get("_visual_verified")),
                )
                decision_records.append({"cluster_index": idx, **dec.to_dict()})
        identity_trace.record_metadata("identity_decision_engine", {
            "evaluated_multi_clip_clusters": len(decision_records),
            "decisions": decision_records,
        })
    except Exception as dec_exc:
        logger.debug("Identity decision engine trace skipped: %s", dec_exc)
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


def _traced_fallback(clip_analyses: list[dict]) -> list[dict]:
    result = _strip_internal_fields(_fallback_clusters(clip_analyses))
    identity_trace.record_layer("model", result)
    identity_trace.record_layer("post_process", result)
    return result


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

    identity_trace.record_persons(clip_analyses)
    try:
        if len(clip_analyses) == 1:
            return _traced_fallback(clip_analyses)

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

        # ── OPT-02: Local visual embedding candidate evaluation before Gemini ─
        try:
            from pipeline import visual_embeddings
            emb_summary = visual_embeddings.evaluate_candidate_pairs(_person_entries(clip_analyses))
            identity_trace.record_metadata("visual_embedding_prefilter", {
                "model_version": emb_summary.get("model_version"),
                "crop_version": emb_summary.get("crop_version"),
                "shadow_mode": emb_summary.get("shadow_mode"),
                "total_entries": emb_summary.get("total_entries"),
                "embeddings_computed": emb_summary.get("embeddings_computed"),
                "embeddings_cache_hits": emb_summary.get("embeddings_cache_hits"),
                "total_cross_clip_pairs": emb_summary.get("total_cross_clip_pairs"),
                "plausible_pairs_count": emb_summary.get("plausible_pairs_count"),
                "rejected_pairs_count": emb_summary.get("rejected_pairs_count"),
                "strong_local_matches_count": emb_summary.get("strong_local_matches_count"),
            })
        except Exception as emb_exc:
            logger.debug("Visual embedding prefilter skipped: %s", emb_exc)

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
        return _traced_fallback(clip_analyses)

    finally:
        _cleanup_thumbnails(clip_analyses)
