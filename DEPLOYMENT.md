# SportReel — Deployment Guide

This guide covers taking SportReel from source to an operational app-pipeline system.

The production architecture has these layers:

```text
Operator mobile app
  -> web-api on Vercel
  -> GitHub Actions workflows
  -> Python pipeline and delivery scripts
  -> Google Drive folders + Supabase tracking tables
  -> Review, Delivery, Discover, checkout, and app status screens
```

The mobile app is a control surface. Do not move Python, FFmpeg, Gemini, Drive moves, or other heavy processing into mobile code.

---

## 0. What's already provisioned / expected

| Piece | Status / purpose |
|---|---|
| Supabase project (`bcndgmymnismbxvdeetc`) | Live project used by web-api, mobile RLS flows, and the Python pipeline. |
| Supabase migrations | Live schema plus migrations in `supabase/migrations/`. Apply new migrations through the migration workflow or Supabase SQL editor. |
| Storage buckets | Private buckets for reel assets and athlete profile assets. |
| `web-api` | Next.js API layer deployed from the `web-api` root directory on Vercel. |
| `mobile` | Expo app for athlete/user flows and the hidden operator console. |
| Python pipeline | Runs in GitHub Actions or locally for development; writes Drive/Supabase state. |
| Google Drive folders | Durable pipeline state for RAW, PROCESSED, REVIEW, APPROVED, preview, and pending-payment handoff. |
| GitHub Actions | Dispatch target for pipeline, delivery, mobile checks, and Supabase migrations. |

---

## 1. External accounts and credentials

These require identity, billing, or dashboard setup:

| Service | Why | Required values |
|---|---|---|
| Stripe | Discover checkout and payment completion | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, publishable key for mobile |
| Meshulam | Bit/wallet payments where supported | API key, user ID, webhook secret |
| Cloudflare Stream | Stream hosting / protected playback | Account ID, Stream API token, customer code |
| Google Cloud | Drive access and service account JSON | `GOOGLE_SERVICE_ACCOUNT_JSON`; Drive API enabled |
| GitHub | Dispatch workflows from operator API / Apps Script | Dispatch token scoped to this repository |
| Expo / Apple / Google Play | Mobile builds and store submission | EAS account and store credentials |
| Supabase | DB, auth, storage, service-role API access | URL, anon key, service-role key, DB URL for migrations |

The Supabase service-role key is used only by trusted server/pipeline contexts: Vercel web-api and GitHub Actions pipeline jobs. Do not put it in mobile code.

---

## 2. Deploy the API layer: `web-api` -> Vercel

The Vercel project root directory must be `web-api`.

### Required Vercel environment variables

```bash
SUPABASE_URL=https://bcndgmymnismbxvdeetc.supabase.co
SUPABASE_SERVICE_KEY=<service_role secret>

OPERATOR_SECRET=<shared operator secret entered once in the mobile operator settings>
UPSTASH_REDIS_REST_URL=<optional rate-limit Redis URL>
UPSTASH_REDIS_REST_TOKEN=<optional rate-limit Redis token>

GITHUB_REPO=yotamfried-ux/Video-editing-with-drone
GITHUB_DISPATCH_TOKEN=<fine-grained token for repository/workflow dispatch>

GOOGLE_SERVICE_ACCOUNT_JSON=<single-line service account JSON>
RAW_FOLDER_ID=<Drive RAW folder id, required by /api/operator/upload>
REVIEW_FOLDER_ID=<Drive REVIEW folder id>
APPROVED_FOLDER_ID=<Drive APPROVED folder id>

CLOUDFLARE_ACCOUNT_ID=<...>
CLOUDFLARE_STREAM_API_TOKEN=<...>
CLOUDFLARE_CUSTOMER_CODE=<...>

STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
MESHULAM_API_KEY=<...>
MESHULAM_USER_ID=<...>
MESHULAM_WEBHOOK_SECRET=<...>

RESEND_API_KEY=<...>
RESEND_FROM_EMAIL=<...>
NEXT_PUBLIC_APP_DOMAIN=sportreel.app
```

