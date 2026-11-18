# Independent holdout H1 — plan, tooling and blocker

**Status: BLOCKED. No independent footage exists.**

Measured on 2026-11-18 from production `source_uploads`, read-only:
- the only drone sources are the **24 GT-v1 sources** (20 filmed on 2026-07-20, 4 on 2026-07-24);
- the other 5 uploads are tiny non-drone test files.

The 24 GT-v1 sources are development data. They are **not** reused as a holdout.

## What is ready (cycle 12)

| Piece | Where |
|---|---|
| Freeze, lock and evaluation tool | `scripts/holdout_qualification.py` |
| Its contract (synthetic fixtures; H1–H7 in CI) | `scripts/test_holdout_qualification_contract.py` |
| Pre-registered metrics template | `evaluation/qualification/holdout_h1_metrics.json` |
| Isolated real-footage run | `pipeline-qualification-run.yml` (namespace, LLM cap, production fingerprint) |
| Labelling | existing annotation studio; same GT schema as GT-v1 |

**What `freeze` checks and records:**
- It refuses any source that appears in GT-v1 or in any listed development SHA set.
- Every source must have a reviewed range and condition tags.
- A budget cap and pre-registered thresholds are required.
- The lock is immutable and records the code SHA, the sport-profile threshold digest, the prompt-source digests, the
  source hashes and the cap.
- `verify-lock` fails if any threshold or prompt changes after the freeze.

**What `evaluate` reports:**
- normalised rates: FULL, ≥95 %, wrong start and wrong end per ride, and missing seconds per ride-minute;
- a breakdown by athlete, lighting, distance, crowding, camera motion, difficulty and action type;
- the pre-registered pass/fail table.

## What is needed from you

1. **Footage:** new drone surf footage from a **different day**, ideally 15–30 sources and at least 30 rides, with
   people not in GT-v1 where possible. It should cover:
   - early paddling;
   - fast take-offs;
   - waiting before the wave (negative onset cases);
   - small riders in frame;
   - speed changes;
   - several people in frame;
   - occlusions;
   - drone orbit or pan;
   - short and long rides;
   - failed attempts (validity negatives).
2. **Labelling** in the annotation studio:
   - performer;
   - include and exclude windows;
   - start and end;
   - exclusion reason (failed take-off, no ride established…);
   - an uncertain flag and an annotator note.

   Condition tags per source go in `conditions.json`.
3. **Freeze** (in this order, before any candidate run):

   ```
   python scripts/holdout_qualification.py freeze --gt holdout_gt.json --conditions conditions.json \
          --id H1 --out-dir evaluation/ground_truth/holdout/H1 --budget-cap 0.40 \
          --metrics evaluation/qualification/holdout_h1_metrics.json
   ```

4. **Run the locked candidate** in an isolated paid run under the cap. Then:
   - `verify-lock`, then `evaluate`;
   - decode and view the MP4s for the onset cases (waiting cases must not open stationary).

**If H1 fails:** fixes are developed on a separate development split. A new, untouched holdout (H2) is needed to
qualify them. H1 is never re-used for tuning.
