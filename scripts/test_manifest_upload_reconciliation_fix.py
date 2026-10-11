#!/usr/bin/env python3
"""Fail-closed manifest upload path reconciliation simulation."""
import json
from pipeline.publishable_reel_policy import _find_upload_part

def row(name, path, aliases=()):
    return {"athlete_label": name, "parts": [
        {"local_path": path, "upload_path_aliases": list(aliases)}]}

single = {"athletes": [row("A", "/tmp/a/final.mp4")]}
assert _find_upload_part(single, "/tmp/a/final.mp4")[0]["athlete_label"] == "A"
assert _find_upload_part(single, "/new/location/final.mp4")[0]["athlete_label"] == "A"
ambiguous_exact = {"athletes": [row("A", "/tmp/a/final.mp4"),
                                 row("B", "/tmp/b/other.mp4", ["/tmp/a/final.mp4"])]}
assert _find_upload_part(ambiguous_exact, "/tmp/a/final.mp4") is None
ambiguous_basename = {"athletes": [row("A", "/tmp/a/final.mp4"),
                                    row("B", "/tmp/b/final.mp4")]}
assert _find_upload_part(ambiguous_basename, "/tmp/c/final.mp4") is None
print(json.dumps({"scope": "isolated manifest upload reconciliation",
                  "unique_exact_match": "allowed",
                  "unique_basename_match": "allowed",
                  "ambiguous_exact_before": "first athlete selected",
                  "ambiguous_exact_after": "blocked",
                  "ambiguous_basename": "blocked"}, indent=2))
