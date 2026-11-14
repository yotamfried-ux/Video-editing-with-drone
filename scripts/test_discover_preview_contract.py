#!/usr/bin/env python3
"""Discover shows a preview, never the product; the product is a separate file; athletes are followable.

Checked on the code path delivery uses, with real ffmpeg and a fake Supabase:

1. The preview is a short excerpt (40 %, capped), smaller than the reel, silent, and visibly different from
   the source frame (burned watermark). It is never the whole reel.
2. Publishing stores two objects: the preview (`storage_path`, what Discover streams) and the clean full
   reel (`full_storage_path`, signed only after a verified payment), with both durations on the row.
3. Reels of one athlete in one session share a persistent athlete id; another athlete gets another id.
4. A follower is notified once per new reel of the athlete, also when delivery runs twice.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    raise SystemExit(f"discover preview contract FAILED: {msg}")


class _Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload, self.not_null = db, name, [], "select", None, []
        self.not_ = self

    def select(self, *_a): self.op = "select"; return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def is_(self, key, _value): self.not_null.append(key); return self
    def limit(self, _n): return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "insert":
            if self.name == "athlete_follow_notifications" and any(
                    r["follow_id"] == self.payload["follow_id"] and r["reel_id"] == self.payload["reel_id"] for r in rows):
                raise RuntimeError("duplicate key")
            rows.append({"token": f"tok-{len(rows)}", **self.payload} if self.name == "reels" else dict(self.payload))
            return type("R", (), {"data": [self.payload]})()
        out = [r for r in rows if all(r.get(k) == v for k, v in self.filters)
               and all(r.get(k) is not None for k in self.not_null)]
        return type("R", (), {"data": out})()


class _Bucket:
    def __init__(self, db): self.db = db
    def upload(self, path, handle, file_options=None):
        self.db.objects[path] = len(handle.read())


class _Db:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.objects: dict[str, int] = {}
        self.storage = type("S", (), {"from_": lambda _s, name: _Bucket(self)})()

    def table(self, name): return _Query(self, name)


def _probe(path: str, entries: str) -> list[str]:
    return subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "csv=p=0", path],
                                   text=True).split()


def main() -> int:
    # The repository's own `supabase/` directory (migrations) shadows the client package when it is not
    # installed; the contract never talks to Supabase, so a stub is enough either way.
    import types
    stub = types.ModuleType("supabase")
    stub.create_client = lambda *_a, **_k: None
    stub.Client = object
    sys.modules["supabase"] = stub
    from integrations import supabase_uploader
    from integrations.athlete_follow import notify_athlete_followers
    from pipeline.draft_identity_metadata import athlete_key_of
    from pipeline.stages import editor

    for full, want in ((5.3, 3.0), (8.0, 3.2), (25.0, 10.0), (57.8, 12.0), (200.0, 12.0), (2.0, 1.2)):
        got = editor.preview_seconds(full)
        if abs(got - want) > 0.01 or got >= full:
            fail(f"a {full}s reel previews {want}s, never the whole reel: got {got}")

    with tempfile.TemporaryDirectory(prefix="preview-contract-") as tmp:
        reel = str(Path(tmp) / "DRAFT_surfer_20261114.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=25",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=25", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", reel], check=True)
        preview = editor.create_preview(reel, athlete_label="Surfer #7")
        duration = editor.probe_duration(preview)
        if not 9.8 <= duration <= 10.2:
            fail(f"the preview of a 25 s reel is 10 s, got {duration:.2f}")
        streams = _probe(preview, "stream=codec_type")
        if streams != ["video"]:
            fail(f"the preview is silent video only, got {streams}")
        width, height = (int(v) for v in _probe(preview, "stream=width,height")[0].split(","))
        if (width, height) != (720, 1280):
            fail(f"the preview is scaled down to 720 wide, got {width}x{height}")
        if Path(preview).stat().st_size >= Path(reel).stat().st_size:
            fail("the preview must be smaller than the reel")
        # Watermark: the same second differs clearly from the plainly scaled source.
        psnr = subprocess.run(
            ["ffmpeg", "-v", "info", "-t", "3", "-i", preview, "-t", "3", "-i", reel, "-filter_complex",
             "[1:v]scale=720:-2:flags=lanczos[ref];[0:v][ref]psnr", "-f", "null", "-"],
            capture_output=True, text=True).stderr
        average = float(psnr.split("average:")[1].split()[0])
        if average > 30:
            fail(f"the preview frame must carry a visible watermark (PSNR against the clean frame {average:.1f} dB)")

        db = _Db()
        supabase_uploader._supabase = lambda: db
        meta = {"sport": "surfing", "description": "Surfer in a red rash guard"}

        def publish(name: str, key: str | None) -> dict:
            reel_id = supabase_uploader.publish_reel_approved(
                preview_path=preview, draft_name=name, drive_file_id=f"approved/{name}", reel_meta=meta,
                full_path=reel, preview_duration=round(duration, 2), full_duration=25.0, athlete_key=key)
            return next(r for r in db.tables["reels"] if r["id"] == reel_id)

        first = publish("DRAFT_surfer_20261114.mp4", "ath_aaa")
        if first["recording_date"] != "2026-11-14":
            fail(f"the recording date comes from the draft name: {first['recording_date']}")
        if not first["storage_path"].endswith("_preview.mp4") or not first["full_storage_path"].endswith("_full.mp4"):
            fail(f"preview and full reel are separate objects: {first['storage_path']} / {first['full_storage_path']}")
        if db.objects[first["storage_path"]] >= db.objects[first["full_storage_path"]]:
            fail("Discover's object is the small preview, the paid object is the full reel")
        if (first["preview_duration_sec"], first["full_duration_sec"]) != (round(duration, 2), 25.0):
            fail("both durations are stored so the app can say 'preview X s of Y s'")
        second = publish("DRAFT_surfer (part 2)_20261114.mp4", "ath_aaa")
        other = publish("DRAFT_other_20261114.mp4", "ath_bbb")
        unknown = publish("DRAFT_mixed_20261114.mp4", None)
        if not first["athlete_id"] or first["athlete_id"] != second["athlete_id"]:
            fail("two reels of one athlete in one session share the persistent athlete id")
        if other["athlete_id"] == first["athlete_id"] or unknown["athlete_id"] is not None:
            fail("another athlete gets another id; an unknown or mixed reel gets none")
        if len(db.tables["athletes"]) != 2:
            fail(f"one athlete row per athlete: {db.tables['athletes']}")

        db.tables["athlete_follows"] = [{"id": "f1", "user_id": "u1", "athlete_id": first["athlete_id"]}]
        db.tables["push_tokens"] = [{"user_id": "u1", "token": "ExponentPushToken[x]"}]
        sent: list[list[dict]] = []
        if notify_athlete_followers(db, second["id"], second["athlete_id"], send=sent.append) != 1:
            fail("the follower is told about the athlete's new reel")
        if notify_athlete_followers(db, second["id"], second["athlete_id"], send=sent.append) != 0 or len(sent) != 1:
            fail("a second delivery of the same reel does not notify again")
        if sent[0][0]["to"] != "ExponentPushToken[x]" or sent[0][0]["data"]["token"] != second["token"]:
            fail(f"the push opens the new reel: {sent[0]}")
        if notify_athlete_followers(db, other["id"], other["athlete_id"], send=sent.append) != 0:
            fail("followers of one athlete are not told about another athlete")

    if athlete_key_of([{"athlete_id": "ath_1"}, {"athlete_id": "ath_1"}]) != "ath_1":
        fail("a reel of one athlete carries that athlete's key")
    if athlete_key_of([{"athlete_id": "ath_1"}, {"athlete_id": "ath_2"}]) is not None or athlete_key_of([]) is not None:
        fail("a mixed or unknown reel carries no athlete key")
    print("discover preview contract ok (25 s reel -> 10 s 720p watermarked preview; full reel stored separately)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
