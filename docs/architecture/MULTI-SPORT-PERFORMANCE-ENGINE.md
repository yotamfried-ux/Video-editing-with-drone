# Multi-sport performance engine — architecture, current state, adding a sport

SportReel is one engine for personal performance reels. Surfing is the first profile, because labelled GT exists only
for surfing. This document records what is already sport-neutral, what still carries surf assumptions, and how to add
a sport. Football is the worked example.

Binding rules: gap register §13 and README item 11.

**Mandatory across every sport profile:** inference has no access to historical per-video AI responses, tracker sidecars, manual athlete decisions or GT. See production spec §Binding addendum and gap register §16 (MEM-01..MEM-06). Reuse general model weights and core logic, but never replay a prior clip's model conclusion to claim new-footage quality.

> **Scope of the evidence:** the football material here is a synthetic architecture contract. It proves the engine runs
> a second profile without a new orchestrator, renderer, QA or review. It does **not** prove football accuracy. Real
> football needs labelled football footage, football GT, an independent holdout, render/QA review and owner approval.

## 1. Two layers

| Layer | Owns | Code |
|---|---|---|
| **Core engine** (sport-neutral) | media ingest, provenance, SHA-256; person detection and tracking (YOLO + BoT-SORT sidecars); actor binding (`perception.runtime.enrich_event`); identity continuity and cross-source identity evidence/gates (`identity_evidence`, `real_identity_gate`, `identity_review`); event lineage (`event_identity`); windows and action intervals (`window_refinement`, `complete_action_window_policy`, `action_onset`, `output_qualification`); selection/dedup; framing (`quality_preserving_framing`); render (`stages.editor`, FFmpeg); EDL (`edl_export`); QA / re-edit; publishable manifest; operator approval; evidence; storage (R2) and Supabase; retries and isolation (`integrations/qualification.py`) | `pipeline/`, `integrations/` |
| **Sport / performance profile** (domain) | which words name an action; failed-attempt definition; coverage-first policy; action types and phases; build-up (onset) policy; which description conflicts are owner-reviewable; framing height | `pipeline/sport_profiles/` (`base.py`, `surfing.py`, `football.py`, `registry.py`) |

**Profile contract (`SportProfile`).** Every field has a live consumer in the engine; there is no speculative interface.

| Field | Consumer |
|---|---|
| `event_terms`, `failed_attempt_terms`, `failed_attempt_reasons`, `coverage_first` | `performance_reel_policy.coverage_profile` / `classify_event_eligibility` / `is_explicit_failed_takeoff`; `output_qualification.classify_action` |
| `onset` (`OnsetPolicy`: `requires_motion`, `min_motion_body_heights_per_sec`, `max_lead_sec`, `step_sec`) | `action_onset.motion_supported_onset` (Core), via `window_refinement` and `complete_action_window_policy.extend_to_setup` |
| `reviewable_attribute_conflicts` | `stages.identity._text_attribute_split_reviewed` |
| `framing_subject_height_ratio` | `quality_preserving_framing.decide_framing` / follow-crop |
| `action_types`, `action_phases` | `performance_event.PerformanceEvent` (labelled examples / GT vocabulary) |

**Resolution.** `profile_for(activity)` maps activities through aliases. `profile_for_event(event, activity)` tries, in
order:
1. the activity;
2. the event's `sport` / `sport_profile_id`;
3. the profile vocabulary.

An event that names no sport uses `default_profile()`, set by `SPORTREEL_DEFAULT_PROFILE`. The default is surfing,
because it is the only profile with labelled data; this is explicit configuration rather than a hidden assumption.

**PerformanceEvent** (`pipeline/performance_event.py`) is a typed view over the event dict the pipeline already
passes. It is not a parallel system:
- It carries `sport_profile_id`, `source_sha256`, source frames, `primary_actor_id`, `action_type`, `action_phases`,
  start/end evidence, validity, QA status and evidence references.
- `missing_fields` lists what a stage or profile did not provide. Nothing is filled with an invented value.
- `to_pipeline_event()` turns labelled examples or an external detector's events into engine events.

## 2. Surf assumptions already moved into the surfing profile (cycle 11)

