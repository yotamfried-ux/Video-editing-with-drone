# Architecture usefulness findings

Classified **only after** observing real execution, per the brief. Categories:
PROVEN REQUIRED · REQUIRED BUT UNPROVEN · DUPLICATIVE/OVERLAPPING · DISCONNECTED ·
LEGACY/CANDIDATE FOR REMOVAL · UNKNOWN.

**Standing caveat.** This campaign could not exercise the upload → pipeline →
CV → edit path at all (BLOCKER-002/003). Most of the product is therefore
**REQUIRED BUT UNPROVEN**, which is a statement about *this campaign's reach*,
not a criticism of the code. Nothing here is a recommendation to delete
anything, and nothing was deleted.

---

## PROVEN REQUIRED — exercised in this campaign, observed working

| Component | Evidence |
| --- | --- |
| `web-api/src/lib/operator-auth.ts` | SEC-01: rejected 10 unauthenticated routes and a wrong secret, constant-time compare, run `35436251541` |
| Operator route surface (`/api/operator/*`) | All ten probed routes deployed, reachable and enforcing auth |
| Vercel production deployment | `dpl_BrGpP43YvLgvitTLBBpKqa9QxKYt` READY at exactly `main` HEAD `356d581` |
| `web-api/src/lib/r2-storage.ts` credentials path | R2 `head_bucket` 200 against bucket `sportreel`; ListObjectsV2 and ListMultipartUploads both functional |
| Supabase service-role access + schema | All queried tables exist and respond; column set enumerated |
| Android app package + launcher activity | Installs from the exact APK and launches on a clean API-35 emulator; `Welcome Back` and Register surfaces reached |
| `pipeline_runs` as a durable state table | 55 real rows with coherent status/stage/error transitions |
| EAS build distribution | `eas build:download` retrieves the exact build id reproducibly across four runs |

## REQUIRED BUT UNPROVEN — central to the product, not reachable this campaign

| Component | Why unproven |
| --- | --- |
| Multipart upload subsystem (7 routes + `source_upload_manifest.ts`, `upload-batch-manifest.ts`) | `source_uploads`, `source_upload_parts`, `upload_batches` are **all empty**; no upload has ever run through it |
| `repository_dispatch` → `pipeline-run.yml` | Wired and readable in source; last actual dispatch was 2026-07-22, none under current `main` |
| Gemini semantic analysis | No run to observe |
| Ultralytics / BoT-SORT perception + `pipeline/required_perception_policy.py` | No run to observe; the mandatory-perception rule could not be tested |
| Decision layer | No predictions produced |
| FFmpeg editor (2160×3840, 30 fps, ≤90 s, silent) | No reel produced; `ffprobe` had no input |
| QA / re-edit layer | Not exercised live; see GAP-008 for historical failure |
| `mobile/modules/sportreel-source-reader` (native SD/USB) | Symbol confirmed present in APK DEX by the prior campaign, but hardware behaviour needs a physical device (BLOCKER-005) |
| Checkout / payments (Stripe, Meshulam), webhooks, protected media tokens | Entirely outside this campaign's executed scope |
| `draft_publishability.ts`, `delivery_runs` | Tables empty; logic never exercised |

## DISCONNECTED — present but not carrying its intended signal

| Component | Finding |
| --- | --- |
| `pipeline_runs.github_run_id` | The column exists and is **NULL in all 55 rows**. Nothing ever writes it. It is the natural home for the correlation identity the brief mandates, and it is inert. (GAP-004) |
| `pipeline_runs.input_files` | Empty on all 55 rows despite `pipeline/start/route.ts` explicitly inserting `input_files: readyBatch.inputManifest`. Consistent with no run having gone through the batch-manifest path. (GAP-009) |
| `pipeline_runs.output_drafts` | Empty on all 34 `succeeded` rows. (GAP-009) |
| `actionsUrl()` in `pipeline/start/route.ts` | Computes a constant workflow-page URL, so `github_run_url` carries no per-run information. Functioning as written; the design cannot correlate. (GAP-004) |

## OVERLAPPING — two storage backends live side by side

`pipeline-run.yml` selects between Google Drive and R2 via
`STORAGE_BACKEND: ${{ vars.STORAGE_BACKEND || secrets.STORAGE_BACKEND || 'drive' }}`,
with **`drive` as the default**, and carries credential-writing branches for
both. The evidence shows a half-completed migration:

- All 55 historical runs are Drive-era (one failed with *"The user's Drive
  storage quota has been exceeded"*).
- The R2 bucket has the full prefix layout created 2026-07-04 but contains no
  media.
- The R2-side Supabase tables are all empty.

So both backends are wired, and **neither currently holds a produced reel**.
Classified OVERLAPPING rather than legacy because I could not establish which is
intended to be authoritative today — that needs your answer, and it directly
affects how GAP-005 should be read.

## LEGACY / CANDIDATE FOR REMOVAL

**None proposed.** Nothing observed in this campaign justifies removal, and per
the brief I did not delete or restructure anything during validation. Two items
are flagged only as questions for you, not recommendations:

- `debug.py` at repo root is 217 KB, which is unusual for a tracked file; its
  role was not examined.
- Several near-identical stale branches exist on the remote
  (`audit/state-recon`, `-2`, `-3`, `-doc`, `-final`, `audit/recon-doc`,
  `audit/reconcile-pipeline-state`, `-2` all point at the same commit
  `c43afbf`). Branch hygiene only; no code implication.

## UNKNOWN

The Discover/marketplace surface, analytics, notifications, crash reporting, the
support flow, and the Apps Script integration were not touched by any executed
experiment and no evidence was gathered about them either way.
