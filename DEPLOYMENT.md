# SportReel — Deployment Guide

This guide covers taking SportReel from source to an operational app, API, pipeline, delivery, payment, and Discover system.

## Architecture

```text
Operator mobile app
  -> Next.js web-api on Vercel
  -> GitHub Actions workflows
  -> Python + Gemini + mandatory Ultralytics/BoT-SORT + FFmpeg
  -> R2 or Drive storage + Supabase tracking tables
  -> Review, re-edit, delivery, Discover, checkout, and app status screens
```

The mobile app is a control surface. Do not move Python, FFmpeg, Gemini, detector/tracker inference, storage moves, or service-role operations into mobile code.

SportReel does **not** collect face photos, create face embeddings, or match a Reel automatically to an app account from a face. Do not provision or restore an `athlete-photos` bucket, biometric RPC, `face_embedding`, `photo_path`, or `matched_athlete` field.

---

## 1. Provisioned services

| Piece | Purpose |
|---|---|
| Supabase | Auth, application state, pipeline/delivery tracking, purchases, diagnostics, and migrations. |
| Cloudflare R2 or Google Drive | RAW, PROCESSED, REVIEW, APPROVED, preview, and payment/delivery object state. |
| Vercel | Hosts `web-api/`. |
| Expo / EAS | Builds and publishes `mobile/`. |
| GitHub Actions | Runs pipeline, delivery, checks, and tracked migrations. |
| Gemini | Semantic video understanding and model-assisted QA. |
| Ultralytics YOLO + BoT-SORT | Mandatory detector/tracker evidence for athlete localization and continuity. |
| FFmpeg | Silent 2160x3840, 30 fps rendering and media validation. |
| Stripe | Discover checkout and payment completion. |

The Supabase service-role key belongs only in trusted server and pipeline environments. Never place it in mobile code.

---

## 2. Vercel web-api

Set the Vercel project root to `web-api`.

Required environment variables depend on the enabled features, but the production baseline is:

```bash
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_KEY=<service-role-secret>

OPERATOR_SECRET=<operator-shared-secret>
UPSTASH_REDIS_REST_URL=<optional>
UPSTASH_REDIS_REST_TOKEN=<optional>

GITHUB_REPO=yotamfried-ux/Video-editing-with-drone
GITHUB_DISPATCH_TOKEN=<fine-grained-repository-token>

STORAGE_BACKEND=r2
R2_ACCOUNT_ID=<...>
R2_ACCESS_KEY_ID=<...>
R2_SECRET_ACCESS_KEY=<...>
R2_BUCKET=sportreel
R2_ENDPOINT_URL=<optional-explicit-endpoint>
R2_PUBLIC_BASE_URL=<optional-public-base>

STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
RESEND_API_KEY=<...>
RESEND_FROM_EMAIL=<...>
NEXT_PUBLIC_APP_DOMAIN=sportreel.app
```

Drive-backed deployments additionally need the Google credentials and folder IDs documented in `web-api/.env.example` and `.env.example`.

### Webhooks

| Provider | Endpoint | Events |
|---|---|---|
| Stripe Checkout | `https://<deployment>/api/payments/webhook` | `checkout.session.completed`, `checkout.session.expired` |
| Legacy Stripe PaymentIntent | `https://<deployment>/api/webhooks/stripe` | `payment_intent.succeeded`; remove after legacy clients are retired |

The legacy webhook uses explicit Stripe receipt/customer data. It must not query an inferred athlete owner.

---

## 3. Mobile app

`mobile/.env` should include:

```bash
EXPO_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
EXPO_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
EXPO_PUBLIC_API_BASE_URL=https://<vercel-deployment>
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_...
EXPO_PUBLIC_APP_DOMAIN=sportreel.app
```

Validation and release:

```bash
cd mobile
npm ci
npm run type-check
npm test
npx eas-cli@latest login
eas build --platform all --profile preview
eas build --platform all --profile production
eas submit --platform ios
eas submit --platform android
```

Store-review requirements:

- Provide the current Privacy Policy and Terms URLs.
- State accurately that the app does not collect facial biometric templates or use face recognition for account matching.
- Explain that computer vision is used server-side to track a featured athlete inside operator-uploaded sports footage.
- Disclose external payment flows where required.
- Explain the hidden operator section and provide review access instructions.

After release, verify the active EAS update/build ID rather than assuming the latest source is live.

---

## 4. GitHub Actions pipeline configuration

Add required secrets and variables under **Settings -> Secrets and variables -> Actions**.

### Core pipeline

| Secret / variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Semantic analysis and QA. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | Durable run, QA, delivery, and manifest state. |
| `OWNER_EMAIL` / `NOTIFY_EMAIL` | Optional notifications. |
| `SENTRY_DSN` | Optional observability. |
| Storage credentials | R2 or Drive access according to `STORAGE_BACKEND`. |