| Was hard-coded in Core | Now |
|---|---|
| `performance_reel_policy._SURF_TERMS`, `_FAILED_TAKEOFF_TERMS`, the failed-takeoff reason set; `classify_event_eligibility` "surf event" branch | `SURFING.event_terms / failed_attempt_* / coverage_first`; Core asks `coverage_profile(event)` (old names kept as read-only aliases) |
| `stages.identity._TEXT_ATTRIBUTE_REASONS` (wetsuit / swimwear / equipment colour) | `SURFING.reviewable_attribute_conflicts`; football has none (team kits) |
| `quality_preserving_framing`: `0.16 if sport == "surfing" else 0.18` | `SportProfile.framing_subject_height_ratio` |
| Lead-in: fixed 2 s cap over the analyzer's `setup_start` | Core motion-supported onset with per-profile `OnsetPolicy` (FIX-PQ-11-001) |

Measured change for the cycle-11 work: Core 16 files, +571/−23 lines. Profiles: 5 files, 176 lines. For a new sport, the
profile is the only code to write.

## 3. Surf dependencies still in shared paths (migration list, PQ-30)

Counts are matches of surf / wave / board / paddle / wetsuit, measured at the cycle-11 head; prompts are included.

| File | Matches | Nature | Migration |
|---|---|---|---|
| `pipeline/performance_reel_policy.py` | 58 | analyzer prompt text "EVERY DISTINCT WAVE RIDE", surf QA-defect filter, wave packing | move prompt and defect filter to `SportProfile` (prompt template field); packing is generic (rename "wave" → action) |
| `pipeline/stages/analyzer.py` | 41 | session-analysis prompts and sport detection | prompt templates per profile |
| `pipeline/stages/identity.py` | 37 | clustering prompt (wetsuit/board vocabulary), description parsing | prompt + attribute vocabulary per profile; football needs number/kit handling |
| `pipeline/stages/surf_editor.py` | 35 | surf-only editing path | keep as surfing implementation behind the profile |
| `pipeline/wave_completion.py`, `surf_ride_segment.py`, `surf_ride_gate.py`, `ride_validity.py` | 17 / 10 / 5 / 11 | surf ride segmentation and validity | profile-owned evaluators (surfing) |
| `pipeline/missed_moment_rescue.py` | 14 | sets `sport="surfing"` on rescued events, surf wording | take sport from the session profile |
| `pipeline/identity_decision_engine.py` | 3 | "never match solely because both have a surfboard"; wetsuit/sleeve categories | equipment class and kit-sharing rules per profile |
| `pipeline/complete_action_window_policy.py` | 8 | fall-resolution tail ("hitting the water") | outcome-tail seconds per profile |
| `pipeline/stages/editor.py` | 10 | colour-grade / BPM tables keyed by sport | already data keyed by sport: keep and add football rows |

## 4. Football profile (`pipeline/sport_profiles/football.py`)

- **Actions:** ball_receive, dribble, pass, shot, goal, tackle, interception, defensive_action.
- **Phases:** build_up → ball_contact → action → outcome.
- **Onset:** the build-up requires motion, ≥ 0.3 body heights/s, at most 4 s before the main moment.
- **Coverage-first:** every usable action of the player is kept and reviewed if uncertain; a non-action ("walk") stays
  under the quality floor.
- **Identity:** no description conflict is owner-reviewable, because team kits are shared. Shirt numbers stay hard
  evidence in the existing number-conflict rule. Other players in frame are never a rejection reason (Core multi-actor
  policy).

### What the engine reuses without change
- tracking sidecars and stitching;
- actor binding among many people;
- window refinement and onset;
- identity gates (single-source MATCH; multi-source needs evidence or owner review);
- output qualification;
- follow-crop framing;
- FFmpeg render and EDL;
- QA / re-edit / manifest / approval / evidence / storage;
- isolated qualification runs.

### What football needs that does not exist yet
1. **Ball detection:** class `sports ball` is in COCO; it must be added to the sidecar classes and linked to the player
   for ball-contact phases.
2. **Shirt-number OCR** as identity evidence. This is non-biometric and allowed.
3. **A kit-aware identity engine:** colour must not be evidence of SAME identity for team-mates.
4. **Analyzer prompts** for football actions.
5. **Labelled football GT** (actions, boundaries, players), a holdout match, calibrated thresholds (onset motion,
   coverage), and football QA rules.
6. **Wider-field drone framing:** the follow-crop height ratio needs calibrating.

