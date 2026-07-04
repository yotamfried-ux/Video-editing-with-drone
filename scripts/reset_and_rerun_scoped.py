#!/usr/bin/env python3
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if (os.getenv("STORAGE_BACKEND", "drive").strip().lower() or "drive") == "r2":
    from pipeline.r2_batch_scope import install
    install()

runpy.run_path(str(ROOT / "scripts/reset_and_rerun.py"), run_name="__main__")
