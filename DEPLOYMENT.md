# SportReel — Deployment Guide

This guide covers taking SportReel from source to a live, store-ready product.
Three cloud layers plus the mobile app. Supabase is already provisioned and live.

```
Supabase (LIVE)  →  web-api on Vercel  →  Mobile app (EAS → App Store / Play)
                         ↑
                  Stripe · Meshulam · Cloudflare Stream
```

---

## 0. What's already done

| Piece | Status |
|---|---|
| Supabase project (`bcndgmymnismbxvdeetc`) | **Live** — URL `https://bcndgmymnismbxvdeetc.supabase.co` |
| DB schema (8 tables + RLS + pgvector) | **Applied** |
| Storage buckets (`reels`, `athlete_photos`) | **Created** (private) |
| Cron jobs (48h expiry, 7d cleanup) | **Scheduled** |
| `web-api` (Next.js 15) | Code complete, builds clean |
| `mobile` (Expo SDK 52) | Code complete |
| Python pipeline integrations | Code complete |

---

## 1. Accounts you must create (cannot be automated)

These require your identity/payment, so only you can create them:

| Service | Why | What to grab |
|---|---|---|
| **Stripe** | Card payments | `sk_live_…` (secret), `pk_live_…` (publishable), `whsec_…` (webhook secret) |
| **Meshulam** | Bit wallet (Israel) | API key, webhook secret |
| **Cloudflare** | DRM video streaming (Stream is a paid add-on) | Account ID, Stream API token, customer code |
| **Apple Developer** | App Store ($99/yr) | Apple ID, App Store Connect app ID |
| **Google Play** | Play Store ($25 once) | Service account JSON |
| **Expo (EAS)** | Builds the app | free account |

The **Supabase service_role key** already exists in your dashboard:
Settings → API → `service_role` secret. Needed by `web-api` and the pipeline.

---

## 2. Deploy the backend (web-api → Vercel)

Done from this repo. Root directory is `web-api`.

### Environment variables (set on the Vercel project)

```
SUPABASE_URL=https://bcndgmymnismbxvdeetc.supabase.co
SUPABASE_SERVICE_KEY=<service_role secret>
CLOUDFLARE_ACCOUNT_ID=<…>
CLOUDFLARE_STREAM_API_TOKEN=<…>
CLOUDFLARE_CUSTOMER_CODE=<…>
STRIPE_SECRET_KEY=sk_live_…
STRIPE_WEBHOOK_SECRET=whsec_…
MESHULAM_API_KEY=<…>
MESHULAM_WEBHOOK_SECRET=<…>
```

### Webhooks to register after the first deploy

- Stripe → `https://<deployment>/api/webhooks/stripe` (event: `payment_intent.succeeded`)
- Meshulam → `https://<deployment>/api/webhooks/meshulam`

---

## 3. Pipeline `.env` additions

```
SUPABASE_URL=https://bcndgmymnismbxvdeetc.supabase.co
SUPABASE_SERVICE_KEY=<service_role secret>
CLOUDFLARE_ACCOUNT_ID=<…>
CLOUDFLARE_STREAM_API_TOKEN=<…>
CLOUDFLARE_CUSTOMER_CODE=<…>
APP_DOMAIN=sportreel.app
```

Install the face-matching dependency: `pip install face_recognition` (needs dlib).

---

## 4. Mobile app (EAS → stores)

```
mobile/.env
  EXPO_PUBLIC_SUPABASE_URL=https://bcndgmymnismbxvdeetc.supabase.co
  EXPO_PUBLIC_SUPABASE_ANON_KEY=<anon key>
  EXPO_PUBLIC_API_BASE_URL=https://<vercel deployment>
  EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_…
  EXPO_PUBLIC_APP_DOMAIN=sportreel.app
```

```bash
cd mobile
npx eas-cli@latest login
eas init                                   # fills projectId in app.json
eas build --platform all --profile preview # internal test build
eas build --platform all --profile production
eas submit --platform ios                  # App Store Connect
eas submit --platform android              # Play Console
```

