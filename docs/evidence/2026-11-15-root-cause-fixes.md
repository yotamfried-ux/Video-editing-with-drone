# Root-cause fixes after the deep verification of 2026-11-15

Source: `docs/evidence/2026-11-15-verified-deep-root-causes.md` (PR #387). Evidence used here: the diagnostics
of run 43710581656 (the document states run 43725044948 has the same 25 shots and tracks), the code paths the
document names, and offline replays. No video was watched.

## Fixed, with the mechanism that was wrong

| # | Mechanism (confirmed in code) | Fix | Proof |
|---|---|---|---|
| M2 | A cluster was marked `_visual_verified` without any image being checked, in two places: `_merge_compatible_structured_clusters` set it after merging on text descriptions, and `_verify_multi_clusters` (and the `identity_failsafe` wrapper that production uses) skipped the image verifier when `_cluster_structured_verified` found the descriptions agreeing. `real_identity_gate` then passed the cluster as `visual_verified_per_source_tracks` | The flag is set only where the image verifier answered "same person". A text merge clears it and is labelled `_structured_merge`. The verifier always runs for an unconfirmed multi-source cluster, and runs again after the second text merge | Contract test: red on `main` ("a merge on text descriptions must not be marked visually verified"), green here. Under the real bootstrap order the 0143 + 0152 pair with agreeing descriptions and no images is split, not confirmed |
| M2 | A multi-source cluster the gate kept as `kept_together_unconfirmed` stayed publishable | `qa_gate_block_reasons` reads `identity_gate.decision`; such a draft is recorded `IDENTITY_UNCONFIRMED` and is not publishable, through the same path as a QA-gate block | Contract test |
| M4 | No event had a canonical id (0 of 25 EDL shots); lineage was inferred from source and window, which breaks when a stage revises the window | `pipeline/event_identity.py`: `event_uid` assigned in `analyze_session` from source, person, the analyzer's window and type; kept through window changes with the original `analyzer_window`; written to the EDL. An event created later (a rescued moment) gets one at clip time, marked `assigned_late` | Contract test: stable across a window change and across a re-run; EDL contract still passes |
| M5 | `close_queued_reprocess` set **every** `queued` request to `done`, and only when a note existed. Requests of other runs and failed re-edits were closed as repaired | The run remembers the requests it re-queued and closes exactly those: `done` only if it produced a publishable draft from that request's sources, otherwise `reprocessed_unverified`. A call without ids changes nothing | Contract test with a recording fake: every update names one id and filters on `queued` |
| M1 | Admission was a bare boolean | `classify_event_eligibility`: ELIGIBLE / INELIGIBLE / UNCERTAIN with the basis, stamped on the event. Admission itself is unchanged | Contract test |

## Second pass: four gaps found in review of this PR

| # | Gap | Fix | Proof |
|---|---|---|---|
| P0 | `real_identity_gate._stable_track` passed a multi-source cluster when every source had the same tracker number. Tracker ids are numbered per video, so two different surfers can both be `t7`. The existing contract test asserted that this case passes | A shared track id is evidence only inside one source. Across sources the reason is `same_track_id_across_sources_is_not_evidence` and the cluster is unconfirmed (blocked) or split | `test_real_identity_gate_contract.py`: the old assertion is replaced; red on the previous commit |
| P0 | `_verify_merge_candidates` compared one image of each cluster and then marked the whole merged cluster `_visual_verified`, also when a side had several members that were never shown | The pair check confirms only a merge of two single appearances. Any larger merge is labelled `_merge_check_pair_only`, loses the flag, and the whole cluster goes through the image verifier, which now runs once more at the end of post-processing | `test_root_cause_fixes_contract.py`: red on the previous commit |
| P1 | A reprocess request was `done` when *any* publishable reel came from one of its sources, although a source can hold several athletes | A request is verified only when the run produced reels from its sources and **every** reel using any of them is publishable. One blocked reel from those sources leaves it `reprocessed_unverified` | Contract test with two athletes sharing a source |
| P1 | `event_uid` was built from the file name and windows rounded to two decimals: two files with one name, or two events with equal rounded windows, collided | The id is built from the source's content SHA-256, the person and the event's ordinal within that person, plus a schema version (`v2`). No timestamp takes part. An event created later uses its exact window, type and track | Contract test: same name with different bytes differs, same bytes under another name matches, equal rounded windows differ, stable across a window change and a re-run |

Limit of the reprocess fix, stated plainly: it does not bind a request to one athlete, one defect and one output
hash. Athlete ids are re-derived on every run and a request carries only a draft name, so the rule used is the
stricter one above. It can leave a request unverified because another athlete in the same source is blocked; it
cannot close a request whose own athlete is still blocked.

## A correction to what I reported earlier

After run 43710581656 I wrote that three independent views (analyzer, clustering model, visual verifier) agreed
that 0143 and 0152 are one person. That was wrong about the third: the `confirmed_by_visual_verifier` in the
trace came from the text shortcut above. Two model views agreed; the image check did not run for that pair. With
this change it runs, so the next run gives a real answer.

## Checked against the data and not changed

| Case | What the data shows |
|---|---|
| 0151 cut at 6.13 s | The document's hypothesis is that the lost track 10002 continues as 10003. The sidecar refutes it: 10003 exists from 0.03 s and stays 0.16–0.36 of the frame away from 10002 the whole time. It is another person. 10002 ends at 5.14 s mid-frame and no track starts near that point; the tracks that begin after 6.2 s enter at the frame edge. The cut at track end + 1 s is what the evidence supports, and the reel is withheld as `RIDE_BOUNDARY_UNCERTAIN`. Extending to the analyzer's 7.4 s would show frames where the athlete is not tracked |
| 0095, 0155 | The analyzer describes both as real rides ("making a smooth turn before falling", "pops up, performs a brief turn, and then falls") with scores 9 and 7. Included rides are described the same way (0160, 0165, 0115 also end in a fall). No rule on the model's text separates them without copying the catalog's labels into inference. This is a disagreement between the model and the human label and needs adjudication on video |
| 0108 tail | The analyzer's own window ends at 9.0 s; the catalog ends at 6.82 s. Same kind of disagreement |
| 0094 two athletes | Overlap in time is not proof of a wrong person in frame; needs track overlays on video |

## Not done

- A frozen-GT evaluator that writes `evaluation_runs` in production: it writes production data and needs approval.
- Actor-fenced intervals and appearance-based track stitching (M3): no evidence here that a specific stitch was
  wrong, and no video to validate a change against.
- Binding a reprocess request to one athlete, one defect and one output hash (M5, full form): needs a
  persistent athlete id on the request. See the limit stated above.

## What the next run should show

`IDENTITY_UNCONFIRMED` or a split for 0143 + 0152 if the image verifier does not confirm them; `event_id` on
every EDL shot; no "confirmed_by_visual_verifier" without a verifier call.
