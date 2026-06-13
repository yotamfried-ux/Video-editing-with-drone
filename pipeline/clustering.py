"""
pipeline/clustering.py — pure clustering/selection helpers.

Import-light (stdlib only) so the merge-gate truth table and frame-selection are
unit-testable without torch / CLIP / Gemini. The heavy stages (identity.py,
analyzer.py) supply the real similarity matrix, the Gemini confirmation callback,
and the frame-sharpness function.
"""

from collections import defaultdict


def union_find_merge(sim_matrix, clip_indices, *, merge_threshold, high_conf, confirm_fn):
    """Cluster items by CLIP cosine similarity with a TWO-SIGNAL gate.

    For each pair i<j:
      - same source clip            → never merge (two people in one clip differ)
      - sim >= high_conf            → merge directly (CLIP alone is confident)
      - merge_threshold <= sim      → merge ONLY if confirm_fn(i, j) is True
        (< high_conf)                 (second signal: e.g. Gemini "same person?")
      - sim < merge_threshold       → never merge

    Returns a list of groups, each a sorted list of item indices. confirm_fn is
    only invoked for uncertain-band pairs that would actually join two components.
    """
    n = len(clip_indices)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if clip_indices[i] == clip_indices[j]:
                continue
            sim = sim_matrix[i][j]
            if sim < merge_threshold:
                continue
            if find(i) == find(j):
                continue  # already together — no need to confirm
            if sim >= high_conf or confirm_fn(i, j):
                union(i, j)

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return [sorted(g) for g in groups.values()]


def pick_sharpest(paths, sharpness_fn):
    """Return the path with the highest sharpness score, or None for an empty list."""
    best = None
    best_score = float("-inf")
    for p in paths:
        try:
            score = sharpness_fn(p)
        except Exception:
            score = float("-inf")
        if score > best_score:
            best_score, best = score, p
    return best