Use `web-api/.env.example` as the exact API-side checklist.

### Webhooks

Register these after the first Vercel deployment:

| Provider | Current endpoint | Events / notes |
|---|---|---|
| Stripe Checkout | `https://<deployment>/api/payments/webhook` | `checkout.session.completed`, `checkout.session.expired`. This is the current Discover checkout path backed by `purchases`. |
| Stripe legacy payment-intent route | `https://<deployment>/api/webhooks/stripe` | Existing legacy handler for `payment_intent.succeeded`; keep only while legacy payment-intent clients need it. |
| Meshulam | `https://<deployment>/api/webhooks/meshulam` | Meshulam success callbacks. |

---

## 3. Mobile app configuration

`mobile/.env` should include:

```bash
EXPO_PUBLIC_SUPABASE_URL=https://bcndgmymnismbxvdeetc.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=<anon key>
EXPO_PUBLIC_API_BASE_URL=https://<vercel deployment>
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_...
EXPO_PUBLIC_APP_DOMAIN=sportreel.app
```

Build and submit through EAS:

```bash
cd mobile
npm ci
npm run type-check
npx eas-cli@latest login
eas init
eas build --platform all --profile preview
eas build --platform all --profile production
eas submit --platform ios
eas submit --platform android
```

Store requirements:

- Privacy Policy URL, for example `https://sportreel.app/privacy`.
- Face/biometric disclosure if app-store review requires it.
- External payment disclosure for Stripe/Meshulam flows.
- App Review note explaining the hidden operator section and how reviewers can access it.

---

## 4. Pipeline and delivery secrets for GitHub Actions

Add these under **Settings -> Secrets and variables -> Actions**:

| Secret / variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini highlight analysis. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Drive API access. |
| `DRIVE_USER_TOKEN_JSON` | Operator OAuth token required for owner-file uploads/moves. |
| `RAW_FOLDER_ID` | Incoming footage queue. |
| `PROCESSED_FOLDER_ID` | Verified archive for processed originals. |
| `REVIEW_FOLDER_ID` | Draft reels awaiting operator approval. |
| `APPROVED_FOLDER_ID` | Approved reels ready for delivery. |
| `PREVIEW_FOLDER_ID` | Optional watermarked preview handoff. |
| `PENDING_PAYMENT_FOLDER_ID` | Optional full reel handoff before payment. |
| `OWNER_EMAIL` | Operator notification recipient. |
| `NOTIFY_EMAIL` | Optional fallback client notification recipient. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Durable tracking rows and publishing state. |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_STREAM_API_TOKEN` / `CLOUDFLARE_CUSTOMER_CODE` | Stream upload/playback integration. |
| `APP_DOMAIN` | Public app/web domain used in delivery links. |
| `SENTRY_DSN` | Optional pipeline observability. |

Pipeline environment behavior is defined in `config/settings.py`.

---

## 5. Drive -> GitHub Actions automation

Production-style pipeline runs should be triggered through the app/API boundary or Drive watcher, not by asking mobile to process videos.

```text
Operator uploads footage or RAW receives footage
  -> Apps Script watcher or operator API dispatch
  -> `.github/workflows/pipeline-run.yml`
  -> `scripts/run_tracked.py` / Python pipeline
  -> Drive move + Supabase status rows
  -> operator Pipeline screen
