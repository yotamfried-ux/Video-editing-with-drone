# FULL_SPEC_GO readiness — decision record

**Decision (2026-11-02, after the FULL_SPEC implementation pass): `NO-GO`.** The addendum's mandatory data model and algorithms are now implemented and tested on synthetic data: annotation sets and assignments, adjudication, set-scoped identity agreement, physical-action lineage, person merge/split lineage, §8 matching, §9 Jaccard, the §10 evaluation identity, freeze gating, event-scoped primary, and the §18 sport items. The gate still cannot be `GO` because spec §22.3 requires real evidence that only the operator's environment can supply:

| Blocking item | Why it is still open |
|---|---|
| `CATALOG_GO` evidence on real DJI footage, the real R2 token and the backup disk | BLOCKED: operator workstation, see [CATALOG-READINESS](CATALOG-READINESS.md) |
| Output quality: real source vs proxy vs final reel (spec §21.5, ADV-12) | NOT_TESTED: needs an existing real reel; the pipeline is not run without approval |
| Independent annotation on real data (a real second annotator or a delayed blind pass) | NOT_TESTED: the mechanism works; its scientific use has not happened yet |
| Accessibility audit and operator usability walkthrough | NOT_TESTED |

## Known limitations of the implementation (documented, not hidden)
- Set isolation is enforced by the API and UI. One person on one machine can still open the primary screen.
- Accepting an adjudication set does not automatically write the primary Ground Truth revision. The operator applies it through the normal approval flow, which appends a revision and never rewrites one.
- The evaluator does not yet map attributions through the person-lineage graph.
- No metadata or model sport-suggestion producer exists. Only the labeled-suggestion and confirmation mechanism does.

All per-requirement evidence: [REQUIREMENTS-MATRIX](REQUIREMENTS-MATRIX.md) section H.
