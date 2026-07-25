# SportReel production release gate — 2026-07-24

Repository: `yotamfried-ux/Video-editing-with-drone`  
Scope: GAP-023 release evidence before the first controlled Android upload smoke  
Baseline: `main` at `5408818ac2fa6615ae54ebe6073fa792f998f2f7`  
Contained upload foundation: PR #196 merge commit `9a686ee1d1a13d658d20123d455bc39674c11ce0`  
Contained blind-ground-truth design: PR #197 merge commit `5408818ac2fa6615ae54ebe6073fa792f998f2f7`  
Working branch: `fix/production-release-gate`  
PR: #198  
Result: **blocked with exact evidence — the release gate implementation is prepared, but the protected live workflow has not run from merged `main`**

This record distinguishes implementation evidence from live-service evidence. It does not claim that an APK is installed, that a physical SD/USB source was tested, or that GAP-013, GAP-014, GAP-015, GAP-016, or GAP-027 is closed.

## Status vocabulary

- `verified` — directly proved from the repository, GitHub metadata, a deterministic check, or a retained live artifact.
- `missing` — a required object or control does not exist.
- `stale` — an object exists but describes an older commit or contract.
- `misconfigured` — configuration exists but does not enforce the required behavior.
- `unverified` — configuration or service state may exist, but no acceptable evidence was available.
- `blocked` — the next proof depends on an external protected run or manual device action that cannot be truthfully substituted.

## Pre-change live-state inventory

| Area | Item | Status | Evidence / finding |
|---|---|---|---|
| GitHub | Live `main` | verified | Exact HEAD `5408818ac2fa6615ae54ebe6073fa792f998f2f7`. |
| GitHub | PR #196 | verified | Merged at `9a686ee1d1a13d658d20123d455bc39674c11ce0`; contained by live `main`. |
| GitHub | PR #197 | verified | Merged at the live `main` commit; GAP-027 remains intentionally open. |
| GitHub | Conflicting open release PR | verified absent | Open PRs #194, #192, #191, #188, and #134 were inspected; none is the active GAP-023 production-release implementation. |
| Vercel | Commit check for PR #196 merge | verified, limited | GitHub recorded a successful Vercel status and deployment target ending in `EcTwgRapf6MPhUw8auLyPfQ7S68J`. This is not production-alias or API evidence. |
| Vercel | Commit check for current `main` | verified, limited | GitHub recorded a successful Vercel status and deployment target ending in `3X56Kj8ocbnxca9rdrM9zix2vzrz`. This is not production-alias or API evidence. |
| Vercel | READY production deployment containing current `main` | unverified | No retained deployment API artifact proved state, exact source commit/ancestry, target, or deployment ID. |
| Vercel | Production alias/domain points to that deployment | unverified | A successful GitHub deployment check does not prove the production alias target. |
| Vercel | Required production environment variable names | unverified | Existing workflow did not inventory Vercel Production variable names through the Vercel API. |
| Vercel | Production upload API smoke | missing | Existing release workflow did not call the production domain. |
| GitHub Actions | Release ordering | verified foundation | Existing workflow ordered migration/schema verification before R2 and Android build. |
| GitHub Actions | Exact production deployment approval | missing | Existing workflow did not verify Vercel commit containment and production alias identity. |
| GitHub Actions | Required protected secret-name preflight | misconfigured | Secrets were consumed by later steps, but no complete fail-closed preflight artifact existed. |
| GitHub Actions | Failure artifacts | misconfigured | Some existing artifacts used warning behavior or were absent when an early verifier failed. |
| Supabase | Upload migrations in repository | verified | Upload foundation migrations and biometric-removal migration exist. |
| Supabase | Live migration history/checksums | missing | No repository-owned immutable release migration ledger existed for this sequence. |
| Supabase | Live upload schema | unverified | Existing verifier checked a small subset of tables/columns/RPCs only. |
| Supabase | Constraints/indexes/foreign keys | missing from gate | Existing release verifier did not enforce them comprehensively. |
| Supabase | RLS/policies/client grants/service-role grants | missing from gate | Existing release verifier did not prove the full authorization surface. |
| Supabase | Biometric-removal migration in release order | missing | `20260721_remove_face_recognition.sql` was not part of the upload release workflow. |
| Runtime | No obsolete biometric dependencies in registration/login/profile/Discover/checkout/support/delivery | unverified | No focused, fail-closed runtime inventory existed. |
| R2 | Multipart create/parts/retry/complete/HEAD/hash/delete probe code | verified foundation | Existing real probe covered the primary sequence. |
| R2 | Exact first/retry/completion ETag ledger | incomplete | Existing evidence recorded only ETag presence, not the exact correlation needed for retry proof. |
| R2 | Final multipart ETag is not source MD5 | incomplete | Policy existed, but the independent evidence artifact did not prove the distinction. |
| R2 | Production CORS policy | unverified | No API-based narrow-origin/`ExposeHeaders: ETag` verifier existed. Native Android still requires installed-build proof. |
| Android/EAS | `SportReelSourceReader` source and compile checks | verified foundation | Local Expo module, autolinking contract, prebuild, and Kotlin compile checks exist. |
| Android/EAS | Exact cloud build ID/profile/runtime/channel | missing | Existing job used a local build and did not retain an authoritative EAS build record. |
| Android/EAS | Exact APK installed on device | blocked | Requires the user to install the generated APK; not part of this PR. |
| Mobile config | iOS media permission text | stale | Camera/photo descriptions still claimed face-photo collection despite biometric removal. |

