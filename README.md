# SportReel — personal sports reels from shared footage

SportReel turns raw or edited sports footage into a personal, publishable social-media video for every athlete who performs at least one usable action in the footage. The system is an app-controlled production platform with a mobile operator surface, a Next.js API boundary, GitHub Actions orchestration, Python video processing, storage, Supabase tracking, delivery approval, payments, and Discover.

## Product vision — source of truth

The business outcome is not “the pipeline produced some highlights.” The outcome is:

> For every distinct athlete with at least one complete, visible, usable action, produce a personal silent video that centers that athlete and can be uploaded directly to social media so the athlete can promote themself and add platform-native audio after download.

This vision has the following non-negotiable rules:

1. **One featured athlete per reel, not one visible person.** Each reel is centered on one target athlete and the featured actions belong to that athlete. Teammates, opponents, officials, bystanders, and other athletes may remain visible or actively participate when the target athlete stays clear, continuous, and central. In football, a play normally contains many players. In surfing, another surfer may enter or ride the same wave. Neither case is a defect by itself. Block or split only when identity, tracking, or action attribution becomes genuinely uncertain.
2. **Every eligible athlete is accountable.** Each athlete with at least one usable action must receive a publishable reel, or the run must contain an explicit hard-reject reason explaining why no reel can be produced.
3. **One canonical silent output per part.** The pipeline must not select music, mix audio, preserve source audio, or publish an audio-bearing variant. Review shows one video-only file per Part. The athlete can add music or other audio in the social platform after download. A publishable reel must prove that it has no audio stream, use vertical 9:16 framing, supported encoding, acceptable resolution, and a duration of at most 90 seconds.
4. **Primary reel first.** Each athlete receives one primary reel. Additional parts are allowed only when complete actions cannot fit under the platform limit. Parts must be clearly ordered and independently publishable. A complete action is never split between Parts.
5. **Sport-specific coverage, shared business contract.** The definition of a usable action depends on the sport, but the athlete-level obligation does not. In surfing, every complete readable wave is included; a wave is rejected only for explicit evidence such as an immediate failed takeoff, no readable ride, duplication, wrong athlete, or loss of the target. Another surfer on the same wave does not invalidate the ride when the target surfer remains central. In team sports, the action belongs to the athlete who performs the meaningful play while the other players remain expected context.
6. **Repair before removal.** QA should trim, extend, re-frame, re-track, or re-render when possible. A usable action must not disappear merely because it is less impressive, has removable dead time, or is not the best moment in the session.
7. **QA failure is not publishable.** A final QA failure must block approval and enter the re-edit loop. “Non-blocking FAIL” is not a publishable business state.
8. **Evidence is mandatory.** A production run is successful only when diagnostics prove athlete coverage, identity lineage, primary-athlete continuity, action inclusion/rejection reasons, silent-video technical compliance, and final QA status.
9. **Preserve 4K/30 quality before reframing.** Production source footage is 4K at 30 fps. Canonical Parts must remain 2160x3840 at 30 fps. The normal framing mode keeps the full source frame inside the vertical canvas. Crop or zoom is allowed only as an evidence-backed repair when the detector/tracker proves the athlete would otherwise be unreadably small, outside the safe frame area, or ambiguous. Gemini edit hints, score, event type, or other visible people cannot authorize crop by themselves.
10. **Computer vision is mandatory; app-user biometrics are not part of the product.** Every analyzed event must have detector/tracker bbox and track evidence. Production must fail closed instead of falling back to Gemini-only identity or crop hints. The app does not collect face photos, create face embeddings, or automatically match a reel to an account from a face. Identity inside footage is used only to keep the featured athlete continuous within the production run; delivery and purchase ownership use explicit links, checkout, purchase records, or configured client contacts.

Terms used throughout the repository:

- **Eligible athlete:** a distinct athlete with at least one complete, visible, usable action.
- **Featured athlete / primary athlete:** the athlete for whom the personal reel is being created. Other people may be present, but the edit, tracking, and action attribution stay centered on this athlete.
- **Publishable reel:** the canonical silent social-ready video that passed final QA and technical checks.
- **Primary reel:** the first publishable reel for an athlete.
- **Supplemental part:** another publishable reel required only because complete actions exceed 90 seconds.
- **Hard reject:** an evidence-backed reason that makes an action or athlete output genuinely unusable; low score, other visible people, or another surfer on the same wave are not hard rejects by themselves.
- **Contain framing:** the default quality-preserving mode that keeps the complete source image visible inside the 9:16 canvas.
- **Tracked crop:** an exceptional destructive reframe allowed only by the deterministic necessity contract and stable CV evidence.

The implementation and acceptance plan for the centered-athlete/silent contract is tracked in `docs/audit/personal-publishable-reel-completion-plan-20260717.md`. The 4K/framing/perception/biometric-removal decision is tracked in `docs/audit/quality-first-4k-perception-and-face-removal-plan-20260721.md`. Changes that conflict with these sections require an explicit product decision and an audit update; they must not be introduced as a local optimization.

## Current architecture

```text
Operator mobile app
  -> Next.js web-api operator routes
  -> GitHub Actions workflows
  -> Python pipeline / delivery scripts
  -> storage + Supabase tracking tables
  -> mobile status screens, Review, Delivery, and Discover
```

Public athlete/viewer flows use the mobile app and web-api for Discover, reel checkout, payment webhooks, and protected download/streaming flows. Privileged operator flows must go through the operator API boundary and `operatorFetch`; the mobile app is a control surface only and must not run Python, FFmpeg, Gemini, detector/tracker inference, or other heavy processing locally.

