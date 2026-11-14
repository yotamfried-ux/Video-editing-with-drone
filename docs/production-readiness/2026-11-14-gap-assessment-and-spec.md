# SportReel — Production Readiness Gap Assessment and Implementation Specification

**Date:** 2026-11-14  
**Scope:** athlete-facing mobile app, operator experience, API, pipeline, review, checkout, delivery and release.  
**Status:** evidence-based static repository assessment, **NOT** production certification. No code, infrastructure, data or deployment changes are authorized by this document.

## Product contract to preserve

The [repository README](../../README.md) defines a distinct, publishable, silent 9:16 video per eligible athlete; complete action coverage; explicit athlete-level hard-rejects; 2160×3840 at 30 fps; no app-user biometric identification; detector/tracker evidence; fail-closed final QA. Do not dilute these invariants for speed or monetization. Mobile is a control/consumer surface; heavy inference and rendering remain in backend workflows per [DEPLOYMENT.md](../../DEPLOYMENT.md).

## Observed evidence and current gaps

| ID | Severity | Evidence in repository (as of assessment) | Gap / decision | Acceptance gate |
| --- | --- | --- | --- | --- |
| P0-01 | P0 | `docs/evidence/run-43303438106-catalog-comparison.md`: 14 athletes reached compile, 13 published, one QA-failed; wrong merge 0143/0152 and excluded 0095 published in observed run; 88% catalogued seconds included and 94% cut seconds catalogued | Athlete identity and source eligibility not fully qualified on live dataset | Replay representative **approved** GT cohort on merged production candidate, zero wrong-athlete merges, zero excluded-source publish, 100% eligible-athlete outcomes (reel or justified hard reject), 100% QA FAIL blocked; record action boundary error and no regressions. Do not mark PASS from offline unit tests alone |
| P0-02 | P0 | PR #382 (draft at assessment) reports preview was full video and paid download returned the same watermarked preview; fixes are proposed, not proven deployed | Protect paid full asset, correct entitlements, prevent bypass through direct object URLs | Test anonymous, unpaid, paid, revoked and refunded access to preview/full/download; no full asset access before server-side verified payment; webhook replay and concurrency idempotent; signed URLs expire; production smoke |
| P0-03 | P0 | `mobile/eas.json` production profile contains a Stripe **test** publishable key; iOS submission fields are placeholders. PR #382 proposes repairs | Store-release configuration and live payment readiness unverified | EAS production build with appropriate live/test-mode segregation; signed AAB/IPA and store metadata; platform review; no hardcoded secret; production payment test with controlled refunds |
| P0-04 | P0 | PR #382 explicitly requires `supabase/migrations/20261114_discover_preview_and_athlete_follow.sql` before deployment | Migration and deployment sequencing not qualified | Backup and dry-run migration; RLS and compatibility checks; expand/contract deployment plan; rollback/recovery drill; no partial rollout exposing unpaid full media |
| P0-05 | P0 | README mandates CV evidence and silent 4K export; existing CI run summaries alone do not prove these properties for real footage | End-to-end production evidence gap | For each output: verify 2160x3840, 30fps, <=90s, zero audio tracks, valid codec, source/track/athlete lineage, approved QA and stable delivery, including real-device playback |
| P0-06 | P0 | `docs/annotation-studio/STATUS.md` is an earlier milestone snapshot, with real integration gaps; later work may have superseded it | Evidence ledger inconsistent across historical milestones | Reconcile current cloud Studio, approved source revisions, immutable catalog, EDL/prediction imports, backup and read-only separation with live evidence; do not treat historical NOT DONE as current fact |
| P0-07 | P0 | Android Expo SDK 53 / React Native 0.79.6; `mobile/app.json` has package/version and permissions; no verified Play submission artifact examined | Store policy and permission compliance unverified | Verify target API 36+ for new/updated phone app submissions under Aug 2026 Play rules; current SDK/toolchain support, AAB signing, permissions, Data Safety, account deletion, privacy URLs and internal/closed tests |
| P1-01 | P1 | `DEPLOYMENT.md` documents Vercel, Supabase, R2, GitHub Actions, Stripe, Resend | Cross-service observability/recovery and cost controls not independently qualified | Correlation ID from upload→job→render→purchase→delivery; SLO dashboards, actionable alerts, retries/DLQ, cost per reel and budget caps; chaos tests for storage/API/webhook/worker failures |
| P1-02 | P1 | Operator UI and review workflow are described, but current real-device qualification not independently run here | Real-device UX and failure handling unverified | Android/iOS real-device test matrix: large uploads, interrupted network, resume, process death, status refresh, approval/re-edit, checkout, download, accessibility/RTL, low storage |
| P1-03 | P1 | Mobile/API/pipeline span JS/TS/Python and third-party models | Dependency and supply-chain hardening needs current evidence | Lockfile reproducibility, SBOM, secret scan, dependency CVE review, signed artifacts, restricted GitHub Actions permissions and server-side auth/RLS |
| P1-04 | P1 | `DEPLOYMENT.md` describes service-role isolation and storage prefixes | Privacy and retention need proof, not policy statements | Verify access policies, retention/deletion, account deletion propagation, lawful media rights, third-party processing disclosures, export and backup lifecycle |
| P2-01 | P2 | Existing app product has Discover and athlete follow features proposed in PR #382 | Product analytics and release telemetry | Privacy-respecting funnel: upload→ready→preview→checkout→paid download, crash-free sessions, playback failures, time-to-reel, churn and refunds; staged rollout |

