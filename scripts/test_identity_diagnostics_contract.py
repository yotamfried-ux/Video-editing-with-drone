#!/usr/bin/env python3
"""Contract: the run diagnostics explain identity clustering and `identity-split` rows.

Fixture lines are copied from run 39726001357 (24 sources -> 15 persons, three medium-confidence
multi-clip clusters, one verifier split, and the turquoise athlete's `identity-split 2` row whose two
Parts both failed final QA).
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("print_run_diagnostics", ROOT / "scripts" / "print_run_diagnostics.py")
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)

LOG = """\
2026-10-22T05:33:51.1034199Z 🔍 Clustering 24 source(s) by person identity...
2026-10-22T05:35:21.9420106Z ⚠️ Cluster 'Woman on a turquoise longboard, seen in various outfits.' spans 3 clips with confidence=medium — fail-safe checks apply
2026-10-22T05:35:21.9423541Z ⚠️ Cluster 'Man in a white t-shirt and dark shorts on a pink longboard.' spans 2 clips with confidence=medium — fail-safe checks apply
2026-10-22T05:35:21.9424177Z ⚠️ Cluster 'Man on a light blue surfboard, seen both in a wetsuit and shirtless.' spans 2 clips with confidence=medium — fail-safe checks apply
2026-10-22T05:35:38.9074991Z    ✂️  Identity verification split 1 clip(s) out of 'Woman on a turquoise longboard, seen in ' — different athlete detected
2026-10-22T05:36:25.0662487Z 👥 Found 15 unique person(s)
"""

TURQUOISE = "Woman on a turquoise longboard, seen in various outfits."


def _manifest() -> dict:
    def part(i, ok):
        return {"part_index": i, "publishable": ok, "qa_verdict": "PASS" if ok else "FAIL"}

    return {"athletes": [
        {"athlete_label": f"{TURQUOISE} identity-split 1", "parts": [part(1, True)]},
        {"athlete_label": f"{TURQUOISE} identity-split 2", "parts": [part(1, False), part(2, False)]},
        {"athlete_label": "Surfer in a distinctive red hooded top on a light-colored board.", "parts": [part(1, False)]},
    ]}


def _debug(log: str | None, manifest: dict | None) -> Path:
    tmp = Path(tempfile.mkdtemp())
    if log is not None:
        (tmp / "run_tracked.log").write_text(log, encoding="utf-8")
    if manifest is not None:
        (tmp / "publishable_reel_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp


def test_identity_section_reports_clustering_verifier_and_fragments() -> None:
    lines = diag.identity(_debug(LOG, _manifest()))
    text = "\n".join(lines)
    assert "sources clustered=24 -> unique persons=15" in text, text
    assert text.count("medium") == 3, text
    turquoise = next(l for l in lines if l.strip().startswith("Woman on a turquoise longboard, seen in") and "clips" not in l and "split" in l)
    assert "split 1 clip(s) off" in turquoise, turquoise
    assert sum("kept together" in l for l in lines) == 2, text
    assert "athlete rows in the manifest=3; identity-split rows=2 from 1 cluster(s)" in text, text
    assert "rows=2 parts=3 publishable_parts=1" in text, text


def test_identity_section_degrades_gracefully() -> None:
    assert diag.identity(_debug(None, None)) == ["(no identity data in run_tracked.log or publishable_reel_manifest.json)"]
    only_log = diag.identity(_debug(LOG, None))
    assert any("unique persons=15" in l for l in only_log) and not any("athlete rows" in l for l in only_log)
    only_manifest = diag.identity(_debug(None, _manifest()))
    assert any("identity-split rows=2" in l for l in only_manifest)
    assert diag.identity(_debug("garbage", {"athletes": "nope"})) == ["(no identity data in run_tracked.log or publishable_reel_manifest.json)"]


def test_section_is_registered_and_coverage_explains_its_numbers() -> None:
    assert ("Identity clustering", diag.identity) in diag.SECTIONS
    tmp = _debug(None, None)
    (tmp / "athlete_coverage_report.json").write_text(json.dumps({"summary": {"confirmed_athlete_cluster_count": 65}, "athletes": []}))
    first = diag.coverage(tmp)[0]
    assert first.startswith("note: 'clusters'") and "not a count of distinct athletes" in first, first


def main() -> int:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
            print(f"ok  {name}")
    print("Identity diagnostics contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