## Main components

| Area | Path | Purpose |
|---|---|---|
| Operator / public mobile app | `mobile/` | Expo app for operator controls, Review, Pipeline status, support, analytics, Discover, checkout, and reel viewing. No face enrollment or biometric reel matching. |
| API layer | `web-api/` | Next.js API routes for operator actions, checkout, webhooks, analytics, Discover sessions, signed URLs, and service-role operations. |
| Pipeline | `pipeline/`, `scripts/run_tracked.py`, `run.py` | Python, Gemini, mandatory Ultralytics/BoT-SORT perception, FFmpeg, storage, Supabase, QA, identity-continuity, and editing logic. Runs in GitHub Actions or locally for development. |
| Delivery | `deliver.py`, `services/delivery.py`, `.github/workflows/deliver.yml` | Moves approved reels through explicit Discover/delivery/payment handoff and records durable delivery runs. |
| Storage automation | `apps_script/`, `.github/workflows/pipeline-run.yml` | Watches incoming uploads and dispatches pipeline runs once uploads settle. |
| Database and diagnostics | `supabase/`, `scripts/run_pipeline_with_diagnostics.sh` | Migrations, tracking tables, run evidence, coverage reports, framing decisions, Discover smoke SQL, and payment/pipeline state. |
| Contracts and audits | `docs/` | Product contracts, official-source research, smoke loops, audit state, and focused repair notes. |

## Supported operator actions

Use `docs/operator-pipeline-contract.md` as the source of truth for operator routes and tracking behavior. Current high-level actions are:

| Action | Current route / workflow |
|---|---|
| Run pipeline now | `POST /api/operator/pipeline/start` -> `.github/workflows/pipeline-run.yml` |
| Upload footage | `POST /api/operator/upload`, then `POST /api/operator/pipeline/start` |
| Reset and rerun | `POST /api/operator/pipeline/reset` -> `.github/workflows/pipeline-run.yml` |
| Send reel to re-edit | `POST /api/operator/reprocess` -> `.github/workflows/pipeline-run.yml` |
| Approve reel for delivery | `POST /api/operator/drafts/approve` -> `.github/workflows/deliver.yml` |
| Read pipeline status | `GET /api/operator/pipeline/status` |
| Read run history | `GET /api/operator/pipeline/runs` |
| Read delivery status | `GET /api/operator/delivery-status` |
| Discover diagnostics | `GET /api/operator/discover-diagnostics` |

`POST /api/operator/pipeline/run` exists only as a backward-compatible alias for older app builds. New operator code should use `/api/operator/pipeline/start`.

## Storage state model

Storage folder/prefix membership is operational state. The current flow uses:

- `RAW_FOLDER_ID` / `raw/` — incoming footage waiting to run.
- `PROCESSED_FOLDER_ID` / `processed/` — originals after verified processing.
- `REVIEW_FOLDER_ID` / `review/` — canonical generated silent reels awaiting operator approval.
- `APPROVED_FOLDER_ID` / `approved/` — approved reels ready for delivery.
- `PREVIEW_FOLDER_ID` / `previews/` — optional watermarked previews.
- `PENDING_PAYMENT_FOLDER_ID` / `pending_payment/` — optional full reels awaiting payment handoff.

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
npm test
```

Mobile PRs are guarded by `.github/workflows/mobile-check.yml`. The mobile app may read end-user auth/profile/RLS data directly through Supabase, but privileged operator data must go through the API boundary.

### Pipeline

```bash
pip install -r requirements.txt
python run.py
```

Local pipeline runs are for development and diagnostics. Production-style operator runs should be dispatched through the API and GitHub Actions so `pipeline_runs`, `pipeline_status`, mandatory perception evidence, storage moves, product-contract evidence, and app status screens stay aligned. Production runs require a working Ultralytics/BoT-SORT sidecar producer and fail when tracked event evidence is missing.

## Deployment and operations

Use `DEPLOYMENT.md` for environment setup, Vercel, EAS, GitHub Actions, Supabase migrations, storage automation, webhooks, and verification checklists.

Important focused docs:

- `docs/audit/personal-publishable-reel-completion-plan-20260717.md` — centered-athlete business vision and acceptance gates.
- `docs/audit/quality-first-4k-perception-and-face-removal-plan-20260721.md` — 4K/30, contain-first framing, mandatory CV, face-recognition removal, risks, and real-run closure.
- `docs/operator-pipeline-contract.md` — app/API/workflow contract.
- `docs/operator-api-boundary.md` — privileged operator API boundary.
- `docs/drive-move-contract.md` — RAW -> PROCESSED move invariant.
- `docs/delivery-approval-note.md` — Review approval and delivery feedback behavior.
- `docs/upload-to-run-smoke.md` — upload-to-run smoke loop.
- `docs/discover-reels-smoke-loop.md` — Discover -> Checkout smoke loop.
- `docs/app-pipeline-audit.md` — current readiness gaps and repair order.

## Current readiness focus

The pipeline must be evaluated against the Product vision above, not only against workflow success. Keep future PRs narrow, update the relevant audit when a gap changes status, and do not close a footage-level gap without a real run and visual review. The 4K/perception/biometric-removal audit remains open until final-head CI, migration/deployment, measured tracking quality, and real 4K footage all pass.

## License

MIT — built for drone operators and sports content creators.
