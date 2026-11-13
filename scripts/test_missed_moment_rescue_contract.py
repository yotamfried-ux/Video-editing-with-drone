#!/usr/bin/env python3
"""People who moved through a clip but got no event get a second look; unusual moments count.

Run 43013005072, 0094: a father and child rode one longboard together for 20 s (in the manual catalog). The
analyzer listed them as two people ("light blue top", "yellow top", same turquoise longboard) with
`no_complete_action`, because its contract scores one athlete's technique. The coverage report flagged the track
(13.8-36.6 s, 38% inside kept rides) and nothing acted on it.

1. A long, moving, uncovered window is cut and shown to a model that is told who is already covered and asked
   for moments by anyone else, unusual ones included. A confirmed moment becomes a new person with one event bound
   to that track, through the production hardening step (bootstrap order), with its identity contact sheet.
2. The answer is cached per source and window: a second run makes no call.
3. Covered athletes are not added twice (the model is told, and the answer is checked against them); a low score,
   no moment, short or still windows add nothing; the call budget is respected.
4. The analysis prompt is untouched.

No network: Gemini is a fake module. Real ffmpeg for the source and the cut.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CALLS: list[dict] = []
ANSWER: dict = {}


def fail(msg: str) -> None:
    raise SystemExit(f"missed-moment rescue contract FAILED: {msg}")


def _install_fake_gemini() -> None:
    fake = types.ModuleType("integrations.gemini")

    class _File:
        def __init__(self, path):
            self.name = os.path.basename(path)
            self.path = path

    class _Model:
        def __init__(self, model_name):
            self.model_name = model_name

        def generate_content(self, contents, request_options=None):
            clip = contents[0].path
            duration = float(subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", clip], text=True))
            CALLS.append({"model": self.model_name, "prompt": contents[-1], "clip_duration": duration})
            return types.SimpleNamespace(text=json.dumps(ANSWER))

    fake.genai = types.SimpleNamespace(GenerativeModel=_Model, upload_file=lambda path, mime_type=None: _File(path),
                                       delete_file=lambda name: None)
    fake.upload_video = lambda path: _File(path)
    fake.delete_video = lambda item: None
    sys.modules["integrations.gemini"] = fake


def _source(path: str, seconds: float) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path], check=True)


def main() -> int:
    global ANSWER
    tmp = tempfile.mkdtemp(prefix="missed-moment-")
    os.environ["TMP_DIR"] = tmp
    os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, "llm-cache")
    os.environ["SPORTREEL_MISSED_MOMENT_MAX_CALLS"] = "20"
    _install_fake_gemini()
    import config
    config.TMP_DIR = tmp

    from pipeline import missed_moment_rescue as rescue
    from pipeline import performance_reel_policy, runtime_quality as rq
    from pipeline.perception.schema import PerceptionDetection

    analyzer_src = (ROOT / "pipeline" / "stages" / "analyzer.py").read_text(encoding="utf-8")
    if "tandem" in analyzer_src.lower() or "missed-moment" in analyzer_src:
        fail("the analysis prompt must stay unchanged (its cache would be invalidated)")

    video = os.path.join(tmp, "DJI_20260720160337_0094_D.MP4")
    _source(video, 37.0)

    def det(track, t, x):
        return PerceptionDetection(source_video=video, frame_index=int(t * 30), time_sec=t, xyxy=(x, 300, x + 60, 400),
                                   frame_width=1280, frame_height=720, confidence=0.9, class_id=0, class_name="person",
                                   tracker_id=track)

    detections = [det(1, 3.5 + 0.5 * i, 100 + 25 * i) for i in range(0, 20)]        # athlete A, 3.5-13 s (kept)
    detections += [det(162, 13.8 + 0.5 * i, 1100 - 25 * i) for i in range(0, 46)]   # tandem, 13.8-36.3 s
    rq._load_detections = lambda _path: detections
    rq.install()
    performance_reel_policy.install()

    result = {"activity": "surfing", "persons": [
        {"id": "person_A", "description": "surfer with long dark hair in a black tank top on a white longboard",
         "events": [{"type": "wave_catch", "description": "rides the wave", "start": 3.5, "end": 12.5, "score": 9,
                     "target_track_id": "1", "crop_x": 0.3, "crop_y": 0.5}]},
        {"id": "person_B", "description": "surfer in a light blue top on a turquoise longboard", "events": [],
         "no_output_reason": "no_complete_action"},
        {"id": "person_C", "description": "surfer in a yellow top on a turquoise longboard", "events": [],
         "no_output_reason": "no_complete_action"}]}

    ANSWER = {"moment": True, "kind": "tandem_ride", "start": 3.5, "end": 23.0, "people": 2,
              "description": "adult in a light blue top and a child in a yellow top riding tandem on a turquoise longboard",
              "score": 9, "reason": "a father and child ride one board together the whole wave",
              "start_evidence": "both stand up together on the board", "end_evidence": "both step off as the wave dies"}
    hardened = rq._harden_session_result(video, result)
    rescued = [p for p in hardened["persons"] if p.get("rescued_by")]
    if len(rescued) != 1:
        fail(f"the uncovered tandem ride must become one new person, got {[p.get('id') for p in hardened['persons']]}")
    event = rescued[0]["events"][0]
    if event.get("target_track_id") != "162" or event.get("type") != "wave_catch":
        fail(f"the moment is a surf event bound to the uncovered track: {event}")
    if not (16.0 <= event["start"] <= 16.6 and 35.5 <= event["end"] <= 36.1):  # window 12.8 s + 3.5 / + 23.0
        fail(f"the model's clip-relative times must map back to the source: {event['start']}-{event['end']}")
    if (rescued[0].get("identity_evidence") or {}).get("kind") != "track_bbox_sheet":
        fail(f"the rescued person gets the same tracked contact sheet as everyone else: {rescued[0].get('identity_evidence')}")
    # Run 43031447052 crashed in the cut step: a rescued event had a target track but no tracker evidence.
    if event.get("perception_evidence_status") != "tracker_sidecar" or str(event.get("track_id")) != "162":
        fail(f"the rescued event must carry the same tracker evidence as every analyzer event: {event.get('perception_evidence_status')}")
    if not event.get("bbox_xyxy") or "162" not in (event.get("visible_track_ids") or []):
        fail("the framing step must see the rescued track's box and everyone else visible in the window")
    from pipeline.quality_preserving_framing import decide_framing
    try:
        decide_framing(event, sport="surfing")
    except RuntimeError as exc:
        fail(f"framing must accept a rescued event: {exc}")
    # Run 43079298706: the publishable gate needs person lineage on every selected window; the rescued tandem ride
    # had none (lineage 0.958). Identity clustering adds athlete_id later; the rest must already be there.
    if event.get("person_id") != "rescued_track_162" or event.get("source_video") != os.path.basename(video):
        fail(f"the rescued event carries its person lineage: person_id={event.get('person_id')} "
             f"source_video={event.get('source_video')}")
    from pipeline.draft_identity_metadata import enrich_metadata_entry
    lineage = enrich_metadata_entry({"draft_name": "DRAFT_tandem"}, [{**event, "athlete_id": "ath_test"}])
    if lineage["identity_lineage_status"] != "complete" or lineage["person_id"] != "rescued_track_162":
        fail(f"a draft of the rescued event must have complete identity lineage: {lineage['identity_lineage_status']}")
    # Run 43203677423: the tandem ride had no timing contract, so its single-fragment ride end counted as inferred
    # and the reel was blocked (RIDE_BOUNDARY_UNCERTAIN). Boundary evidence from the model makes it exact.
    from pipeline.surf_ride_segment import normalize_surf_rides

    def boundary_defects(ev):
        return [d["type"] for r in normalize_surf_rides([dict(ev)], "surfing") for d in r.get("ride_qa_defects", [])]

    if event.get("timing_precise") is not True or "both step off" not in str(event.get("timing_evidence")):
        fail(f"named boundaries give the rescued event the analyzer's timing contract: {event.get('timing_evidence')}")
    if "RIDE_BOUNDARY_UNCERTAIN" in boundary_defects(event):
        fail("a rescued ride with named boundaries is not an inferred ride end")
    vague = {k: v for k, v in event.items() if k not in {"timing_precise", "outcome_end", "ride_end_evidence"}}
    if "RIDE_BOUNDARY_UNCERTAIN" not in boundary_defects(vague):
        fail("without boundary evidence the end stays uncertain (the QA gate still asks for review)")
    at_end = rescue._timing_contract({}, 27.8, 36.9, recording_end=True)
    if at_end.get("outcome_end") != 36.9 or "RIDE_BOUNDARY_UNCERTAIN" in boundary_defects({**vague, **at_end}):
        fail(f"a moment that runs into the end of the recording ends there, observed: {at_end}")
    if rescue._timing_contract({"start_evidence": "stands"}, 1.0, 5.0, recording_end=False):
        fail("one named boundary is not enough for exact timing")
    if "tandem" not in rescued[0]["description"]:
        fail("the description carries 'tandem' so identity treats the pair as one subject, never as a solo surfer")
    if len(CALLS) != 1 or CALLS[0]["model"] != "gemini-2.5-flash":
        fail(f"one cheap model call for one window: {CALLS}")
    prompt = CALLS[0]["prompt"]
    for needle in ("black tank top on a white longboard", "3.5-12.5s", "light blue top", "two people riding one board",
                   "skill is NOT required"):
        if needle not in prompt:
            fail(f"the model must be told who is covered, who was noticed and what counts ({needle!r})")
    if not 23.0 <= CALLS[0]["clip_duration"] <= 25.0:
        fail(f"the model sees only the uncovered window plus a little padding: {CALLS[0]['clip_duration']:.1f}s")
    registry = {r["person_id"]: r for r in hardened.get("detected_athlete_registry", [])}
    if registry.get("rescued_track_162", {}).get("retained_action_count") != 1:
        fail("the accountability registry lists the rescued person and its event")

    # Cached: the same source and window make no second call.
    rq._harden_session_result(video, result)
    if len(CALLS) != 1:
        fail("the answer is cached per source and window")

    # Rejections.
    people = [p for p in result["persons"]]
    cand = [{"track_id": "162", "start": 13.8, "end": 36.3, "span": 22.5, "travel_frames": 0.9, "covered": 0.0}]
    os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, "cache-2")
    for answer, why in (
        ({**ANSWER, "score": 4}, "a low score"),
        ({**ANSWER, "moment": False}, "no moment"),
        ({**ANSWER, "end": 4.5}, "a 1-second moment"),
        ({**ANSWER, "description": "surfer with long dark hair in a black tank top on a white longboard"}, "the covered athlete again"),
        ({**ANSWER, "kind": "ride", "description": "surfer in a black sleeveless top on a white longboard"},
         "an ordinary ride the analyzer already rejected (0155: a catalogued failed take-off)"),
    ):
        ANSWER = answer
        os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, f"cache-{len(CALLS)}")
        if rescue.rescue_missed_moments(video, people, cand, detections, "surfing"):
            fail(f"{why} must add nothing")

    os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, "cache-kept-track")
    before = len(CALLS)
    kept_track = [{"id": "person_A", "description": "x", "events": [{"start": 0.0, "end": 9.0, "target_track_id": "162"}]}]
    if rescue.rescue_missed_moments(video, kept_track, cand, detections, "surfing") or len(CALLS) != before:
        fail("a window on a track a kept highlight already follows is the same person: no call, nothing added")
    no_dets = [d for d in detections if str(d.tracker_id) != "162"]
    ANSWER = {"moment": True, "kind": "tandem_ride", "start": 3.5, "end": 23.0, "people": 2,
              "description": "adult and child riding tandem on a turquoise longboard", "score": 9, "reason": "tandem"}
    os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, "cache-no-dets")
    if rescue.rescue_missed_moments(video, people, cand, no_dets, "surfing"):
        fail("a moment whose track has no detections cannot be framed and must not be added")

    # Run 43303438106, 0094: the model ended the tandem ride at 33.8 s; track 162 was tracked, moving, to 36.6 s of a
    # 36.7 s file; the catalog ride ends at 36.7 s and final QA reported PREMATURE_CUT at the reel's end. The end of a
    # ride the tracker still follows to the end of the recording is the recording's. Lost, still or long tails are not.
    video2 = os.path.join(tmp, "DJI_20260720160337_0094_D_end.MP4")
    _source(video2, 36.7)
    cand2 = [{"track_id": "162", "start": 13.8, "end": 36.6, "span": 22.8, "travel_frames": 0.99, "covered": 0.38}]
    ANSWER = {"moment": True, "kind": "tandem_ride", "start": 13.0, "end": 21.0, "people": 2,
              "description": "adult in a pink top and child in a yellow top riding tandem on a lime green surfboard",
              "score": 9, "reason": "tandem", "start_evidence": "both stand up", "end_evidence": "still riding"}

    def run_end_case(name, track):
        os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, f"cache-end-{name}")
        found = rescue.rescue_missed_moments(video2, people, cand2, track, "surfing")
        return found[0]["events"][0] if found else None

    moving = [det(162, 13.8 + 0.2 * i, 1100 - 8 * i) for i in range(0, 115)]  # 13.8-36.6 s, travelling
    ev = run_end_case("moving", moving)
    if ev is None or not 36.5 <= ev["end"] <= 36.7 or ev.get("end_before_track_extension") != 33.8:
        fail(f"a ride the tracker follows to the end of the recording ends there: {ev and (ev['start'], ev['end'])}")
    if ev.get("outcome_end") != ev["end"] or ev.get("ride_end_evidence") != "recording_end":
        fail(f"the extended end is an observed recording end: {ev.get('outcome_end')} {ev.get('ride_end_evidence')}")
    lost = [d for d in moving if d.time_sec <= 34.0]  # tracked until 34.0 s: no claim about the rest
    ev = run_end_case("lost", lost)
    if ev is None or ev["end"] > 34.1 or "end_before_track_extension" in ev:
        fail(f"a track lost before the recording's end does not move the end: {ev and ev['end']}")
    still = [d for d in moving if d.time_sec <= 33.8] + [
        det(162, 33.8 + 0.2 * i, 300) for i in range(1, 15)]  # standing in the shallows to the end
    ev = run_end_case("still", still)
    if ev is None or "end_before_track_extension" in ev:
        fail("a track that stopped moving after the model's end is not the ride continuing")
    ANSWER = {**ANSWER, "end": 15.0}  # model end 27.8 s: 8.9 s of track left, more than a ride's tail
    ev = run_end_case("long-tail", moving)
    if ev is None or "end_before_track_extension" in ev:
        fail("a long tail after the model's end is not claimed")

    windows = rescue.select_windows([
        {"track_id": "a", "start": 0.0, "end": 8.8, "span": 8.8, "travel_frames": 0.83, "covered": 0.27},
        {"track_id": "b", "start": 1.0, "end": 7.5, "span": 6.5, "travel_frames": 0.91, "covered": 0.16},
        {"track_id": "c", "start": 20.0, "end": 24.2, "span": 4.2, "travel_frames": 0.9, "covered": 0.0},
        {"track_id": "d", "start": 30.0, "end": 40.0, "span": 10.0, "travel_frames": 0.2, "covered": 0.0},
        {"track_id": "e", "start": 50.0, "end": 60.0, "span": 10.0, "travel_frames": 0.9, "covered": 0.5}])
    if [w["track_id"] for w in windows] != ["a"]:
        fail(f"overlapping tracks are one window; short, still or mostly covered tracks are none: {windows}")

    before = len(CALLS)
    os.environ["SPORTREEL_MISSED_MOMENT_MAX_CALLS"] = str(rescue._calls_made)
    os.environ["LLM_CACHE_DIR"] = os.path.join(tmp, "cache-budget")
    rescue.rescue_missed_moments(video, people, cand, detections, "surfing")
    if len(CALLS) != before:
        fail("the per-run call budget is respected")

    print("missed-moment rescue contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
