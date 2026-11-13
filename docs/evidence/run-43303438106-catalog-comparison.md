# Run 43303438106 against the manual catalog

Run: `Run Pipeline · 0d35aff8…` on `main@041eadb` (#371), 2026-11-12, **success / partial**: 14 athletes entered
compile, 13 published, 1 QA-failed. Catalog: Supabase `ground_truth`, latest approved revision per source (24 sources,
13 athletes with an included action). Pipeline side: the job log's DIAG digest and `IDTRACE_JSON`.

Limit of this evidence: the `pipeline-diagnostics` artifact could not be downloaded from the investigation host
(`blob.core.windows.net` is blocked), so everything below comes from the job log. Tracker detections are not in the log;
claims that need them are marked *not verified*.

## 1. Gaps between output and catalog

| gap | catalog | run | cause class |
|---|---|---|---|
| **one athlete, two reels** | 0070 + 0108 = one woman | clusters 0 and 1, two reels | pipeline rule (fixed here, §2) |
| wrong merge | 0143 (pink board) ≠ 0152 (white board) | one reel | upstream: analyzer and the model's visual cluster both read 0152 as "on a pink board". Not fixed |
| reel for an excluded source | 0095 `exclude / no_meaningful_action` | reel, QA PASS 65 | analyzer scored it 6 (a ride ending in a fall). Not fixed |
| correct | 0097+0115 one, 0074 ≠ 0151, 0094 father and child separate, 0155 no reel, red-board man = 0104/0112/0126/0131/0140 | as catalogued | — |

Time windows (final cut per drafted person against the catalog's `include` segments of that athlete):
**88 %** of catalogued seconds are in the cut (run 43203677423: 81 %), **94 %** of cut seconds are catalogued (91 %).
Remaining gaps: ten cuts still open ≥ 1 s late (0115 3.9 s, 0104 2.8, 0070 2.5, 0094 2.5, 0097 2.0, 0118 1.7, 0142 1.4,
0162 1.3, 0163 1.0; the tandem 8.9 s); 0094's long-hair cut runs 9.3 s past the catalogued ride end (13.2 s), 5.6 s of it
inside the father-and-child ride; the tandem reel is 25.8–33.8 s against a catalogued 16.9–36.7 s. Sources without an
analyzer `setup_start` (0070, 0097, 0104, 0118, 0162, 0163) get no lead-in.

## 2. Root cause fixed: a generic garment word is read as a different garment

The analyzer described the two clips of the woman as

- 0070: `surfer in grey long-sleeve top and reddish bottoms on a light blue longboard`
- 0108: `surfer in grey top on a turquoise surfboard`

`extract_structured_attributes` filed `long-sleeve` under `long_sleeve` and a bare `top` under `shirt_top`, the same label
as a short-sleeved `t-shirt`. `_sleeve_styles_compatible` treats two different labels as incompatible, so
`IdentityDecisionEngine` returned `NO_MATCH wetsuit_vs_bare_or_swimsuit_conflict`. The job log shows the consequence:

```
Splitting identity cluster 'Woman in a grey long-sleeve swimsuit on a light blue longboard.' into singles:
IdentityDecisionEngine hard conflict (wetsuit_vs_bare_or_swimsuit_conflict)
```

The model's own visual clustering had joined the two (model cluster 0); the text rule overrode it, and a hard-conflict
split is never offered to the visual merge check (`identity._verify_merge_candidates` ran once, for 0097/0115). Same class
as #370 (a hedged garment read as a fact): less detail was treated as a contradiction.

Reproduced offline on the run's own descriptions (`scripts/eval_identity_vs_catalog.py`, fixture
`run-43303438106-identity-descriptions.json`, 24 persons, 275 cross-source pairs, 19 of them the same catalogued athlete):

| | before | after |
|---|---|---|
| same-athlete pairs hard-split | **1** (0070 + 0108) | **0** |
| different-athlete pairs matched | 1 (0143 + 0152, analyzer-side, §1) | 1 (unchanged) |

Fix (`pipeline/stages/identity.py`): `shirt`/`top` with no sleeve length is `covered_top`; `t-shirt`/`short-sleeve` stays
`shirt_top`. `covered_top` is compatible with `long_sleeve`, `shirt_top` and `covered_top` only. Unchanged conflicts (the
contract asserts each): shirtless, sleeveless, swimwear, a full wetsuit (#371, 0074 ≠ 0151), a t-shirt against long
sleeves. 0070 + 0108 now ends `UNCERTAIN`, so it goes to visual verification instead of a split.

`scripts/test_generic_top_identity_contract.py` fails on `main@041eadb` and passes here; it runs in
`cost-time-optimizations-check`. The existing identity contracts (merge check, failsafe, wetsuit coverage, athlete
canonicalization, lineage, verified cluster merge) pass. `test_identity_trace_contract.py` needs `langsmith`, absent on the
investigation host.

## 3. QA remarks: pipeline or QA agent

| remark | right? | owner |
|---|---|---|
| `PREMATURE_CUT` on the father and child reel | yes: cut 25.8–33.8, catalog 16.9–36.7, recording ends 36.7 | pipeline. The model saw the 12.8–36.7 s clip (track 162 13.8–36.6 s) and ended the moment at 33.8 s. End fixed in §3a; the start (25.8 s against 16.9 s) is not |
| `NO_VISIBLE_ACTION` (critical) on the red-board man, clip 5 = 0140 | label wrong: the catalog has a ride 1.8–10.5 and the cut is 1.5–11.4. QA quoted the pipeline's "primary continuity 0.415" (policy threshold 0.50) | QA agent (should say `PRIMARY_ACTOR_UNCLEAR`) and pipeline (0140 track 2 continuity; tracks 4, 10001, 1 move in 0–4.5 s). *Not verified* without detections |
| `DEAD_TIME` 2.1 s paddling at the start of 0140 | yellow, non-blocking. The catalog counts the catch as part of the ride | QA agent: allow ~2 s of catch before the stand |
| `RECORDING_ENDS_MID_ACTION` on 13 reels | true, and reported twice (grey note and yellow finding), the yellow one lowers the score | QA agent prompt: end of recording is expected |

Also observed: three drafts were blocked by the primary-actor policy (`review_required=3`, three active qa_gate re-edit
tasks) while `public.draft_publishability` for this run has only the red-board reel unpublishable
(`final_qa_failed`, `qa_critical:NO_VISIBLE_ACTION`); the long-hair (0094) and patterned (0097/0115) reels are
`publishable=true` with `approval_blocked_reasons=[]`. The business gate reports 13/14 published. Worth a separate look at what `publishable` means next to a policy block.

## 3a. Second fix: the rescued tandem ride ends where the tracker still follows it

Log: `missed-moment check (ADDED): … 12.8-36.7s kind=tandem_ride` (the clip the model saw), `possible missed ride … track
162 13.8-36.6s (moved 0.99 frame widths)`, rescued window `25.8-33.8` in the draft trace, recording 36.7 s, catalog ride
16.9–36.7 s, QA `PREMATURE_CUT @8s` ("cut just before the natural completion").

`missed_moment_rescue.rescue_missed_moments` took the model's end as given. It now moves the end to the recording's end
when the rescued track is seen without a gap longer than `max(1 s, 3 × sampling)` from the model's end to the end of
the recording, still travels (≥ 0.05 frame widths), and the tail is at most 4 s. It is then an observed boundary
(`outcome_end`, `ride_end_evidence=recording_end`, `end_before_track_extension` keeps the model's second). A lost track,
a track standing still, or a tail longer than 4 s leaves the model's end alone. On the run's numbers (33.8 → 36.7 s) the
end meets the catalog's.

Evidence level: `scripts/test_missed_moment_rescue_contract.py` replays these numbers with synthetic tracks (36.7 s
source, track 13.8–36.6 s, model end 33.8 s) and four negatives; it fails on the previous code (`(25.8, 33.8)`). The
run's real detections were not available, so the rule is not validated on the real track 162.

Not fixed: the start. The model started the moment at 25.8 s; the catalog ride starts at 16.9 s, the track at 13.8 s.
The lead-in policy (`extend_to_setup`, ≤ 2 s) cannot close 9 s, and nothing in the log says what happens in 16.9–25.8 s.

## 4. Not changed, proposed

- Tandem rescue start: needs the real detections (and a look at 16.9–25.8 s) to tell paddling into the wave from a ride.
- 0094 long hair: the analyzer's `outcome_end` 22.5 s and track 42 (3.5–23.4 s, no gap) run into the father-and-child
  ride; the catalog ride ends at 13.2 s. The tracker did not separate them.
- 0143 / 0152: the board colour is wrong at the analyzer; a text rule cannot separate them.
- Run the studio's evaluator on every run's `predictions.v1.json` (`ground_truth.pipeline_predictions` and
  `evaluation_runs` are still empty).
