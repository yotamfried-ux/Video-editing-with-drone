"""E3: the analysis proxy ffmpeg command is built from config (crf/preset/width)."""

import json
import types

import config
import pipeline.stages.analyzer as analyzer


class _FakeProbe:
    def __init__(self, width):
        self.stdout = json.dumps({"streams": [{"width": width}]})


def test_proxy_command_uses_config(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        # First call is ffprobe (returns width), second is the ffmpeg encode.
        if cmd[0] == "ffprobe":
            return _FakeProbe(width=3840)
        captured["cmd"] = cmd
        # Pretend the proxy file now exists with some size.
        out = cmd[-1]
        with open(out, "wb") as f:
            f.write(b"x" * 2048)
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
    monkeypatch.setattr(config, "TMP_DIR", str(tmp_path))

    src = tmp_path / "drone_4k.mp4"
    src.write_bytes(b"0")
    out = analyzer._make_proxy(str(src))

    assert out is not None
    cmd = captured["cmd"]
    assert "-crf" in cmd and cmd[cmd.index("-crf") + 1] == str(config.PROXY_CRF)
    assert "-preset" in cmd and cmd[cmd.index("-preset") + 1] == config.PROXY_PRESET
    assert f"scale={config.PROXY_MAX_WIDTH}:-2" in cmd
    # Default config should be the higher-fidelity values, not the old 28/veryfast/1280.
    assert config.PROXY_CRF == 23
    assert config.PROXY_MAX_WIDTH == 1600


def test_proxy_skipped_when_source_small(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "ffprobe"  # ffmpeg must never run for a small source
        return _FakeProbe(width=640)

    monkeypatch.setattr(analyzer.subprocess, "run", fake_run)
    monkeypatch.setattr(config, "TMP_DIR", str(tmp_path))
    assert analyzer._make_proxy(str(tmp_path / "small.mp4")) is None
