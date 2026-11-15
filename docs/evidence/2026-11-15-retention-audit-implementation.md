# Retention audit of 2026-11-15 — what was implemented

Source: `docs/evidence/2026-11-15-sports-reels-retention-audit.md` (PR #385). The audit sets its own rule: no
edit change becomes the default on synthetic tests alone; a blind human review of real proxies comes first. So
this change measures by default and changes an edit only behind a flag that is off.

## Implemented

| Audit item | What was done | Default |
|---|---|---|
| P1 "Measure first_1s_actor_visibility, time_to_visible_action, unresolved_final_action, shot_count, static padding" | `pipeline/retention_metrics.py`: one line per reel in `edl/retention_metrics.jsonl` (in the diagnostics artifact) and one log line `Retention metrics …`. Inputs are the EDL and the bound-track samples already recorded; a measurement that cannot be made is `null`. No thresholds | on, observational |
| P1 "Compare fade-in removal or shortening" | `SPORTREEL_REEL_FADE_IN_SEC` (0–1 s). Unset, the opening fade is the same 0.25 s. The EDL records the value used | off |
| P1 "For 2+ complete rides, the most understandable complete ride first, a strong resolved ride last" | The resolved ride already closes the reel (`narrative_policy.choose_climax`). New: with `SPORTREEL_HOOK_COMPLETE_OPENER=1`, among clips rated within one point of the best opener, one whose ride resolves inside its recording opens. Only the order changes: no ride is dropped, shortened or repeated | off |
| P0 "Preserve fail-closed QA" | Verified on the audited run itself (commit `9a03610`): the four withheld reels carry `qa_gate_review_required` and are `publishable=false` in the manifest. This is the fix merged in PR #382 working in production | — |
| Log quality | "Kept apart: the cluster descriptions conflict" was printed for 160 cluster pairs that were never merge candidates in run 43710581656. It is now printed only for a pair that would otherwise merge | — |

## Measured on the audited run (replayed offline from its EDLs)

`reel_metrics` over the 14 EDLs of run 43710581656:

- 12 of 14 reels have the bound athlete tracked through the whole first second; none starts more than 0.5 s
  before the athlete is tracked.
- The two exceptions are 0.25 (the 85.5 s five-ride reel that opens on 0094) and 0.75 (the 58.4 s five-ride reel
  that opens on 0112). Both are among the four reels the QA gate withheld for an unclear primary athlete. On
  this one run the metric and the gate point at the same two reels; that is one run, not a validated threshold.
- Fields added by this change (`ends_with_recording`, `setup_lead_in_sec`) are `null` in that replay, because the
  run predates them. The next run fills them.

## Findings that need a person, not code

- **0143 + 0152 are still one reel.** In this run the per-clip analyzer, the clustering model and the visual
  verifier each describe both as a white top, dark shorts and a pink board, so the description-conflict rule
  (PR #382) had nothing to act on. The catalog labels 0152 "white shirt, white board" and 0143 "pink board".
  Three model views disagree with one catalog label. Someone has to look at 0152: either the board is pink and
  the catalog entry needs a correction in Annotation Studio, or it is white and the models misread it.
- **Three of the four withheld reels are an unclear primary athlete** (0094 group, 0112 group, 0115). The audit
  asks for tracker overlays on real frames; this environment has the tracks but not the video.

## Not implemented, and why

| Audit item | Reason |
|---|---|
| Paired contain vs follow-crop review proxies, human side-by-side rating | Needs the rendered video and a reviewer. `SPORTREEL_FOLLOW_CROP` already switches the variant for an A/B run |
| Intra-ride moment annotations (takeoff, turn, wipeout…) | Needs new model output and independent human verification; the audit forbids inferring tricks from `surf_ride` |
| Enabling `surf_editor` in the canonical path | The audit says to prove type detection and patch order first; its `_SURF_TYPES` does not include `surf_ride`, the only type observed |
| Teasers | Suppressed on purpose (duplicate appearances across personal reels); the audit says not to re-enable |
| Thumbnails, caption templates, platform measurement | Outside the pipeline's silent-reel contract or needs posting with consent |

## How to run the A/B the audit describes

Same sources, three runs: A with no flag; B with `SPORTREEL_HOOK_COMPLETE_OPENER=1` and
`SPORTREEL_REEL_FADE_IN_SEC=0`; C adds `SPORTREEL_FOLLOW_CROP=0`. Compare `edl/retention_metrics.jsonl` and
`draft_publishability` between them, then have a person watch the proxies before any flag becomes a default.