## Implementation phases

**Phase A — evidence freeze and blockers:** identify deployed SHAs for API/mobile/pipeline/Studio; map PR #382 features against `main`; inventory latest CI, device builds, migrations, production environment and last successful full real-video run. Record PASS/FAIL/UNKNOWN per gate; no guessing. Block paid launch on any P0 failure.

**Phase B — correct business invariants:** fix athlete/source misattribution, excluded-source publishing, event boundaries, final QA fail-closed, media format; use the existing approved Ground Truth cohort as blind holdout. Record per-athlete and per-action evaluation and trace.

**Phase C — secure commercialization:** integrate and qualify payment-provider implementation only after reviewing PR #382; apply migrations safely; enforce server-side entitlement checks and short-lived media access; verify privacy/deletion and payment webhooks. Avoid new infrastructure until a measurable requirement exists.

**Phase D — mobile and operational release:** EAS production artifacts, Play/API requirements, iOS metadata, staged internal/closed testing, accessibility, low-connectivity, alerts, backup/restore, load and cost gates; controlled rollout with rollback criteria.

## Recommended authoritative documentation / tools

| Area | Primary source | Tool or use |
| --- | --- | --- |
| Android media | https://developer.android.com/media/media3/transformer | Media3 Transformer/ExoPlayer for optional **on-device** preview/export, only if justified; not a replacement for canonical 4K FFmpeg server pipeline |
| Mobile security | https://mas.owasp.org/MASVS/ ; https://mas.owasp.org/MASTG/ | MASVS/MASTG test matrix; manual + automated auth/storage/network review |
| Play release | https://support.google.com/googleplay/android-developer/answer/11926878 ; https://support.google.com/googleplay/android-developer/answer/9859348 | target SDK, release tracks and production submission |
| Expo releases | https://docs.expo.dev/build/introduction/ ; https://docs.expo.dev/submit/introduction/ ; https://docs.expo.dev/eas-update/introduction/ | EAS Build/Submit/Update, channel separation and rollback |
| Storage | https://developers.cloudflare.com/r2/ ; https://supabase.com/docs/guides/database/postgres/row-level-security | scoped signed access, bucket policy and RLS |
| Payments | https://docs.stripe.com/webhooks ; https://docs.stripe.com/payments/checkout | verified webhook, idempotent fulfillment and entitlement |
| Video QA | https://ffmpeg.org/ffprobe.html ; https://ffmpeg.org/ffmpeg.html | machine-check codec, resolution, fps, audio absence and duration |
| Monitoring | https://docs.sentry.io/platforms/react-native/ ; https://opentelemetry.io/docs/ | errors, traces and correlated production diagnostics |
| Testing | https://maestro.mobile.dev/ ; https://playwright.dev/docs/intro | mobile real-device flows and web/API E2E |
| Dependency security | https://docs.github.com/en/code-security/dependabot ; https://github.com/gitleaks/gitleaks | dependency alerts and secret detection |

**Adoption principle:** prefer existing Expo, Maestro, Playwright, FFmpeg, Supabase and pipeline infrastructure. Add no SDK, service or model until a measured gap demonstrates value, security/licensing are reviewed, and costs fit budget.

## Evidence ledger schema (required before any production claim)

For each gate: `gate_id`, `requirement`, `current_sha`, `environment`, `test_command_or_run_url`, `dataset_version`, `observed_result`, `verdict=PASS|FAIL|UNKNOWN`, `owner`, `timestamp`, `blocking_issue`, `remediation_pr`. A merged PR or green CI does not prove deployed production behavior. Keep UNKNOWN until independently verified.

## Immediate next execution package

1. Read and audit #382 plus current `main` to avoid duplicate work; establish deployment SHA and migration status.
2. Re-run approved GT comparison on a representative real-video batch and reproduce previously observed misattribution/exclusion failures.
3. Perform adversarial payment entitlement and preview/full media leakage tests in isolated staging.
4. Build and run Android preview/production profiles on real devices, verify API target and crash/retry behavior.
5. Execute a controlled end-to-end run and publish signed evidence ledger before declaring production ready.

No pipeline execution, migration, merge, cloud changes, store submission, paid external calls or destructive data operations were performed during this assessment.
