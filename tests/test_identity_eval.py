"""E2 verification gate: the two-signal merge gate beats threshold-only on the
labeled look-alike fixture (precision), without losing recall."""

import importlib

ie = importlib.import_module("eval.identity_eval")


def test_gated_beats_threshold_only_on_precision():
    gated = ie._aggregate(ie.run(gated=True))
    threshold_only = ie._aggregate(ie.run(gated=False))
    # The gate removes the look-alike contamination ...
    assert gated["precision"] > threshold_only["precision"]
    assert gated["precision"] == 1.0
    # ... without sacrificing recall (same athlete still grouped).
    assert gated["recall"] >= threshold_only["recall"] - 1e-9
    assert gated["recall"] == 1.0
