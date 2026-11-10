"""Run the SAME YOLO weights through OpenVINO on CPU runners (3-4x faster inference, same FP32 model).

Measured on a 4-vCPU runner with yolo11n (frames from a 4K clip with people, conf 0.18):

  imgsz  640: torch 39 ms/frame -> OpenVINO 13 ms; 116/116 boxes matched at IoU>0.9, max |dconf| 0.017
  imgsz 1280: torch 116 ms/frame -> OpenVINO 30 ms; 100/101 boxes matched at IoU>0.9, max |dconf| 0.023

The export is a format conversion of the verified ``.pt`` weights (no quantization, ``half=False``), made
once and cached by the weights' SHA-256. Anything unexpected (OpenVINO missing, export or load failure,
non-.pt model) falls back to the PyTorch weights, so this can never block perception.
Set ``SPORTREEL_ULTRALYTICS_RUNTIME=torch`` to force the previous runtime.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_RUNTIME_ENV = "SPORTREEL_ULTRALYTICS_RUNTIME"
_CACHE_ENV = "SPORTREEL_OPENVINO_CACHE"


def _cache_root() -> Path:
    return Path(os.getenv(_CACHE_ENV, "").strip() or Path.home() / ".cache" / "sportreel" / "openvino")


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_model(model: str) -> tuple[str, str]:
    """Return ``(model_path_for_YOLO, runtime)`` where runtime is ``"openvino"`` or ``"torch"``."""
    requested = os.getenv(_RUNTIME_ENV, "openvino").strip().lower()
    if requested in {"torch", "pytorch", "pt", "off", "0"}:
        return model, "torch"
    if not model.endswith(".pt") or not os.path.isfile(model):
        return model, "torch"
    try:
        import openvino  # noqa: F401
    except Exception:
        return model, "torch"
    try:
        target = _cache_root() / f"{Path(model).stem}-{_sha256(model)[:16]}_openvino_model"
        if not (target / "metadata.yaml").exists():
            from ultralytics import YOLO

            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=str(target.parent)) as work:
                staged_pt = Path(work) / Path(model).name
                shutil.copy2(model, staged_pt)
                exported = YOLO(str(staged_pt)).export(format="openvino", imgsz=1280, dynamic=True, half=False)
                staging = Path(work) / "ready"
                shutil.move(str(exported), staging)
                if not target.exists():
                    os.replace(staging, target)
        return str(target), "openvino"
    except Exception as exc:  # noqa: BLE001 - fall back to the verified PyTorch weights
        logger.warning("OpenVINO runtime unavailable, using PyTorch weights: %s", exc)
        return model, "torch"


__all__ = ["resolve_model"]
