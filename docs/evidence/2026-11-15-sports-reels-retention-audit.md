# SportReel — Editorial Retention & Viral-Potential Audit (2026-11-15)

**Status:** evidence-backed pipeline/EDL/code audit. **NOT a visual review of rendered MP4 frames, not a claim that any edit will become viral.**

## Exact evidence

- Last completed successful **full Run Pipeline** checked: [GitHub Actions run #43710581656](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/43710581656), 2026-11-15 11:47–12:49 UTC, commit `9a03610a73d09784ef02f3a9c1d5c4cf44f7f29e`. Later workflow_dispatch #43712059697 was **cancelled** and is not a new completed full render.
- Artifact **pipeline-diagnostics-43710581656** (artifact ID `14162886161`): `publishable_reel_manifest.json`, `publishable_reel_gate_result.json`, `run_quality_report.json`, `edl/*.edl.json`, `edl/edl_clips.jsonl`, `framing_decisions.jsonl`, `identity_trace.json`, `candidate_decision_ledger.json`, `predictions.v1.json`.
- Cross-check: Supabase `public.pipeline_runs` confirms pipeline ID `e05b179e-37b2-4356-8e2d-c806bacd8832`, Github run ID and succeeded **execution**; `public.draft_publishability` confirms which of 14 review drafts are approved for publication.
- **No MP4 output is bundled in this diagnostics ZIP**, and review assets are under private `review/` R2 paths. No direct authenticated MP4 player/access was available in this assessment. All editing recommendations below requiring visual judgment must be validated against short, access-controlled real video proxies before implementation.

## Observed results (not platform engagement measurements)

| Measure | Actual observed evidence | Interpretation |
|---|---:|---|
| Draft reels uploaded to REVIEW | 14 | 14 athlete-level drafts produced |
| Publishable | **10/14** | 4 withheld for QA, despite GitHub Actions job success |
| Final QA verdict | 12 PASS / 2 FAIL | Two additional PASS were withheld on subject/identity policy |
| Publishable business gate | `passed=true, outcome=partial` | No complete production qualification |
| `run_quality_report` | `status=fail` | A primary actor safety violation was flagged |
| Candidate action decisions | 32 candidates, **25 selected**, 7 discarded | Must preserve verified complete actions and explicit reject reasons |
| Event types in clip EDL | **25/25 `surf_ride`** | Valuable surf-specific subaction distinctions (turn, cutback, wipeout, landing) are not represented in the final clip-level labels |
| Framing decisions | **24/25 `follow_crop`**, 1 `contain` | Evaluate framing/zoom on real images; 19 cropped actions started as `full_frame_readable` |
| Tracking | 278 tracks, 101 shorter than 2 seconds (**36.3%**) | Aggregate fragmentation, not the probability a featured athlete is lost; still warrants targeted actor review |
| Suspect windows | 3/25 final action windows | Primary actor can't be followed reliably in some windows |
| Output duration | **5.63s–85.5s** | Wide range; not an independent viral-success predictor |
| Multi-source shot counts | **9×1 shot, 3×2 shots, 2×5 shots** | Most personal reels have a single ride, so full-shot hooks cannot rely on reordering multiple rides |
| First continuous shot | up to **20.3s** in an 85.5s reel and **20.0s** in a 58.4s reel | Potential early-retention risk until a human reviews whether the rides are already engaging |
| Video-output fade metadata | **0.25s fade in, 0.4s fade out** on all 14 EDLs | Measure whether opening fade suppresses visible action in first swipe-critical frames |
| Source vs output frame rate | **59.94 fps sources → 30 fps output** | EDL `speed≈1.998` encodes source frames per output frame, **not evidence of 2× playback speed** |

**Four withheld:**
- Source **0151** rider: `RIDE_BOUNDARY_UNCERTAIN`, final QA FAIL.
- Athlete spanning **0094** and other sources: primary athlete continuity unclear, final QA PASS but publication withheld.
- Athlete spanning **0112** and several other sources: both final QA FAIL and primary actor unclear; repeated camera-end cuts.
- Athlete associated with **0115**: primary actor continuity unclear, QA PASS but publication withheld.

QA reports for many published clips also warn `RECORDING_ENDS_MID_ACTION`; this is a source-footage issue that cannot be fabricated away by rendering. Avoid closing an entire reel on an unresolved event when a complete ending is available and equally suitable. If the only ride is incomplete, apply the product's explicit reject/repair policy; never synthesize an outcome.

## Current active implementation audit

1. **`pipeline/editorial_value_ranker.py`: metadata only.** The module expressly states its score does not influence live selection, partitioning, slow-motion or ordering. Adding a value score to the ledger is not the same as using it to edit.
2. **`pipeline/narrative_policy.py`: a generic arc exists and is installed in `pipeline/bootstrap.py`.** It chooses a high-quality opening and climax when multiple events exist, but scores are based on quality/perception plus optional peak, not externally measured audience retention. The majority of outputs are one-shot.
3. **`pipeline/stages/surf_editor.py`: surf-specific hook/transition/window functions exist, but `enable_surf_editor_policy()` is referenced in `run_surf.py`, not in the canonical tracked bootstrap path.** Moreover, its `_SURF_TYPES` set does not include the `surf_ride` clip label observed 25/25 times; so the current recorded events would not trigger its surf-specific ordering even if enabled. **Verify wrapper precedence and product invariants before changing installation order.**
4. **`pipeline/teaser_policy_runtime.py`: explicitly suppresses cold-open teaser duplicates.** Historical reason: repeating the climax may overlap another athlete's source moment and create duplicate appearances across personal reels. Do not simply re-enable teasers. Consider a non-duplicative action-first opening or an optional distinct, rights-cleared promotional cut if the product contract is explicitly amended.
5. **`pipeline/quality_preserving_framing.py`: `SPORTREEL_FOLLOW_CROP` defaults to ON.** A tracked 9:16 follow crop may override `full_frame_readable` contain decisions when trajectory is dense, making follow-crop frequent even though the documented crop permission is conservative. Compare variants at mobile size, inspect subject visibility and sharpness; nominal 2160×3840 output does not guarantee true source-level detail after crop/upscale.
6. **`pipeline/stages/editor.py`: contains introductory/closing fades, transition mapping, existing optional loop-bookend helper, and audio-related legacy code.** Preserve canonical **silent** output; optional in-app music belongs to the athlete's social platform, not an automatic pipeline soundtrack.
7. **`pipeline/performance_reel_policy.py`: all usable full surf rides must be retained**, one primary reel per athlete, parts split only when complete actions cannot fit under the maximum duration. Do not shorten long reels by silently dropping less exciting but usable rides.

## Official platform guidance (principles, not guarantees)

- YouTube [Shorts search/discovery](https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=en) identifies chose-to-view vs swiped-away, average viewing duration, average percentage viewed, viewer satisfaction and relevance; [Analytics](https://support.google.com/youtube/answer/12942217?co=YOUTUBE._YTVideoType%3Dshorts&hl=en) explains measurement.
- Meta [Instagram Best Practices](https://about.fb.com/news/2024/10/best-practices-education-hub-creators-instagram/) and [Reels average/total watch time](https://about.fb.com/news/2023/04/instagram-reels-trending-audio-and-gifts-updates/) recommend testing hooks and watching the actual drop-off points.
- TikTok for Business [Creative Guide](https://ads.tiktok.com/business/en/guides/what-is-ad-creative-guide) and [Creative Best Practices](https://ads.tiktok.com/resources/help/article/creative-best-practices) emphasize action early, hooks, native vertical presentation and testing, mostly for advertising; do not interpret as organic sports-algorithm rules.

No reliable document guarantees that a particular duration, transition count, zoom, overlay or hook will go viral.

## Recommended implementation sequence

### P0 — Safety and quality: do not confuse viral optimization with production qualification

- Reproduce all 4 withheld reels with their precise QA evidence; inspect actual corresponding proxy videos and tracker overlays.
- Fix primary-actor ambiguity at 0094 / 0112 / 0115 via tracker continuity, track rebinding and manual review when uncertain. Re-evaluate source 0151 action boundary on real frames.
- Treat the current 10/14 publishability and run-quality FAIL as blocking complete production readiness. Preserve full action accountability, immutable GT catalog, no wrong-person attribution and final fail-closed QA.
- Compare approved Ground Truth labels to latest predictions/EDL without leaking labels into inference. Preserve no audio, source lineage and 4K delivery contract.

### P1 — Action-first hook selector, without duplicating or losing a wave

- Add an **observational first** `hook_candidate`/ `peak_frame`/ `action_resolves` signal based on source evidence, visible athlete, verified timing, strong on-screen motion and manual annotation; do not infer unsupported tricks from `surf_ride`.
- For **2+ complete rides**, test score-aware ordering placing the most visually understandable **complete** ride first, with a strong resolved ride last; do not invent a teaser or shorten a complete action.
- For a **single-ride reel**, focus on starting at the earliest valid readable action, not a reused climax snippet. Compare fade-in removal or shortening only when the first shot itself passes identity/continuity QA.
- Make the opening frame immediately show the athlete and action as far as source allows; avoid logos, filler, black frames, or forced fake drama.
- Measure `first_1s_actor_visibility`, `time_to_visible_action`, `time_to_peak`, `unresolved_final_action`, `shot_count` and `unnecessary_static_padding_seconds`. Thresholds must be calibrated on real proxies, not assumed.

### P1 — Framing/camera motion quality

- Render paired **contain vs current follow_crop** low-resolution review proxies from identical source windows with no other changes. Do not expose full media publicly.
- For each frame/shot check: primary actor still in crop; person height fraction, missing bbox interval, jerk/pan acceleration, headroom/leadroom, visual context and upscaled sharpness.
- Never increase zoom merely to optimize a proprietary model engagement score. Fail closed or widen framing when subject continuity is uncertain.
- Add a side-by-side human rating (identity clarity, motion smoothness, understandable sport context, visual quality, emotional payoff). Track objective evidence separately.

### P1 — Surfing-specific editorial semantics

- Keep `surf_ride` as the **complete atomic ride**. Add optional **intra-ride moment annotations** (takeoff, acceleration, carve/turn, recovery, wipeout/clean finish, emotional reaction), grounded in CV/event timing and independent human verification.
- Use moments to drive opening and pacing **within safe action boundaries**, not to split or drop full rides.
- Safely integrate the surf policy into the canonical pipeline only after proving its type detection, patch order and event completeness through regression tests.
- A/B baseline vs surf-specific ranking while holding the same footage, athlete, action inclusion, resolution and render parameters fixed.

### P2 — Platform-facing polish, optional

- Generate compliant thumbnail/cover **metadata** from a genuinely compelling visible frame; do not generate misleading action images.
- Offer optional **text/caption templates** and social-post guidance outside the canonical silent reel, or in a separately versioned, user-approved variant, respecting safe areas and rights.
- Do not auto-add copyrighted sound/music; retain silent output and let athletes add platform-native audio.
- Limit transitions and visual effects to where they improve comprehension; avoid unnecessary dissolves and over-editing.
- For long 5-ride reels, test complete-ride ordering and dead-time removal; avoid fake short highlights that violate the all-usable-waves business contract.

## Validation strategy and gates

1. **Visual access:** obtain 14 **compressed private review proxies** and keep corresponding EDL/manifests; the GitHub artifact does not contain MP4 bytes. Use an authorized R2 signed URL with short expiry or local user upload; never make private review assets public to bypass access.
2. **Per-reel storyboard:** inspect actual first 0.0/0.5/1.5/3.0 seconds, every shot junction, midpoint, climax and final second; score actor readability, action clarity, motion smoothness, narrative payoff, natural ending and drop-off risk. Log timestamps and stills internally with secure access.
3. **Controlled edit test:** A = current output; B = action-first and safe ordering; C = safer framing variant where appropriate. Keep same source and all required action coverage, encode settings, final QA and athlete identity.
4. **Offline safety gate:** zero wrong athlete, zero lost/duplicated complete action, zero excluded source, 100% explicit QA policy, 9:16, 2160×3840, 30 fps, no audio, no unapproved release/cost.
5. **Platform impact** (only after authorized posting with consent): measure Instagram watch time, saves, shares per reach; YouTube Shorts chose-to-view vs swiped-away, average duration and average percentage viewed. Evaluate by similar athlete/event format, randomize variants where allowed and avoid falsely claiming causality from tiny samples.
6. **Go/no-go:** do not merge a performance edit on synthetic tests alone or claim viral success on model-generated `engagement` scores. Require human-blind visual review and no regression on the approved GT cohort before default-on.

## Missing and explicit limitations

- Full video frames, playback, dynamic crop smoothness, motion blur, actual emotional impact, transition legibility and visual quality were **NOT directly observed**. They cannot be inferred reliably from EDL/QA text alone.
- No Instagram/TikTok/YouTube publication insights for these particular private reels were available; virality **cannot be predicted or verified** from this run.
- All statistics are from the specified run, not every deployment or every future run.
- This document proposes experiments only; no production pipeline change, cloud access policy change, render rerun or paid call was performed.
