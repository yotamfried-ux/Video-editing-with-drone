"""Minimal Python path bootstrap for scripts/ entrypoints.

Product-critical runtime policies are installed explicitly and fail-fast through
``pipeline.bootstrap`` by each real entrypoint.
"""
from pathlib import Path
import sys

root = str(Path(__file__).resolve().parents[1])
if root not in sys.path:
    sys.path.insert(0, root)