### Effort estimate
- **Profile and prompts:** ~1–2 days.
- **Ball class and player–ball link** in perception: ~2–3 days.
- **Number OCR evidence:** ~3–5 days.
- **Kit-aware identity rule:** ~2 days.
- **GT annotation:** one match day, ~1–2 days of labelling in the existing annotation studio.
- **Calibration and qualification run:** ~2–3 days, within an approved budget.
- **Not needed:** a new orchestrator, renderer, storage, review or evidence system.

## 5. Architecture contract (synthetic) — `scripts/test_football_profile_architecture_contract.py`

Runs in CI (`pipeline-real-mp4.yml`, FFmpeg).

| # | Proven on the synthetic football MP4 | Result |
|---|---|---|
| F1 | Football profile registered (aliases soccer/futsal; own actions and phases) | PASS |
| F2 | A labelled `PerformanceEvent` (pass + build-up) converts to the engine's event without football Core code | PASS |
| F3 | Production binding picks the target among a same-kit team-mate and an opponent | PASS |
| F4 | Production windows open on the target's run-up (football onset), not on standing team-mates | PASS |
| F5 | Production eligibility: low-score action = coverage UNCERTAIN; non-action ineligible; identity gate unchanged | PASS |
| F6 | Production framing and editor render a 9:16 H.264 clip that follows the target (decoded centre = target); same EDL recorder | PASS |
| F7 | The `PerformanceEvent` view lists missing fields explicitly | PASS |
| F8 | Surfing behaviour unchanged | PASS |

Second-domain coverage of the onset rule is in `scripts/test_action_onset_contract.py` (O4).

## 6. Adding a sport — procedure
1. Add `pipeline/sport_profiles/<sport>.py` with terms, failed attempts, actions and phases, onset policy, identity
   conflicts and framing; register it.
2. Add prompts and evaluators that belong to the sport as profile-owned modules; never add sport branches to Core.
3. Collect labelled examples and GT in the existing annotation studio; freeze a GT version and its digest.
4. Add the sport to the synthetic architecture contract, then to a real-footage qualification run in an isolated
   namespace (`pipeline-qualification-run.yml`) with a pre-registration.
5. Calibrate on dev data and qualify on an independent holdout, with rendered MP4 review and owner approval.

## 7. Not yet proven for other sports
- Any accuracy number.
- Ball and number evidence.
- Identity across team-mates in identical kits.
- Football QA prompts.
- Framing on a wide pitch.
- The default-profile fallback when events carry no sport, which works today only because surfing is the default.

## 8. Cycle 12: MULTI_SPORT_COMPATIBILITY of the new Core changes

| Change | Layer | Surf problem solved | Other surf cases | Football (contract) | Surf terms in Core | Football recalibration |
|---|---|---|---|---|---|---|
| FIX-PQ-12-001 draft ledger (`pipeline/draft_ledger.py`) | Core: Review, retry and storage | duplicate drafts after a crash and a retry (PA-13), RED to GREEN | D1–D10, every reel kind | F9: the football reel gets a canonical id and render-plan digest from the same code, stable under a changed description | none (F9) | none |
| FIX-PQ-12-002 owner rejection precedence (`identity_review.rejected_pairs`) | Core: identity | a model MATCH kept the owner-rejected 0074+0151 together | W1–W9; 22 identity contracts unchanged | applies unchanged to team-mates: a rejected same-kit pair can never merge through a verifier | none (F9) | none: a decision is bound to source content and person |
| FIX-PQ-12-003 non-GT-person scoring | Core: evaluation | a valid reel of an uncatalogued person (0095) was counted as a QA false pass | — | the same split serves untagged players | none | none |
| Holdout tooling (`scripts/holdout_qualification.py`) | Core: evaluation | qualification on unseen footage | — | condition tags are free-form; the football GT plugs into the same freeze, lock and evaluate path | none | per-sport thresholds come from `SportProfile` and are digested in the lock |

**Rejected in cycle 12:** an image-space motion end rule (E1, EVD-12-003). A drone that follows a surfer keeps the
rider still in the image, so motion alone cannot mark the end of a surf action. The end signal belongs in a
profile-owned action-state evaluator, trained on labelled data. It is not a Core threshold.

**Still not proven:** football accuracy of any kind. The synthetic contract remains architecture-only.
