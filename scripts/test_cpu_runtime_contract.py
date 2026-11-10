#!/usr/bin/env python3
"""Contract: OpenVINO CPU runtime is used only as a cached conversion of the verified .pt weights, and every
failure falls back to the PyTorch weights (perception must never be blocked by the optimisation)."""
from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fail(msg: str) -> None:
    raise SystemExit(f"cpu runtime contract FAILED: {msg}")


def main() -> None:
    from pipeline.perception import cpu_runtime as rt

    with tempfile.TemporaryDirectory(prefix="sportreel-ov-") as tmp:
        weights = Path(tmp, "yolo11n.pt")
        weights.write_bytes(b"verified-weights")
        os.environ["SPORTREEL_OPENVINO_CACHE"] = str(Path(tmp, "cache"))
        exports: list[str] = []

        class FakeYOLO:
            def __init__(self, path: str) -> None:
                self.path = path

            def export(self, **kwargs):
                if kwargs.get("format") != "openvino" or kwargs.get("half") is not False:
                    raise AssertionError(f"export must be a full-precision OpenVINO conversion: {kwargs}")
                exports.append(self.path)
                out = Path(self.path).with_name(Path(self.path).stem + "_openvino_model")
                out.mkdir()
                (out / "metadata.yaml").write_text("ok")
                return str(out)

        sys.modules["openvino"] = types.ModuleType("openvino")
        sys.modules["ultralytics"] = types.SimpleNamespace(YOLO=FakeYOLO)

        path, runtime = rt.resolve_model(str(weights))
        if runtime != "openvino" or not Path(path, "metadata.yaml").exists():
            fail(f"expected an OpenVINO export, got {runtime} {path}")
        if rt.resolve_model(str(weights)) != (path, "openvino") or len(exports) != 1:
            fail("the export must be made once and reused from the cache")
        weights.write_bytes(b"different-weights")
        path2, _ = rt.resolve_model(str(weights))
        if path2 == path or len(exports) != 2:
            fail("the cache must be keyed by the weights' content, never reuse an export of other weights")

        os.environ["SPORTREEL_ULTRALYTICS_RUNTIME"] = "torch"
        if rt.resolve_model(str(weights)) != (str(weights), "torch"):
            fail("SPORTREEL_ULTRALYTICS_RUNTIME=torch must force the PyTorch weights")
        os.environ.pop("SPORTREEL_ULTRALYTICS_RUNTIME")
        if rt.resolve_model("yolo11n_openvino_model")[1] != "torch":
            fail("non-.pt models are used as given")
        if rt.resolve_model(str(Path(tmp, "missing.pt")))[1] != "torch":
            fail("missing weights fall back (the producer then fails loudly on its own)")

        def broken_export(self, **kwargs):
            raise RuntimeError("export exploded")

        FakeYOLO.export = broken_export
        weights.write_bytes(b"third-weights")
        if rt.resolve_model(str(weights)) != (str(weights), "torch"):
            fail("an export failure must fall back to the PyTorch weights")

        sys.modules["openvino"] = None  # import openvino -> ImportError
        if rt.resolve_model(str(weights)) != (str(weights), "torch"):
            fail("without OpenVINO installed the PyTorch weights must be used")

    print("cpu runtime contract ok (cached full-precision OpenVINO conversion, PyTorch fallback on any failure)")


if __name__ == "__main__":
    main()