```

### Apps Script watcher

1. In `apps_script/trigger.gs`, set `RAW_FOLDER_ID` and repository settings.
2. Create a GitHub token that can trigger dispatches.
3. Apps Script -> Project Settings -> Script Properties -> add `GITHUB_TOKEN=<token>`.
4. Run `setupTrigger()` once and authorize.

The watcher waits for uploads to settle before dispatching, so multi-clip sessions are processed as one logical run.

### Manual and operator-triggered runs

- Operator app run button: `POST /api/operator/pipeline/start`.
- Legacy alias: `POST /api/operator/pipeline/run` is compatibility-only and governed by `docs/legacy-route-policy.md`.
- GitHub UI: **Actions -> Run Pipeline -> Run workflow**.
- Reset/rerun: `POST /api/operator/pipeline/reset` or `python scripts/reset_and_rerun.py` locally for diagnostics.

---

## 6. Drive state contract

Drive folder membership is source-of-truth operational state. `processed.json` is runner cache only.

Required folder behavior:

1. Footage starts in RAW.
2. The pipeline processes a session and writes draft reels to REVIEW.
3. Originals are moved RAW -> PROCESSED only after the move can be verified.
4. Operator approval moves/records delivery into APPROVED / delivery handoff.
5. Optional preview and pending-payment folders support the Discover/payment handoff.

See `docs/drive-move-contract.md` and `docs/operator-pipeline-contract.md` for the exact invariants.

---

## 7. Supabase migrations

New migrations live under `supabase/migrations/`.

Required GitHub secret:

| Secret | Value |
|---|---|
| `SUPABASE_DB_URL` | Postgres connection string with SSL, for example `postgresql://postgres:<DB_PASSWORD>@db.<PROJECT_REF>.supabase.co:5432/postgres?sslmode=require` |

Apply through **Actions -> Run Supabase Migration -> Run workflow**:

1. Set `migration` to the filename, for example `20260702_set_reel_expiry_default.sql`.
2. Run with `confirm_apply=DRY_RUN` first.
3. Rerun with `confirm_apply=APPLY` after reviewing the SQL.

The workflow validates the filename and uses `psql -v ON_ERROR_STOP=1` so SQL errors stop the job.

---

## 8. Verification checklist

### API / Vercel

- Vercel deploy succeeds from `web-api`.
- `GET /api/sessions` returns 200.
- `GET /api/operator/pipeline/status` rejects missing/invalid operator secret.
- A valid operator request to `GET /api/operator/pipeline/status` returns the current live status.

### Operator app / pipeline

- `POST /api/operator/pipeline/start` returns `pipeline_run_id` or an actionable dispatch error.
- `GET /api/operator/pipeline/runs` shows the durable run row.
- Upload footage smoke loop passes: see `docs/upload-to-run-smoke.md`.
- Reset/rerun and re-edit responses display returned run IDs, not stale “next run” copy.

### Review / delivery

- Draft approval calls `POST /api/operator/drafts/approve`.
- Success is shown only when `delivery_started: true`.
- `GET /api/operator/delivery-status` shows the matching delivery run.

### Discover / payments

- Apply new Discover/payment migrations before relying on checkout.
- Run `docs/discover-reels-smoke-loop.md` in Supabase/Stripe Sandbox.
- `POST /api/checkout/{token}` returns a checkout URL for an active, unexpired reel.
- Stripe Checkout webhook to `/api/payments/webhook` marks the purchase paid and the reel sold.

### Mobile checks

- Any mobile change must pass `.github/workflows/mobile-check.yml`.
- Local validation: `cd mobile && npm ci && npm run type-check`.

---

## 9. Operational docs to keep aligned

- `README.md` — short current overview.
- `docs/operator-pipeline-contract.md` — route/workflow/tracking contract.
- `docs/operator-api-boundary.md` — privileged operator API boundary.
- `docs/operator-api-contracts.md` — operator API response contracts.
- `docs/legacy-route-policy.md` — compatibility alias policy and removal conditions.
- `docs/drive-move-contract.md` — Drive state invariant.
- `docs/upload-to-run-smoke.md` — Upload footage smoke loop.
- `docs/discover-reels-smoke-loop.md` — Discover/checkout smoke loop.
- `docs/app-pipeline-audit.md` — readiness gaps and repair order.

When a route, workflow, tracking table, or Drive folder behavior changes, update the focused contract first and then keep this guide as the deployment index.
