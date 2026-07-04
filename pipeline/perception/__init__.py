"""Deterministic perception helpers for the SportReel pipeline.

The package is intentionally isolated from the production editing path until the
perception contracts and debug runner are proven on real surf/drone footage.
"""

from .schema import PerceptionDetection
from .crop_math import bbox_to_crop, bbox_center_norm, bbox_visible_ratio

__all__ = [
    "PerceptionDetection",
    "bbox_to_crop",
    "bbox_center_norm",
    "bbox_visible_ratio",
]
