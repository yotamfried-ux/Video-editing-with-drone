"""Bundle B: QA errors surface as UNKNOWN (observable) without dropping content."""

import pipeline.stages.analyzer as analyzer


def test_clip_qa_returns_unknown_on_error(monkeypatch, tmp_path):
    # ffprobe duration lookup
    monkeypatch.setattr(analyzer.subprocess, "check_output", lambda *a, **k: "5.0")
    # a real thumbnail file so the size/dedupe logic runs
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"x" * 100)
    monkeypatch.setattr(analyzer, "_extract_thumbnail", lambda *a, **k: str(thumb))

    # Gemini upload blows up → must be UNKNOWN, not a silent PASS
    def boom(*a, **k):
        raise RuntimeError("503 unavailable")
    monkeypatch.setattr(analyzer.genai, "upload_file", boom, raising=False)

    assert analyzer._qa_check_clip("clip.mp4", {"start": 0, "end": 5}) == "UNKNOWN"


def test_reel_qa_error_marks_unknown_and_persists(monkeypatch):
    monkeypatch.setattr(analyzer, "_check_technical_compliance",
                        lambda p: ({"aspect": 0.5625, "width": 1080, "height": 1920,
                                    "duration": 30, "has_audio": True}, True, []))

    def boom(*a, **k):
        raise RuntimeError("deadline exceeded")
    monkeypatch.setattr(analyzer, "_upload_video", boom)

    persisted = {}
    monkeypatch.setattr(analyzer, "_persist_qa_result",
                        lambda result, reel, sport: persisted.update(result))

    out = analyzer.qa_check_reel("reel.mp4", sport="surfing")
    assert out["verdict"] == "UNKNOWN"
    assert out["qa_error"] is True
    # non-blocking invariant: a non-FAIL verdict must not be gated
    assert out["verdict"] != "FAIL"
    # the error case is now persisted (was previously skipped)
    assert persisted.get("verdict") == "UNKNOWN"
