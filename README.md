# SportReel — video editing and delivery platform

SportReel turns raw drone footage into reviewable, purchasable sport reels. The project is no longer only a local Python Drive pipeline: it is an app-controlled production system with a mobile operator surface, a Next.js API boundary, GitHub Actions orchestration, Python video processing, Google Drive state, Supabase tracking, delivery approval, payments, and Discover.

## Current architecture

```text
Operator mobile app
  -> Next.js web-api operator routes
  -> GitHub Actions workflows
  -> Python pipeline / delivery scripts
  -> Google Drive folders + Supabase tracking tables
  -> mobile status screens, Review, Delivery, and Discover
```

Public athlete/viewer flows use the mobile app and web-api for Discover, reel checkout, payment webhooks, and protected download/streaming flows. Privileged operator flows must go through the operator API boundary and `operatorFetch`; the mobile app is a control surface only and must not run Python, FFmpeg, Gemini, or other heavy processing locally.

## Main components

| Area | Path | Purpose |
|---|---|---|
| Operator / athlete mobile app | `mobile/` | Expo app for operator controls, Review, Pipeline status, support, analytics, athlete auth/profile, Discover, checkout, and reel viewing. |
| API layer | `web-api/` | Next.js API routes for operator actions, checkout, webhooks, analytics, Discover sessions, signed URLs, and service-role operations. |
| Pipeline | `pipeline/`, `scripts/run_tracked.py`, `run.py` | Python, Gemini, FFmpeg, Drive, Cloudflare, Supabase, and QA/editing logic. Runs in GitHub Actions or locally for development. |
| Delivery | `deliver.py`, `services/delivery.py`, `.github/workflows/deliver.yml` | Moves approved drafts through delivery/payment handoff and records durable delivery runs. |
| Drive automation | `apps_script/`, `.github/workflows/pipeline-run.yml` | Watches RAW uploads and dispatches pipeline runs once uploads settle. |
| Database and diagnostics | `supabase/` | Migrations, diagnostics, tracking tables, Discover smoke SQL, and payment/pipeline state. |
| Contracts and audits | `docs/` | Operational contracts, smoke loops, audit state, and focused repair notes. |

## Supported operator actions

Use `docs/operator-pipeline-contract.md` as the source of truth for operator routes and tracking behavior. Current high-level actions are:

| Action | Current route / workflow |
|---|---|
| Run pipeline now | `POST /api/operator/pipeline/start` -> `.github/workflows/pipeline-run.yml` |
| Upload footage | `POST /api/operator/upload`, then `POST /api/operator/pipeline/start` |
| Reset and rerun | `POST /api/operator/pipeline/reset` -> `.github/workflows/pipeline-run.yml` |
| Send draft/reel to re-edit | `POST /api/operator/reprocess` -> `.github/workflows/pipeline-run.yml` |
| Approve draft for delivery | `POST /api/operator/drafts/approve` -> `.github/workflows/deliver.yml` |
| Read pipeline status | `GET /api/operator/pipeline/status` |
| Read run history | `GET /api/operator/pipeline/runs` |
| Read delivery status | `GET /api/operator/delivery-status` |
| Discover diagnostics | `GET /api/operator/discover-diagnostics` |

`POST /api/operator/pipeline/run` exists only as a backward-compatible alias for older app builds. New operator code should use `/api/operator/pipeline/start`.

## Drive state model

Drive folder membership is operational state. The current flow uses:

- `RAW_FOLDER_ID` — incoming footage waiting to run.
- `PROCESSED_FOLDER_ID` — originals after verified RAW -> PROCESSED move.
- `REVIEW_FOLDER_ID` — generated drafts awaiting operator approval.
- `APPROVED_FOLDER_ID` — approved reels ready for delivery.
- `PREVIEW_FOLDER_ID` — optional watermarked previews.
- `PENDING_PAYMENT_FOLDER_ID` — optional full reels awaiting payment handoff.

`processed.json` is runner cache only. It must not be treated as the source of truth for processed footage. See `docs/drive-move-contract.md`.

## Getting started for development

### API

```bash
cd web-api
npm install
npm run build
```

Configure `web-api/.env.example` values in Vercel or a local `.env.local` equivalent. Operator routes require `OPERATOR_SECRET`; GitHub dispatch requires `GITHUB_DISPATCH_TOKEN` and `GITHUB_REPO`.

### Mobile

```bash
cd mobile
npm ci
npm run type-check
```

Mobile PRs are guarded by `.github/workflows/mobile-check.yml`. The mobile app may read end-user auth/profile/RLS data directly through Supabase, but privileged operator data must go through the API boundary.

### Pipeline

```bash
pip install -r requirements.txt
python run.py
```

Local pipeline runs are for development and diagnostics. Production-style operator runs should be dispatched through the API and GitHub Actions so `pipeline_runs`, `pipeline_status`, Drive moves, and app status screens stay aligned.

## Deployment and operations

Use `DEPLOYMENT.md` for environment setup, Vercel, EAS, GitHub Actions, Supabase migrations, Drive automation, webhooks, and verification checklists.

Important focused docs:

- `docs/operator-pipeline-contract.md` — app/API/workflow contract.
- `docs/operator-api-boundary.md` — privileged operator API boundary.
- `docs/drive-move-contract.md` — RAW -> PROCESSED move invariant.
- `docs/delivery-approval-note.md` — Review approval and delivery feedback behavior.
- `docs/upload-to-run-smoke.md` — upload-to-run smoke loop.
- `docs/discover-reels-smoke-loop.md` — Discover -> Checkout smoke loop.
- `docs/app-pipeline-audit.md` — current readiness gaps and repair order.

## Current readiness focus

The app-pipeline work is tracked in `docs/app-pipeline-audit.md`. Keep future PRs narrow, update the audit when a gap changes status, and validate the relevant contract before merging.

## License

MIT — built for drone operators and sports content creators.