## Root causes found

1. **The release workflow proved build order but not production identity.** A passing Vercel check was treated as adjacent evidence, while deployment state, source commit containment, production alias, and production API behavior were not enforced together.
2. **The live schema gate was too shallow.** It did not prove data types, constraints, indexes, foreign keys, RLS, policies, grants, or the complete RPC boundary.
3. **The destructive biometric-removal migration was documented but omitted from the protected release sequence.** Its required explicit confirmation and post-migration runtime verification were also absent.
4. **The R2 artifact was insufficient for exact retry and checksum claims.** It did not preserve the first and retried ETags or prove that the final multipart ETag was not being interpreted as a source MD5.
5. **The Android job produced an APK without an authoritative cloud build identity.** A local APK plus upload command did not establish build ID, profile, runtime version, channel, source commit, or exact downloadable artifact hash.
6. **No production upload API lifecycle smoke existed.** Authentication, authorization, batch/source/session correlation, negative scope checks, abort, cleanup, and database state were not exercised against the production domain.
7. **Pre-created batch capacity could be counted twice.** `register_upload_batch(..., 1, ...)` followed by first-source membership could increment `expected_file_count` from 1 to 2, permanently preventing a one-file batch from becoming ready.
8. **Biometric-removal copy drift remained in `mobile/app.json`.** iOS permission descriptions still referred to a face photo even though the product contract says SportReel does not collect one.

## Remediation implemented on the working branch

### Release workflow

`.github/workflows/upload-foundation-release.yml` now:

- is an explicit, protected `workflow_dispatch` release gate;
- requires `RELEASE` and `REMOVE_BIOMETRICS` confirmations;
- runs only from `refs/heads/main` and checks out the exact `github.sha`;
- performs required GitHub secret-name and input preflight without printing secret values;
- verifies Vercel READY state, exact source-commit containment, production alias identity, and required production variable names;
- enforces `preflight → Vercel → Supabase → R2 → production API smoke → EAS build` ordering;
- publishes failure evidence with `if: always()` and `if-no-files-found: error`;
- pins EAS CLI `18.8.1` instead of using an unbounded `latest` release;
- builds through EAS cloud build, records the exact build ID, downloads that build by ID, hashes the APK, and records `installed_on_device: false`.

### Supabase

- `scripts/apply_upload_release_migrations.py` applies the explicit dependency sequence, records SHA-256 checksums in `public.sportreel_release_migrations`, blocks checksum drift, and proves a check-only rerun is stable.
- `scripts/verify_upload_release_schema.sql` verifies tables, columns/types, constraints, indexes, foreign keys, RLS, policies, table grants, RPC grants, required functions, migration-ledger entries, and biometric absence.
- `scripts/verify_no_biometric_runtime_dependencies.py` fail-closes if a named live surface is absent or still references removed biometric identifiers.
- `20260723_upload_start_idempotency.sql` now locks and reconciles source membership against reserved batch capacity instead of double-counting the first source.

