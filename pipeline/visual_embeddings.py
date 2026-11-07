"""Local visual embeddings for 2x2 contact sheet crops with caching and shadow mode (OPT-02).

Computes multi-view visual appearance embeddings from the 4 crops of each athlete's
2x2 contact sheet (upper torso/shoulders, lower body, and equipment regions) to:
  1. Measure visual similarity between athlete appearances across different source clips.
  2. Prune implausible cross-clip pairs and identify high-confidence candidate matches
     before expensive Gemini calls.
  3. Cache embeddings deterministically by (model_version, crop_version, source_sha256).
  4. Support Shadow Mode (`SPORTREEL_EMBEDDING_SHADOW_MODE=1`) where embedding decisions
     are logged and traced without altering clustering output.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

from integrations import llm_cache as _llm_cache

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_VERSION = "aerial-multiview-hsv-spatial-v1"
CROP_GRID_VERSION = "contact-sheet-2x2-v1"
DEFAULT_MIN_PLAUSIBLE_SIMILARITY = 0.32
DEFAULT_HIGH_CONFIDENCE_SIMILARITY = 0.88


def shadow_mode_enabled() -> bool:
    """Return whether visual embedding pre-filtering runs in observational shadow mode."""
    return os.getenv("SPORTREEL_EMBEDDING_SHADOW_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-9:
        return [0.0 for _ in vec]
    return [round(v / norm, 6) for v in vec]


def cosine_similarity(vec_a: list[float] | None, vec_b: list[float] | None) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0
    return round(max(-1.0, min(1.0, dot / (norm_a * norm_b))), 4)


def _rgb_to_hsv_bins(r: float, g: float, b: float) -> tuple[int, int, int]:
    """Map normalized RGB in [0, 1] to (hue_bin 0..7, sat_bin 0..2, val_bin 0..2)."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    diff = mx - mn
    if diff <= 1e-6:
        h = 0.0
    elif mx == r:
        h = ((g - b) / diff) % 6.0
    elif mx == g:
        h = ((b - r) / diff) + 2.0
    else:
        h = ((r - g) / diff) + 4.0
    h_deg = (h * 60.0) % 360.0
    s = 0.0 if mx <= 1e-6 else diff / mx
    v = mx
    h_bin = min(7, int(h_deg // 45.0))
    s_bin = 0 if s < 0.20 else (1 if s < 0.55 else 2)
    v_bin = 0 if v < 0.25 else (1 if v < 0.65 else 2)
    return h_bin, s_bin, v_bin


def _extract_region_descriptor(img_rgb: Any, box: tuple[int, int, int, int]) -> list[float]:
    """Extract a 32-dim color + luminance descriptor from a sub-region of a PIL RGB image."""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return [0.0] * 32
    region = img_rgb.crop((x1, y1, x2, y2)).resize((16, 16))
    pixels = list(region.getdata())
    if not pixels:
        return [0.0] * 32

    hue_hist = [0.0] * 8
    sat_hist = [0.0] * 3
    val_hist = [0.0] * 3
    achromatic_bins = [0.0] * 4  # black/dark, grey, white/light, bright-saturated
    r_sum = g_sum = b_sum = 0.0
    r_sq = g_sq = b_sq = 0.0
    n = float(len(pixels))

    for px in pixels:
        r, g, b = px[0] / 255.0, px[1] / 255.0, px[2] / 255.0
        r_sum += r
        g_sum += g
        b_sum += b
        r_sq += r * r
        g_sq += g * g
        b_sq += b * b
        hb, sb, vb = _rgb_to_hsv_bins(r, g, b)
        if sb > 0:
            hue_hist[hb] += 1.0
        sat_hist[sb] += 1.0
        val_hist[vb] += 1.0
        if vb == 0:
            achromatic_bins[0] += 1.0
        elif sb == 0 and vb == 1:
            achromatic_bins[1] += 1.0
        elif sb == 0 and vb == 2:
            achromatic_bins[2] += 1.0
        else:
            achromatic_bins[3] += 1.0

    r_mean, g_mean, b_mean = r_sum / n, g_sum / n, b_sum / n
    r_std = math.sqrt(max(0.0, r_sq / n - r_mean * r_mean))
    g_std = math.sqrt(max(0.0, g_sq / n - g_mean * g_mean))
    b_std = math.sqrt(max(0.0, b_sq / n - b_mean * b_mean))

    # Chromatic ratios (robust to shadow/sunlight changes in drone footage)
    rg_diff = (r_mean - g_mean) * 0.5 + 0.5
    yb_diff = ((r_mean + g_mean) * 0.5 - b_mean) * 0.5 + 0.5

    raw_vec = (
        [c / n for c in hue_hist]          # 8
        + [c / n for c in sat_hist]        # 3
        + [c / n for c in val_hist]        # 3
        + [c / n for c in achromatic_bins] # 4
        + [r_mean, g_mean, b_mean, r_std, g_std, b_std, rg_diff, yb_diff] # 8
        + [0.0] * 6                        # pad to 32
    )[:32]
    return _l2_normalize(raw_vec)


def _extract_single_crop_embedding(crop_img: Any) -> list[float]:
    """Compute a 96-dim embedding for one crop (upper torso + lower torso + equipment zone)."""
    w, h = crop_img.size
    if w < 4 or h < 4:
        return [0.0] * 96
    upper_box = (int(w * 0.22), int(h * 0.16), max(int(w * 0.22) + 1, int(w * 0.78)), max(int(h * 0.16) + 1, int(h * 0.50)))
    lower_box = (int(w * 0.22), int(h * 0.46), max(int(w * 0.22) + 1, int(w * 0.78)), max(int(h * 0.46) + 1, int(h * 0.78)))
    equip_box = (int(w * 0.10), int(h * 0.62), max(int(w * 0.10) + 1, int(w * 0.90)), max(int(h * 0.62) + 1, int(h * 0.94)))

    u_vec = _extract_region_descriptor(crop_img, upper_box)
    l_vec = _extract_region_descriptor(crop_img, lower_box)
    e_vec = _extract_region_descriptor(crop_img, equip_box)
    # Weight upper torso/shoulders highest (0.50), lower body (0.30), equipment (0.20)
    combined = (
        [v * 0.50 for v in u_vec]
        + [v * 0.30 for v in l_vec]
        + [v * 0.20 for v in e_vec]
    )
    return _l2_normalize(combined)


def _split_contact_sheet_quadrants(img_rgb: Any) -> list[Any]:
    """Split a 2x2 contact sheet into 4 quadrant images (or return [img_rgb] if single crop)."""
    w, h = img_rgb.size
    if w >= 320 and h >= 320:
        mid_x, mid_y = w // 2, h // 2
        return [
            img_rgb.crop((0, 0, mid_x, mid_y)),
            img_rgb.crop((mid_x, 0, w, mid_y)),
            img_rgb.crop((0, mid_y, mid_x, h)),
            img_rgb.crop((mid_x, mid_y, w, h)),
        ]
    return [img_rgb]


def embedding_cache_key(thumbnail_path: str) -> str | None:
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        return None
    try:
        media_sha = _llm_cache.file_sha256(thumbnail_path)
        return _llm_cache.make_key(
            "visual-embedding",
            media_sha256=media_sha,
            prompt=CROP_GRID_VERSION,
            model=EMBEDDING_MODEL_VERSION,
            version="1",
            extra=f"grid={CROP_GRID_VERSION}|model={EMBEDDING_MODEL_VERSION}",
        )
    except Exception:
        return None


def compute_contact_sheet_embedding(thumbnail_path: str) -> dict[str, Any] | None:
    """Compute or load cached multi-view visual embedding for a contact-sheet image."""
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        return None

    cache_key = embedding_cache_key(thumbnail_path)
    if cache_key and _llm_cache.enabled():
        cached_raw = _llm_cache.get(cache_key)
        if cached_raw:
            try:
                parsed = json.loads(cached_raw)
                if (
                    isinstance(parsed, dict)
                    and parsed.get("model_version") == EMBEDDING_MODEL_VERSION
                    and parsed.get("crop_version") == CROP_GRID_VERSION
                    and isinstance(parsed.get("pooled_embedding"), list)
                ):
                    return {**parsed, "cache_hit": True}
            except Exception:
                pass

    try:
        from PIL import Image as PILImage
        img = PILImage.open(thumbnail_path).convert("RGB")
    except Exception as exc:
        logger.debug("Could not open thumbnail %s for visual embedding: %s", thumbnail_path, exc)
        return None

    quadrants = _split_contact_sheet_quadrants(img)
    crop_embeddings = [_extract_single_crop_embedding(q) for q in quadrants]
    dim = len(crop_embeddings[0])
    pooled = [
        sum(crop_vec[d] for crop_vec in crop_embeddings) / len(crop_embeddings)
        for d in range(dim)
    ]
    pooled = _l2_normalize(pooled)

    payload = {
        "model_version": EMBEDDING_MODEL_VERSION,
        "crop_version": CROP_GRID_VERSION,
        "source_sha256": _llm_cache.file_sha256(thumbnail_path),
        "crop_count": len(crop_embeddings),
        "embedding_dim": dim,
        "pooled_embedding": pooled,
        "crop_embeddings": crop_embeddings,
        "cache_hit": False,
    }
    if cache_key and _llm_cache.enabled():
        try:
            _llm_cache.put(
                cache_key,
                json.dumps(payload, separators=(",", ":")),
                source=Path(thumbnail_path).name,
            )
        except Exception:
            pass
    return payload


def compare_contact_sheet_embeddings(
    emb_a: dict[str, Any] | None,
    emb_b: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare two multi-view contact sheet embeddings using pooled + best-quadrant similarity."""
    if not emb_a or not emb_b:
        return {"available": False, "similarity": None, "pooled_similarity": None, "best_crop_similarity": None}

    pooled_sim = cosine_similarity(emb_a.get("pooled_embedding"), emb_b.get("pooled_embedding"))
    crops_a = emb_a.get("crop_embeddings") or []
    crops_b = emb_b.get("crop_embeddings") or []
    best_crop_sim = pooled_sim
    if crops_a and crops_b:
        sims = [cosine_similarity(ca, cb) for ca in crops_a for cb in crops_b]
        if sims:
            best_crop_sim = max(sims)

    combined = round(0.60 * pooled_sim + 0.40 * best_crop_sim, 4)
    return {
        "available": True,
        "similarity": combined,
        "pooled_similarity": pooled_sim,
        "best_crop_similarity": best_crop_sim,
    }


def evaluate_candidate_pairs(
    entries: list[dict[str, Any]],
    *,
    min_plausible_similarity: float = DEFAULT_MIN_PLAUSIBLE_SIMILARITY,
    high_confidence_similarity: float = DEFAULT_HIGH_CONFIDENCE_SIMILARITY,
    shadow_mode: bool | None = None,
) -> dict[str, Any]:
    """Pre-filter cross-clip candidate pairs using local visual embeddings (OPT-02).

    Never compares appearances from the same source clip (two people in the same clip
    are distinct athletes).
    """
    is_shadow = shadow_mode_enabled() if shadow_mode is None else bool(shadow_mode)
    embeddings_by_idx: dict[int, dict[str, Any] | None] = {}
    cache_hits = 0
    computed = 0

    for idx, entry in enumerate(entries):
        thumb = entry.get("thumbnail") or ""
        emb = compute_contact_sheet_embedding(thumb) if thumb else None
        embeddings_by_idx[idx] = emb
        if emb:
            if emb.get("cache_hit"):
                cache_hits += 1
            else:
                computed += 1

    plausible_pairs: list[dict[str, Any]] = []
    rejected_pairs: list[dict[str, Any]] = []
    strong_matches: list[dict[str, Any]] = []
    pair_scores: dict[tuple[int, int], float] = {}

    n = len(entries)
    for i in range(n):
        for j in range(i + 1, n):
            src_i = entries[i].get("clip_index", entries[i].get("path"))
            src_j = entries[j].get("clip_index", entries[j].get("path"))
            if src_i == src_j:
                continue
            comp = compare_contact_sheet_embeddings(embeddings_by_idx.get(i), embeddings_by_idx.get(j))
            sim = comp.get("similarity")
            pair_record = {
                "i": i,
                "j": j,
                "key_i": f"{Path(str(entries[i].get('path', ''))).name}::{entries[i].get('person_id', '')}",
                "key_j": f"{Path(str(entries[j].get('path', ''))).name}::{entries[j].get('person_id', '')}",
                "similarity": sim,
                "pooled_similarity": comp.get("pooled_similarity"),
                "best_crop_similarity": comp.get("best_crop_similarity"),
            }
            if sim is not None:
                pair_scores[(i, j)] = sim
                pair_scores[(j, i)] = sim
            if sim is None or sim >= min_plausible_similarity:
                plausible_pairs.append(pair_record)
                if sim is not None and sim >= high_confidence_similarity:
                    strong_matches.append(pair_record)
            else:
                rejected_pairs.append(pair_record)

    return {
        "model_version": EMBEDDING_MODEL_VERSION,
        "crop_version": CROP_GRID_VERSION,
        "shadow_mode": is_shadow,
        "total_entries": n,
        "embeddings_computed": computed,
        "embeddings_cache_hits": cache_hits,
        "total_cross_clip_pairs": len(plausible_pairs) + len(rejected_pairs),
        "plausible_pairs_count": len(plausible_pairs),
        "rejected_pairs_count": len(rejected_pairs),
        "strong_local_matches_count": len(strong_matches),
        "plausible_pairs": plausible_pairs,
        "rejected_pairs": rejected_pairs,
        "strong_local_matches": strong_matches,
        "pair_scores": pair_scores,
        "embeddings_by_idx": embeddings_by_idx,
    }


__all__ = [
    "CROP_GRID_VERSION",
    "DEFAULT_HIGH_CONFIDENCE_SIMILARITY",
    "DEFAULT_MIN_PLAUSIBLE_SIMILARITY",
    "EMBEDDING_MODEL_VERSION",
    "compare_contact_sheet_embeddings",
    "compute_contact_sheet_embedding",
    "cosine_similarity",
    "embedding_cache_key",
    "evaluate_candidate_pairs",
    "shadow_mode_enabled",
]
