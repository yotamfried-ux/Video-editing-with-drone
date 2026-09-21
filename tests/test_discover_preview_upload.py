from pathlib import Path
import sys
import types

from integrations import supabase_uploader


class _Result:
    data = []


class _Bucket:
    def __init__(self):
        self.uploads = []

    def upload(self, path, file, file_options=None):
        self.uploads.append((path, file.read(), file_options))
        return _Result()


class _Storage:
    def __init__(self, bucket):
        self.bucket = bucket

    def from_(self, name):
        assert name == "reels"
        return self.bucket


class _Table:
    def __init__(self):
        self.rows = []

    def insert(self, row):
        self.rows.append(row)
        return self

    def execute(self):
        return _Result()


class _Supabase:
    def __init__(self):
        self.bucket = _Bucket()
        self.storage = _Storage(self.bucket)
        self.reels = _Table()

    def table(self, name):
        assert name == "reels"
        return self.reels


def test_approved_preview_upload_uses_video_mp4_mime(monkeypatch, tmp_path):
    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"valid-video-fixture-placeholder")
    fake = _Supabase()
    monkeypatch.setattr(supabase_uploader, "_supabase", lambda: fake)

    stream = types.ModuleType("integrations.cloudflare_stream")
    def unexpected_stream_upload(path):
        raise AssertionError("approved Discover preview must not upload to Cloudflare Stream")
    stream.upload_to_stream = unexpected_stream_upload
    monkeypatch.setitem(sys.modules, "integrations.cloudflare_stream", stream)

    reel_id = supabase_uploader.publish_reel_approved(
        preview_path=str(preview),
        draft_name="APP_DLV_01_2026-09-20.mp4",
        drive_file_id="approved/APP_DLV_01_2026-09-20.mp4",
        reel_meta={"sport": "unknown"},
    )

    assert reel_id
    assert len(fake.bucket.uploads) == 1
    path, body, options = fake.bucket.uploads[0]
    assert path.endswith("_preview.mp4")
    assert body
    assert options == {"content-type": "video/mp4"}
    assert len(fake.reels.rows) == 1
    assert fake.reels.rows[0]["stream_uid"] is None
    # Production reels.token is UUID with a database default. Approved publication
    # must not provide token_urlsafe() text, which PostgreSQL rejects as 22P02.
    assert "token" not in fake.reels.rows[0]
