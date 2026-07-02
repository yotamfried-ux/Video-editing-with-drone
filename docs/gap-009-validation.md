# GAP-009 validation notes

Before merge:

1. Review the PR diff manually.
2. Confirm the PR is not Draft.
3. Confirm `mergeable: true`.
4. Confirm Mobile Check passes because this PR changes `mobile/**`.
5. Confirm Vercel preview succeeds.
6. Check CodeRabbit if available. If it is rate-limited, use self-review.
7. After merge, check the main commit status to confirm Vercel deploy on `main` succeeds.

Self-review focus:

- Mobile remains a control surface only.
- Privileged reads still go through `operatorFetch`.
- The new contract file is type-only.
- Reels re-edit now uses the returned `pipeline_run_id`.
