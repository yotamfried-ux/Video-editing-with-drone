# Owner actions prepared in cycle 12 (NOT executed)

Each item below changes production behaviour or reference data. Each needs your explicit approval and was **not**
performed.

## 1. Make the two identity decisions live in production

**Today:**
- The working decisions are used **only** in isolated qualification runs. They live in
  `evaluation/qualification/identity_working_decisions.json`, which is marked `"qualification_only": true`.
- `pipeline.identity_review.load_decisions` ignores that file outside a qualification run.
- The production decision file (`evaluation/identity_reviews/decisions.json`) does not exist.

**The action:** create `evaluation/identity_reviews/decisions.json` with:

```json
{
  "schema": "sportreel.identity_review_decisions.v1",
  "decisions": [
    {"request_id": "758fe7783e9c16dc579f0c951a556fc68b7dd94dea78ca9642cce7ed98873e60", "decision": "APPROVED",
     "reviewer": "<owner name>", "decided_at": "<ISO time>",
     "note": "0097 + 0115 (person_A, sources 548cf4ff..., b62c8aa0...) are one athlete"},
    {"request_id": "7b2a6964427f5b96fe87311e310b01ae1739f59852b892bac42519024bd966b3", "decision": "REJECTED",
     "reviewer": "<owner name>", "decided_at": "<ISO time>",
     "note": "0074 + 0151 (person_A, sources f6ac72f8..., e01a614d...) are two people"}
  ]
}
```

Merge it to `main` through a reviewed PR.

**Scope:**
- Each decision is bound to the exact source content hashes and people.
- It does not extend to any similar pair. This is tested by W7 in
  `scripts/test_identity_working_decisions_contract.py`.

## 2. PA-01: policy for uncatalogued people

Approve or amend `UNCATALOGUED-PERSON-POLICY.md`. No code change is needed for the current behaviour.

## 3. PA-03: 0094 end boundary (GT correction proposal, GT-v1 unchanged)

See `PA-03-0094-BOUNDARY-EVIDENCE.md`.
- **The visual evidence:** the athlete keeps riding the whitewater until about 15.0–15.3 s and goes prone at about
  15.5 s.
- **GT-v1:** ends the include at 13.23 s, when the wave breaks.
- **If you decide** that whitewater riding counts, create a **new** GT version. GT-v1 is never edited. The new
  version would end 9524ac02's include at about 15.2 s, and all scores would be reported on both versions.

## 4. Merge policy

Do not merge PR #391 to `main` until you approve. The cycle-12 changes could be split into small PRs:
- PA-13 draft ledger;
- identity rejection precedence;
- scorecard and holdout tooling.

Each has its own contracts.