### Store requirements
- Privacy Policy URL (host at `sportreel.app/privacy`) — content already in `mobile/src/shared/legal/`
- Face biometrics: declare in App Store Connect (Apple guideline 5.1.1)
- External payment (Stripe/Meshulam): disclose; no StoreKit/IAP
- App Review note: explain the hidden operator section (5× logo tap + Face ID) and supply review credentials

---

## 5. Verification checklist

1. `web-api` deploys; `GET /api/sessions` returns 200
2. Pipeline run updates `pipeline_status` (visible in operator → Pipeline)
3. Reel publish writes both `stream_uid` and `storage_path`
4. Stripe test card → webhook flips `payments.status` + `reels.status=sold`
5. Download token → Supabase Storage signed URL works
6. Screenshot blocked (Android FLAG_SECURE / iOS black frame)
7. Operator gate: 5× tap → Face ID
8. Push notification on face match → deep links to My Highlights

---

## 6. Pipeline automation (Drive → GitHub Actions)

The editing pipeline runs automatically when new footage lands in the Drive RAW
folder. No machine of yours needs to stay on.

```
Upload session to RAW  →  Apps Script watcher (waits for uploads to settle)
                                                        ↓
                                            repository_dispatch (one per session)
                                                        ↓
                              GitHub Actions: .github/workflows/pipeline-run.yml
                                  (ffmpeg + Gemini + slow-mo → drafts to REVIEW)
```

RAW acts as the waiting queue: only not-yet-processed clips are turned into
reels, and each processed session is moved to PROCESSED so it is never redone.
Clips uploaded together are grouped into one reel per athlete — the watcher
waits `QUIET_MINUTES` (default 2) of no new uploads before firing, so a
multi-clip session is processed whole rather than split across runs. Runs are
serialized (`concurrency: pipeline-run`), so two uploads never collide.

### A. GitHub repository secrets

Add under **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | Gemini API key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of the service-account JSON file |
| `DRIVE_USER_TOKEN_JSON` | Full contents of `drive_user_token.json` (operator OAuth — required for uploads/moves) |
| `RAW_FOLDER_ID` / `PROCESSED_FOLDER_ID` / `REVIEW_FOLDER_ID` / `APPROVED_FOLDER_ID` | Drive folder IDs |
| `OWNER_EMAIL` | Operator email |
| *(optional)* `NOTIFY_EMAIL`, `PREVIEW_FOLDER_ID`, `PENDING_PAYMENT_FOLDER_ID`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SENTRY_DSN` | as applicable |

### B. Google Apps Script watcher

1. In `apps_script/trigger.gs`, set `RAW_FOLDER_ID` (owner/repo are pre-filled).
2. Create a GitHub PAT that can trigger dispatches (fine-grained: *Contents: read & write*; classic: `repo`).
3. Apps Script → **Project Settings → Script Properties** → add `GITHUB_TOKEN = <PAT>`.
4. Run `setupTrigger()` once and authorize. It polls every minute and fires one
   dispatch per session after uploads settle (`QUIET_MINUTES`, default 2).

### C. Manual run / reprocess the same footage

- **Actions → Run Pipeline → Run workflow** triggers a run by hand.
- Tick **reset** to move PROCESSED→RAW, delete REVIEW drafts and clear state
  first — reprocesses the existing footage without re-uploading. Locally the
  equivalent is `python scripts/reset_and_rerun.py` (`--reset-only` to skip the run).

### D. Folder moves

Raw videos are archived RAW→PROCESSED automatically after processing, using the
operator OAuth token (the service account cannot move operator-owned files).

> **Note on slow-mo cost:** optical-flow interpolation (`SLOWMO_INTERPOLATE`) is
> CPU-heavy. On GitHub's 2-core runners a multi-athlete session can take a long
> time; set `SLOWMO_INTERPOLATE=false` (repo variable) to fall back to plain
> speed-ramps if runs approach the 6h job limit.
