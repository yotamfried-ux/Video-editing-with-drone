"""A2: preflight checks — required failures abort, optional ones warn."""

import pytest

import pipeline.preflight as preflight


def test_ffmpeg_check_detects_missing(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    name, ok, detail = preflight._check_ffmpeg()
    assert ok is False and "ffmpeg" in detail


def test_ffmpeg_check_passes_when_present(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/usr/bin/{name}")
    _, ok, _ = preflight._check_ffmpeg()
    assert ok is True


def test_run_preflight_raises_on_required_failure(monkeypatch):
    # Force the ffmpeg required-check to fail; others stubbed ok.
    monkeypatch.setattr(preflight, "_check_ffmpeg",
                        lambda: ("ffmpeg/ffprobe on PATH", False, "missing"))
    monkeypatch.setattr(preflight, "_check_gemini_key",
                        lambda: ("GEMINI_API_KEY set", True, ""))
    monkeypatch.setattr(preflight, "_check_drive",
                        lambda: ("Google Drive reachable", True, ""))
    monkeypatch.setattr(preflight, "_check_disk",
                        lambda: ("disk", True, ""))
    monkeypatch.setattr(preflight, "_REQUIRED",
                        [preflight._check_ffmpeg, preflight._check_gemini_key,
                         preflight._check_drive, preflight._check_disk])
    with pytest.raises(RuntimeError, match="Preflight failed"):
        preflight.run_preflight_checks()


def test_run_preflight_passes_when_all_required_ok(monkeypatch):
    for fn_name in ("_check_ffmpeg", "_check_gemini_key", "_check_drive", "_check_disk"):
        monkeypatch.setattr(preflight, fn_name, lambda n=fn_name: (n, True, ""))
    monkeypatch.setattr(preflight, "_REQUIRED",
                        [getattr(preflight, n) for n in
                         ("_check_ffmpeg", "_check_gemini_key", "_check_drive", "_check_disk")])
    monkeypatch.setattr(preflight, "_OPTIONAL", [])
    preflight.run_preflight_checks()  # must not raise
