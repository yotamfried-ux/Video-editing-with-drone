"""
pipeline/text_utils.py — small text helpers shared across pipeline stages.

Import-light (stdlib only) so it is unit-testable without the Gemini / CLIP stack.
"""

import re

_NON_ALNUM = re.compile(r"[^a-z0-9 ]")
_WS = re.compile(r"\s+")


def normalize_description(d: str) -> str:
    """Canonicalize an athlete description for use as a merge key.

    Lowercase, strip punctuation, collapse whitespace. Using the FULL normalized
    string (not a truncated prefix) avoids false merges of different athletes that
    share a long common prefix — the previous `description.lower()[:40]` key in
    analyzer._merge_session_results could collide e.g.
    "surfer in black wetsuit on a white board" vs
    "surfer in black wetsuit on a yellow board".
    """
    if not d:
        return ""
    s = _NON_ALNUM.sub(" ", d.lower())
    return _WS.sub(" ", s).strip()
