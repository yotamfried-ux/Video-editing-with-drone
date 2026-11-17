# Cycle 2 — identity evidence key (PQ-10/23): counterfactual replay, decision NO-GO as drafted

**Config:** MAX_PAID_PIPELINE_RUNS=0, MAX_EXTRA_SPEND_USD=0. **Evidence level:** `historical_artifact_replayed` (run 43920602179 artifacts + cycle-1 scorecard). No media, no paid call, no pipeline code changed in this cycle.
**First failing stage:** `identity` verification → release gate. `identity_evidence.member_key` prefers the run-local `_clip_index`; `identity._strip_internal_fields` removes it (and `_person_id`) before the gate, so evidence recorded at verification never covers the stripped cluster (PR #391's finding; code read on main `eaa81b9`).

## Why #391's key change must not be merged alone
The 6 GT-correct reels withheld in the latest run split as: **2 identity** (3e674b = 5 sources/A7, da9f88 = 2 sources/A4), **2 interval** (ee2933 tail after actor lost at recording end; 2d2963 0094 A3 track gap), **2 QA** (93ddac critical QA fail; 28412e PRIMARY_ACTOR_UNCLEAR). The key bug only explains 2 of 6.

Counterfactual: every multi-source cluster the verifier confirmed (decision engine, `identity_trace.json`) vs GT:

| cluster | engine | GT athletes | after key fix |
|---|---|---|---|
| 0112+0126 (+0131,0104,0140 in reel) | MATCH 0.92 visual-confirmed | A7 = A7 | released, correct |
| 0160+0163 | MATCH 0.92 | A4 = A4 | released, correct |
| 0094+0118 (+0155,0146,0142 in reel) | MATCH 1.0 | A2 = A2 | still blocked (tail issue); also holds 0155 non-ride |
| 0070+0108 | MATCH 0.92 | A6 = A6 | would lose its identity block; reel has excluded 0108 tail (GT-wrong) — blocked only if the interval gate catches the tail (it does not report it today) |
| **0143+0152** | **MATCH 1.0 visual-confirmed** | **A8 ≠ A10** | **released as ONE reel of two athletes (mixed)** |

Net effect of the fix alone: +2 correct reels, and **+1 confirmed wrong-athlete publish (+1 excluded-tail publish possible)**. The current block on 0143+0152 is an accident of the key mismatch, not a detection. Under charter §10.1 (two-sided gate, Pareto veto) this is NO-GO: a wrong-athlete release in exchange for two correct ones.

The verifier is not calibrated: its highest score (1.0) and "confirmed_by_visual_verifier" sit on the only false merge (4 of 5 verified merges correct). Persons 0143/0152 are described almost identically ("pink surfboard, light/white top, dark shorts") and their windows do not overlap, so neither text nor score separates them. Free signals tried: score, reasons, descriptions, window overlap, track ids — none discriminates.

## Decisions / blockers
- **BLOCKED (needs media):** a calibrated pairwise check with 4–6 crops per appearance (PQ-17) on 0143 vs 0152 and the four true merges. The artifact has no crops/thumbnails; the compressed proxies are not available in this environment.
- **BLOCKED (needs budget):** a stronger verifier call costs model spend; cap is $0.
- **Owner choice:** until the verifier is calibrated, should confirmed multi-source athletes be (a) held for operator review (REVIEW, not hidden), or (b) auto-published as the verifier says? (a) keeps 3e674b/da9f88 reachable without releasing 0143+0152 unattended.
- New gap **PQ-40** (P0): the image verifier produces a confirmed false merge at the top score; evidence key fix is coupled to it.

## Next free steps
1. Interval gate (PQ-11): replay the 2.0 vs 2.5 s gap and recording-end tail rule on the frozen `*.perception.json` sidecars (present in the artifact) with actor-switch controls — this unlocks ee2933 and 2d2963 without identity risk.
2. Make the interval gate report the 0108 excluded tail (PQ-06) so a released identity cannot carry it.
3. Hold the key fix on a separate branch until PQ-40 has an owner decision.
