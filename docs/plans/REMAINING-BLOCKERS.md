# SportReel — remaining blockers (2026-11-16)

Each item names the exact operation, who must act, and what it unblocks. Code-verifiable work is done on PR #390.

## Owner approval required

| # | Operation | Why | Unblocks |
|---|---|---|---|
| 1 | Merge PR #390 | all code of this mandate | everything below |
| 2 | One controlled pipeline run on the frozen 24-source set (paid) | no real evidence on the fixed code | GATE A, C, D, E, F, G; first `batch_qualification.json` and `runtime_policy_registry.json` |
| 3 | Migration: store `output_qualification.proof_digest` (and revision) on `draft_publishability`, checked by the approval API | the server currently refuses on technical issues, not on the proof itself | GATE F (stale-proof protection) |
| 4 | Persist offline evaluations to `ground_truth.evaluation_runs` (or keep as CI artifacts only) | evaluation results stay in files today | RC-08 persistence |
| 5 | CI read-only access to the frozen dataset export (`SPORTREEL_GT_EVAL_FILE`) | attach the GT benchmark to every run's batch verdict | RC-07/RC-08 automation |

## Visual adjudication required (a person, on footage)

0143 + 0152 (merge), 0097 + 0115 (split), 0095 and 0155 (eligibility), 0108 (tail), 0094 (handoff), 0115 / 0104 /
0152 (late starts), 0151 (conservative cut, distinct tracks 10002/10003). Package: source SHA and frame windows in
`docs/evidence/CONTROLLED-E2E-QUALIFICATION-REPORT.md` §2.

## Human labelling required

Independent holdout (RC-10): attributed box verification (reviewer + time) on difficult windows; until then every
per-frame tracking accuracy claim is `UNVERIFIED_GT`.

## Known risk

The new fail-closed qualification withholds any shot without measured evidence (tracker binding, CV activity,
validated actor span, lineage). If a production stage does not supply one of these fields, valid rides will be
withheld for review (never lost, never published). The controlled run must report withheld parts by
`qualification:` code before any threshold is changed.

## Historical backlog

202 rows (185 `qa_blocked`, all `attempt_count` 0; 13 `cancelled`; 3 `source_not_found`; 1 `done`) are unchanged.
Legacy rows can never close as `done` automatically; the operator API now pages and summarizes them.
