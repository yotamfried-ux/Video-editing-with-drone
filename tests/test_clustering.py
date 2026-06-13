"""E1/E2: merge-gate truth table + sharpest-frame selection (pure logic)."""

from pipeline.clustering import union_find_merge, pick_sharpest


def _groups_as_sets(groups):
    return sorted([tuple(g) for g in groups])


def test_high_conf_merges_without_confirmation():
    # sim 0.95 >= high_conf 0.88 → merge, confirm_fn must NOT be consulted.
    sim = [[1.0, 0.95], [0.95, 1.0]]
    calls = []
    groups = union_find_merge(sim, clip_indices=[0, 1], merge_threshold=0.78,
                              high_conf=0.88, confirm_fn=lambda i, j: calls.append((i, j)) or True)
    assert _groups_as_sets(groups) == [(0, 1)]
    assert calls == []  # second signal not needed at high confidence


def test_mid_band_merges_only_when_confirmed():
    sim = [[1.0, 0.82], [0.82, 1.0]]  # in [0.78, 0.88)
    merged = union_find_merge(sim, [0, 1], merge_threshold=0.78, high_conf=0.88,
                              confirm_fn=lambda i, j: True)
    assert _groups_as_sets(merged) == [(0, 1)]

    split = union_find_merge(sim, [0, 1], merge_threshold=0.78, high_conf=0.88,
                             confirm_fn=lambda i, j: False)
    assert _groups_as_sets(split) == [(0,), (1,)]


def test_below_threshold_never_merges():
    sim = [[1.0, 0.5], [0.5, 1.0]]
    groups = union_find_merge(sim, [0, 1], merge_threshold=0.78, high_conf=0.88,
                              confirm_fn=lambda i, j: True)
    assert _groups_as_sets(groups) == [(0,), (1,)]


def test_same_clip_never_merges_even_at_high_sim():
    # both items from clip 0 → different people by definition
    sim = [[1.0, 0.99], [0.99, 1.0]]
    groups = union_find_merge(sim, [0, 0], merge_threshold=0.78, high_conf=0.88,
                              confirm_fn=lambda i, j: True)
    assert _groups_as_sets(groups) == [(0,), (1,)]


def test_pick_sharpest_selects_max_score():
    paths = ["a.jpg", "b.jpg", "c.jpg"]
    scores = {"a.jpg": 10.0, "b.jpg": 99.0, "c.jpg": 50.0}
    assert pick_sharpest(paths, scores.get) == "b.jpg"


def test_pick_sharpest_empty_is_none():
    assert pick_sharpest([], lambda p: 1.0) is None
