"""
pipeline/identity.py — Cross-clip identity clustering.
Groups persons from multiple short clips into unified athlete clusters using Gemini.
"""

import json
import logging
import re

import google.generativeai as genai

import config

logger = logging.getLogger(__name__)

_CLUSTER_PROMPT_TEMPLATE = """\
Here are visual descriptions of people detected across {n} video clip(s).
Group descriptions that likely refer to the same person.

Input:
{descriptions_json}

Rules:
- Match by distinctive features: jersey number, board color, clothing.
- When uncertain, create separate clusters (avoid false merges).
- A person appearing in only one clip still gets their own cluster.

Return ONLY valid JSON, no markdown:
{{
  "clusters": [
    {{
      "description": "brief description of this person",
      "appearances": [
        {{"clip_index": 0, "person_id": "person_A"}},
        {{"clip_index": 2, "person_id": "person_A"}}
      ]
    }}
  ]
}}
"""


def cluster_clips(clip_analyses: list[dict]) -> list[dict]:
    """
    Groups persons from multiple short clips by identity.

    Args:
        clip_analyses: list of {"path": str, "analysis": {"activity": str, "persons": [...]}}

    Returns:
        list of {"description": str, "appearances": [{"path": str, "events": [...]}]}
    """
    if not clip_analyses:
        return []

    # Single clip — return directly without a Gemini clustering call
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

    # Multiple clips — ask Gemini to cluster by visual similarity
    descriptions = []
    for i, ca in enumerate(clip_analyses):
        for p in ca.get("analysis", {}).get("persons", []):
            descriptions.append({
                "clip_index":  i,
                "person_id":   p["id"],
                "description": p["description"],
            })

    if not descriptions:
        return []

    try:
        prompt = _CLUSTER_PROMPT_TEMPLATE.format(
            n=len(clip_analyses),
            descriptions_json=json.dumps(descriptions, indent=2),
        )
        model    = genai.GenerativeModel(model_name=config.GEMINI_MODEL)
        response = model.generate_content(prompt, request_options={"timeout": 120})
        raw      = response.text.strip()
        raw      = re.sub(r"^```(?:json)?\s*", "", raw)
        raw      = re.sub(r"\s*```$", "", raw)
        data     = json.loads(raw)

        result: list[dict] = []
        for cluster in data.get("clusters", []):
            appearances: list[dict] = []
            for app in cluster.get("appearances", []):
                idx = app.get("clip_index", -1)
                pid = app.get("person_id", "")
                if not (0 <= idx < len(clip_analyses)):
                    continue
                ca      = clip_analyses[idx]
                persons = ca.get("analysis", {}).get("persons", [])
                person  = next((p for p in persons if p["id"] == pid), None)
                if person and person.get("events"):
                    appearances.append({"path": ca["path"], "events": person["events"]})
            if appearances:
                result.append({
                    "description": cluster.get("description", "unknown athlete"),
                    "appearances": appearances,
                })
        return result

    except Exception as e:
        logger.error("Identity clustering failed, falling back to per-clip: %s", e)
        # Fallback: each person in each clip becomes their own cluster
        result = []
        for ca in clip_analyses:
            for p in ca.get("analysis", {}).get("persons", []):
                if p.get("events"):
                    result.append({
                        "description": p["description"],
                        "appearances": [{"path": ca["path"], "events": p["events"]}],
                    })
        return result