### Vercel and production API

- `scripts/verify_production_deployment.py` records the production deployment ID/state/URL/source SHA, proves the requested main SHA is contained, verifies the production alias, and records environment variable **names only**.
- `scripts/test_production_upload_api_smoke.py` exercises operator auth rejection/acceptance, malformed input, explicit one-file batch creation, source multipart start, batch/source/session correlation, cross-batch and raw-key mismatch rejection, status, abort, cleanup confirmation, final database state, and fixture removal without uploading real footage.
- The multipart status route now accepts optional `batch_id` and `storage_key` assertions and returns `409` on mismatch.

### R2

- The independent R2 probe now records exact part ETags, exact retry replacement ETag, completion order, final size, source/download SHA-256, whole-file MD5, final multipart ETag shape, deletion, and post-delete `404` proof.
- `scripts/verify_r2_cors.py` verifies a configured browser origin only when browser upload is explicitly enabled; wildcard origin or missing exposed `ETag` fails. Native React Native ETag visibility remains a device-build proof, not a browser-CORS inference.

### Android/EAS and configuration

- The release job requires successful database, R2, and production API gates before EAS can start.
- The EAS evidence includes build ID, status, platform, profile, source commit, runtime version, channel, distribution, artifact URL identity, APK SHA-256/size, and native-module presence.
- `mobile/app.json` no longer claims that camera/photo access is used for face matching. Local biometric unlock wording remains limited to securing operator access.

### Negative gates

`scripts/test_production_release_negative_contracts.py` and the release contract checks cover:

- missing secrets and environment variables;
- missing destructive-migration confirmation;
- migration/checksum/order failure;
- schema verifier `false`;
- missing RLS/policy/grant proof;
- Vercel source-commit or alias mismatch;
- R2 credentials, missing parts, ETag, size, hash, and cleanup failures;
- failed/errored/cancelled EAS build;
- production smoke failure;
- accidental APK production before all prior gates pass;
- fail-open workflow patterns such as `continue-on-error`, ignored missing artifacts, or `|| true`.

## Live execution and evidence still required

The branch implementation cannot truthfully create production evidence before it is reviewed, merged, deployed, and executed from the resulting exact `main` SHA. After explicit merge approval, run **Upload Foundation Release** from the merged `main` with:

- `confirm_release=RELEASE`;
- `confirm_biometric_removal=REMOVE_BIOMETRICS`;
- the intended production domain;
- a browser upload origin only when a browser client actually uploads parts.

The protected run must retain:

1. preflight evidence;
2. Vercel deployment/alias/environment-name evidence;
3. migration apply and idempotency artifacts;
4. comprehensive schema/RLS/grant evidence;
5. no-biometric runtime evidence;
6. Web API signer and independent R2 multipart evidence;
7. CORS evidence or an explicit native-only not-applicable result;
8. production API smoke evidence;
9. exact EAS build metadata and APK artifact.

No production URL, workflow run ID, migration result, R2 result, EAS build ID, or smoke result is recorded here until that live run exists.

## Rollback and failure behavior

- A failed gate stops all downstream jobs; an APK cannot be produced after a failed migration, verifier, R2 probe, deployment check, or production smoke.
- Migration checksum drift is blocked rather than silently reapplied.
- The biometric-removal migration is destructive and has no automated down-migration. Recovery requires an approved pre-release backup/PITR restoration and redeployment of the prior compatible application commit; this must be validated against the actual Supabase project before closure.
- R2 probes use isolated integration-test keys and treat abort/delete/post-delete verification failure as a release failure.
- A failed EAS build creates no release-ready claim. Existing deployed builds remain unchanged.
- Vercel rollback is operationally separate: restore/alias a previously approved deployment and rerun the deployment and API gates before proceeding.

## Current decision

**State B — blocked with exact evidence.**

The deterministic release implementation and negative gates are prepared. The system is **not yet ready for the Android device smoke** because the exact branch head is not merged/deployed and no protected live workflow run has produced Supabase, R2, production API, or EAS evidence. GAP-013, GAP-014, GAP-015, GAP-016, GAP-023, and GAP-027 remain open. The next admissible evidence-producing step after PR approval and merge is the protected release workflow; only after it passes may the exact APK be installed for the small SD/USB upload smoke.
