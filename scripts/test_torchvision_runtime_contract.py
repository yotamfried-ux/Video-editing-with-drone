#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require_tokens(label: str, text: str, tokens: list[str]) -> None:
    missing = [token for token in tokens if token not in text]
    if missing:
        raise SystemExit(f"{label} missing tokens: {missing}")


def main() -> int:
    workflow = (ROOT / ".github/workflows/pipeline-run.yml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    require_tokens(
        "pipeline torch/torchvision install",
        workflow,
        [
            "pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu",
            "from torchvision.ops import nms",
            "torchvision.__version__",
            "nms.__name__",
        ],
    )
    require_tokens("requirements", requirements, ["torch>=2.0.0", "torchvision>=0.15.0", "ultralytics>=8.3.0"])
    print("Torchvision runtime contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
