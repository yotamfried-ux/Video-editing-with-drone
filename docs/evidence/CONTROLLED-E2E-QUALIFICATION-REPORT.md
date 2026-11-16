# SportReel — controlled end-to-end qualification report (2026-11-16)

**Status: NOT RUN on the fixed code.** A controlled pipeline run needs the owner's approval (paid execution). This
report holds the baseline it will be compared against, the frozen inputs, and the exact acceptance checks.

## 1. Baseline: frozen GT-v1 vs the last two runs (offline, read-only)

Evaluator: Annotation Studio `eval-1.3.0` / `match-2`, run offline by `annotation-studio/scripts/evaluate-offline.mjs`
(no database write). Dataset `ae844a94-b425-4f0a-8e4f-56034ab83425`, digest `b31fd9b4…`, 24 sources, 45 segments
(42 include, 3 exclude), all splits. Both runs predate this branch.

| Run | Commit | Segment recall / precision (IoU 0.5) | Identity accuracy / B³-F1 | Physical rides covered | Excluded segments contaminated | Report digest |
|---|---|---|---|---|---|---|
| 43710581656 | `9a03610` | 0.452 / 0.760 | 0.947 / 0.973 | 24/24 | 3/3 | `77220cd1fa0d` |
| 43816344303 | `2b7d4cf` | 0.452 / 0.760 | 0.947 / 0.973 | 24/24 | 3/3 | `3f7db45798fa` |

Segment recall is low because GT-v1 splits one ride into contiguous manoeuvre segments of the same athlete; the
physical-ride view (contiguous include segments, coverage ≥ 0.5) shows every ride was selected. Run 43816344303
re-qualified under the new rules (`scripts/write_batch_qualification.py`): execution SUCCESS, product **FAIL**,
0/14 parts verified — its parts carry none of the evidence the qualification requires.

## 2. Mandatory real-video cases (frames at 59.94 fps; athlete numbers are per source)

| Source | SHA-256 (12) | GT-v1 segments | Selected (both runs) | Coverage / contamination | Classification | Status |
|---|---|---|---|---|---|---|
| 0143 | `4e84086f72c6` | 0–427, 427–496 inc A1 | 0–492 | ride cov 0.99 | identity: merged with 0152 by an image-verified model verdict; GT says two athletes | VISUAL_REVIEW_REQUIRED |
| 0152 | `85aedb594ab7` | 205–524, 526–676 inc A1 | 299–606 | ride cov 0.65 (late start) | identity (see 0143); late start | VISUAL_REVIEW_REQUIRED |
| 0097 | `548cf4ffb308` | 0–608 inc A1 | 119–594 | cov 0.78 | identity: missed merge with 0115 (GT: one athlete) | VISUAL_REVIEW_REQUIRED |
| 0115 | `b62c8aa0cb14` | 4–810, 810–982 inc A1 | 389–930 | cov 0.55: beginning omitted | boundary (RC-04/05): start 385 frames (6.4 s) late | VISUAL_REVIEW_REQUIRED |
| 0095 | `6d57d3835262` | 0–379 **exclude** | 0–348 | 348/379 excluded frames selected | eligibility (RC-03) | VISUAL_REVIEW_REQUIRED |
| 0155 | `a10e4151734f` | 0–476 **exclude** | 0–420 | 420/476 excluded frames selected | eligibility (RC-03), failed takeoff | VISUAL_REVIEW_REQUIRED |
| 0108 | `3f1f5e846b33` | 0–409 inc, 409–553 **exclude** | 101–540 | 131/144 excluded tail frames selected | tail (RC-04) | VISUAL_REVIEW_REQUIRED |
| 0094 | `250c3592fd87` | 0–793 inc A1, 1010–2199 inc A2 | 239–1319, 1618–2128 | first window runs 526 frames past A1's ride into A2's | actor handoff (RC-04, T03) | VISUAL_REVIEW_REQUIRED |
| 0151 | `e01a614de605` | 0–287, 288–456 inc A1 | 29–444 | cov 0.91 | conservative cut; tracks 10002/10003 are distinct simultaneous actors — not stitched | VISUAL_REVIEW_REQUIRED |
| 0104 | `5f7ba69f1c3f` | 1–788, 788–925 inc A1 | 191–870 | cov 0.73: late start | boundary | VISUAL_REVIEW_REQUIRED |

No private footage was viewed; every case stays blocked until a person reviews the source and the rendered reel.
Previously published disputed reels (0143+0152, 0095, 0108) remain unresolved; no entitlement was changed.

## 3. The controlled run (when approved)

- **Inputs:** the same frozen 24-source set (SHA-256 above / in GT-v1); pipeline commit = merge of PR #390.
- **Must hold:** `runtime_policy_registry.json` with no problems; every part carries `output_qualification` with a
  matching `proof_digest`; `batch_qualification.json` written; the evaluator re-run on its `predictions.v1.json`.
- **Expected changes vs baseline:** 0095/0155/0108-tail and 0094's crossing withheld (qualification issues) or
  absent; 0143+0152 publishable only with a digest-backed identity pass (then still disputed visually).
- **Risk to measure first:** the fail-closed rules may withhold valid rides (UNCERTAIN for unmeasured CV activity or
  unvalidated actor spans). Count withheld parts by `qualification:` code before judging recall.
