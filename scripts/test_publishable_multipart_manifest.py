#!/usr/bin/env python3
"""Regression: multiple batches for one athlete must not overwrite earlier parts."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import publishable_reel_policy as policy

SPECS = {"duration": 20, "width": 1080, "height": 1920,
         "aspect": 9 / 16, "has_audio": True}


def record(path: str, event_id: str) -> dict:
    return policy.record_athlete_outcome(
        sport="surfing", athlete_label="surfer A", final_reels=[path],
        events_by_reel={path: [{"athlete_id": "athlete-1", "event_id": event_id,
                                "start": 0 if event_id == "wave-1" else 5, "end": 4 if event_id == "wave-1" else 9, "source_video": "fixture.mp4"}]},
        flagged_paths=set(), specs_by_path={path: SPECS},
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(Path(directory) / "manifest.json")
        policy.reset_manifest()
        first = record("/tmp/fixture_A_part1.mp4", "wave-1")
        assert len(first["parts"]) == 1
        second = record("/tmp/fixture_A_part2.mp4", "wave-2")
        assert len(second["parts"]) == 2, second
        assert [part["part_index"] for part in second["parts"]] == [1, 2]
        payload = json.loads(Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"]).read_text())
        assert len(payload["athletes"]) == 1, payload
        assert payload["summary"]["eligible_athlete_count"] == 1, payload
        assert len(payload["athletes"][0]["parts"]) == 2, payload
        assert payload["athletes"][0]["action_count"] == 2, payload

        # Re-processing a part must not duplicate it or drop the other part.
        third = record("/tmp/fixture_A_part2.mp4", "wave-2")
        assert len(third["parts"]) == 2, third
        assert third["action_count"] == 2, third
        assert len({p["local_path"] for p in third["parts"]}) == 2, third

        # Another athlete must stay a separate manifest row.
        other = policy.record_athlete_outcome(
            sport="surfing", athlete_label="surfer B",
            final_reels=["/tmp/fixture_B_part1.mp4"],
            events_by_reel={"/tmp/fixture_B_part1.mp4": [
                {"athlete_id": "athlete-2", "event_id": "wave-3",
                 "start": 0, "end": 4, "source_video": "fixture.mp4"}]},
            flagged_paths=set(), specs_by_path={"/tmp/fixture_B_part1.mp4": SPECS},
        )
        assert other["athlete_key"] != third["athlete_key"]
        payload = json.loads(Path(os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"]).read_text())
        assert len(payload["athletes"]) == 2, payload
        assert payload["summary"]["eligible_athlete_count"] == 2, payload
        print("PASS: multi-part append, idempotent update, lineage, separate athlete")


if __name__ == "__main__":
    main()