### Mandatory perception

Production workflow sets:

```bash
SPORTREEL_REQUIRE_PERCEPTION=1
SPORTREEL_ULTRALYTICS_MODEL=yolo11s.pt
SPORTREEL_ULTRALYTICS_TRACKER=botsort.yaml
SPORTREEL_ULTRALYTICS_FPS=30
```

`pipeline/required_perception_policy.py` supplies the first-party producer command when no explicit command is configured. A custom `SPORTREEL_PERCEPTION_COMMAND` is allowed only when it still produces the required sidecar schema with usable detections, bbox dimensions, confidence, and track IDs.

Do not disable required perception to make a failing run green. Fix the detector/tracker configuration or classify the run as blocked.

### 4K/30 resource considerations

Canonical Parts are silent 2160x3840 at 30 fps. Before declaring production ready, measure:

- detector/tracker wall time per source video;
- render and compile wall time per Part;
- GitHub Actions CPU minutes;
- temporary disk usage;
- output object size;
- upload duration and retry count;
- timeout behavior.

The tracked audit is `docs/audit/quality-first-4k-perception-and-face-removal-plan-20260721.md`.

---

## 5. Pipeline dispatch

Production-style runs should be triggered through the operator API or configured storage watcher:

```text
Operator selects/uploads footage
  -> upload verification and batch record
  -> POST /api/operator/pipeline/start
  -> .github/workflows/pipeline-run.yml
  -> scripts/run_tracked.py
  -> mandatory perception + Gemini + edit + QA + business gate
  -> REVIEW objects + Supabase status and diagnostics
```

Supported actions and tracking rows are defined in `docs/operator-pipeline-contract.md`.

The workflow must preserve the requested batch boundary. Do not process unrelated RAW objects in the same run.

---

## 6. Storage state

Storage prefix/folder membership is operational state:

1. Footage starts in `raw/` or `RAW_FOLDER_ID`.
2. Verified processing moves originals to `processed/` or `PROCESSED_FOLDER_ID`.
3. Canonical silent Parts are uploaded to `review/` or `REVIEW_FOLDER_ID`.
4. Operator approval moves or records the object under APPROVED state.
5. Preview/payment/delivery prefixes are optional explicit handoff states.

`processed.json` is a runner cache, not durable truth. See `docs/drive-move-contract.md` and the R2 storage contracts.

---

## 7. Supabase migrations

New migrations live in `supabase/migrations/`.

For existing environments, `20260721_remove_face_recognition.sql` is destructive by design. It removes historical face photos, embeddings, inferred athlete ownership, and matching functions.

Required sequence:

1. Review the SQL and confirm that biometric data must be deleted.
2. Back up only if a legally and operationally valid retention reason exists.
3. Run the tracked migration workflow with `DRY_RUN`.
4. Apply only after explicit approval.
5. Run `supabase/verify_schema.sql` and confirm every result is `ok = true`.
6. Confirm the `athlete-photos` bucket and objects no longer exist.
7. Confirm registration, profile, Discover, checkout, payment confirmation, delivery, and support no longer reference removed fields.

New environments use the cleaned core schema and should never create the biometric surface.

---

## 8. Verification checklist

### API and Vercel

- [ ] Current `main` is deployed, not merely present in GitHub.
- [ ] `GET /api/operator/pipeline/status` rejects missing or invalid operator authorization.
- [ ] Valid operator status and run-history requests return durable state.
- [ ] Operator Smoke passes.
- [ ] Stripe webhooks use explicit purchase/customer data.

### Mobile

- [ ] Registration contains only account and profile steps.
- [ ] Profile contains no face-recognition controls.
- [ ] There is no face-matched My Highlights tab.
- [ ] Privacy Policy and Terms contain no biometric enrollment or consent flow.
- [ ] Discover, checkout, payment confirmation, support, and explicit purchased-media access work.

### Pipeline

- [ ] Missing or invalid perception evidence fails before publishable output.
- [ ] Every analyzed event contains a track ID, bbox, source dimensions, confidence, and tracker-sidecar status.
- [ ] Default surfing framing is contain.
- [ ] Every tracked crop is present in `framing_decisions.jsonl` with a measured necessity reason.
- [ ] Every final Part passes `ffprobe`: 2160x3840, 30 fps, no audio, supported H.264 profile, yuv420p, BT.709, fast start, and <=90 seconds.
- [ ] Track fragmentation and ID switches are measured on difficult footage.

### Real production-style run

- [ ] Use the same comparison footage identified in the audit.
- [ ] Inspect all generated videos at native resolution.
- [ ] Account for every eligible athlete and usable action exactly once or with an explicit rejection.
- [ ] Verify manifest, coverage, QA trace, framing decisions, GitHub conclusion, Supabase run row, and operator status agree.

Do not close the audit from green CI alone.
