# SportReel — final production qualification

Date: 2026-11-14. Assessed code: branch `ccr-3f12fc2f-pdvirt` (PR #382) on top of `main` = `7d6b544`.
Production today: Vercel web-api = `7d6b544`; Supabase project `bcndgmymnismbxvdeetc`, last applied migration
`20261006190446`; no mobile build has been submitted to a store.

Statuses are only PASS, FAIL, UNKNOWN or BLOCKED. UNKNOWN is not PASS. Gate ids follow the specification in
PR #383 (`docs/production-readiness/2026-11-14-gap-assessment-and-spec.md`).

## Verdict

**NOT_READY**

Three P0 gates fail on evidence (athlete identity, excluded source, Ground Truth evaluation record), three are
blocked on an approval or a credential only the owner holds (production migrations and deploy, store artifacts,
live payments), and real-device behaviour is unknown. Nothing in PR #382 is live.

## A. Gap matrix

| Gate | Requirement | Evidence | Status | Severity | Task | Verification |
|---|---|---|---|---|---|---|
| P0-01a | Two clips of one athlete are one reel (0070/0108) | Split in run 43303438106; merged in runs 43397405813 and 43583126199 after PR #376 | PASS | P0 | done (`6362b1b`) | `scripts/test_generic_top_identity_contract.py`; production run logs |
| P0-01b | Two athletes are never one reel (0143 + 0152) | Still merged in run 43583126199; the analyzer describes 0152 on a pink board, the catalog has two athletes | FAIL | P0 | Needs the run's detections and identity decisions to find which rule joins them | `scripts/eval_identity_vs_catalog.py` against the catalog |
| P0-01c | A source the catalog excludes produces no reel (0095) | Run 43583126199 publishes a reel from 0095 | FAIL | P0 | Decide from the footage why the catalog excludes it; the pipeline may not read the label | catalog comparison |
| P0-01d | Action boundaries match the catalog | Tandem ride cut 25.8–33.8 s, catalog 16.9–36.7 s; 0094 cut runs to 22.5 s, catalog 13.2 s. Tandem end rule merged in PR #378 did not fire in run 43583126199 ("subject lost at 34.7s") | FAIL | P0 | Needs detections; a diagnostic that names the refused track fragment is in PR #382 | catalog comparison, coverage 88 %, precision 94 % |
| P0-01e | A clip blocked by the primary-actor policy is not publishable | Run 43303438106: three policy blocks, one unpublishable row | UNKNOWN | P0 | Read the run manifest to see whether the blocked clips were removed from the published reels | manifest in the diagnostics artifact |
| P0-01f | QA FAIL never becomes publishable | `draft_publishability`, run of 2026-11-14: the one FAIL row is `publishable=false`; 12 PASS rows publishable | PASS | P0 | — | SQL on production, `scripts/test_real_qa_fail_closed.py` |
| P0-02a | Discover shows a short watermarked preview, never the full reel | Code in PR #382: 40 % of the reel, at most 12 s, 720 px, tiled watermark; contract test | PASS in isolation, not deployed | P0 | deploy (blocked, section D) | `scripts/test_discover_preview_contract.py` |
| P0-02b | Full file only after a server-verified payment; refund revokes; replay and concurrency idempotent; signed URL expires | 11 adversarial tests run the real route handlers against a fake Supabase and a fake Stripe with real signatures | PASS in isolation, not deployed | P0 | deploy (blocked) | `web-api/scripts/entitlement-adversarial.test.ts` |
| P0-02c | No direct object URL to the paid file | Production `storage.objects` policy on bucket `reels`: service role only; bucket private | PASS | P0 | — | SQL on `pg_policies` |
| P0-02d | Reel rows are not listable with the public key | Production policy `token_access` lets anon read every `reels` row | FAIL | P1 | `supabase/migrations/20261114_security_hardening.sql` written, not applied | apply (blocked), then anon `select` returns nothing |
| P0-02e | Production payment smoke with a controlled refund | 0 purchases in production; no live keys | BLOCKED | P0 | owner supplies provider credentials and approves a live test | one real purchase and refund |
| P0-03a | No test key or secret in the production mobile profile | Stripe test key and SDK removed in PR #382; `Secrets, dependencies and configuration` check green | PASS | P0 | — | CI |
| P0-03b | Signed AAB/IPA, store metadata, submit config | `eas.json` submit: `appleId`/`ascAppId` = `FILL_IN`; no Play service-account key; no build made | BLOCKED | P0 | owner's Apple and Google accounts | `eas build` + `eas submit` |
| P0-03c | Store payment policy for a digital video purchase | Checkout opens the provider's web page; Apple and Google normally require in-app purchase for digital content | UNKNOWN | P0 | owner decision; the provider plugin can host an IAP provider | store review |
| P0-04 | Migrations applied safely before the code that needs them | `20261114_discover_preview_and_athlete_follow.sql` and `20261114_security_hardening.sql` are additive and idempotent; neither is applied | BLOCKED | P0 | owner approval (section D) | `list_migrations`, advisors |
| P0-05a | Each output is 2160x3840, 30 fps, silent, at most 90 s | The publishability gate rejects anything else (`quality_output_issues`, silent policy); 12 publishable rows of 2026-11-14 have `technical_issues=[]`; CI renders and probes a real 4K file | PASS (enforced) | P0 | measured values are now printed per reel and `fps` is stored in the manifest (this PR) | `scripts/test_quality_first_4k_media_contract.py`; next run log lines `Delivery specs` |
| P0-05b | Playback on real devices | not run | UNKNOWN | P1 | device test | manual matrix |
| P0-06 | Ground Truth and Annotation Studio reconciled with live evidence | Production `ground_truth`: 24 sources, 14 athletes, 27 appearances, 39 revisions; `evaluation_runs` = 0, `pipeline_predictions` = 0. Comparisons so far were made by hand from run logs | FAIL | P0 | import each run's predictions and record an evaluation run | rows in `evaluation_runs` |
| P0-07a | Android targets API 36 | Was 35 (Expo SDK 53 default). Set to 36 through `expo-build-properties`; the qualification build reads the level from the APK | PASS once the build check on this commit is green (see section C) | P0 | — | `full-android-app-qualification.yml` |
| P0-07b | Android 16 edge-to-edge and predictive back behave | Emulators in CI are API 35; one screen uses safe-area insets | UNKNOWN | P1 | run the Maestro suite on an API 36 image or a device | device test |
| P0-07c | Account deletion, privacy and terms inside the app | Implemented in PR #382; Maestro user journey green | PASS in isolation | P0 | deploy | CI |
| P0-07d | Data Safety form, privacy URL, closed test | not started | BLOCKED | P0 | Play Console access | console |
| P1-01 | Correlation id from upload to delivery, alerts, budget caps | `pipeline_runs` links a run to GitHub; no id crosses purchase and delivery; no alerting found | FAIL | P1 | not implemented | — |
| P1-02 | Real-device matrix (large upload, network loss, process death, checkout, RTL) | Emulator suites only; four UPL-01 Maestro jobs fail with `device offline` on `main` as well | UNKNOWN | P1 | device lab or owner's phone | manual |
| P1-03 | Supply chain | CodeQL, MobSF, OSV, secret scan and security contracts green on PR #382 | PASS | P1 | — | CI |
| P1-04a | Trigger function not callable by anon; pinned `search_path`; leaked-password protection | Supabase advisors on production report all three | FAIL | P1 | first two in `20261114_security_hardening.sql`; the third is a dashboard switch | advisors after apply |
| P1-04b | Account deletion propagates | Route and test in PR #382 | PASS in isolation | P1 | deploy | adversarial test |
| P2-01 | Funnel analytics | `analytics_events` records views only | FAIL | P2 | not implemented | — |

## B. What was implemented

Merged to `main`: PR #376 (`6362b1b`, identity: generic covered top), PR #378 (`7d6b544`, tandem ride end follows
the tracker).

In PR #382, not merged: payment provider plugin (Stripe provider, Grow placeholder that fails closed), provider-
independent fulfilment with full-refund revocation, short watermarked preview and separate paid file, persistent
non-biometric athlete id with operator-confirmed merges, follow notifications, account deletion, legal screens,
removal of the Stripe mobile SDK and test key, Android target API 36 with a check on the built APK, measured
delivery specs in the run log and manifest, two migrations, QA agent corrections (catch lead-in, recording-limited).

No dependency, paid service or infrastructure was added. `expo-build-properties` was already a dependency.

## C. Evidence ledger

| gate_id | current_sha | environment | test_command_or_run_url | dataset_version | observed_result | verdict | timestamp | blocking_issue | remediation_pr |
|---|---|---|---|---|---|---|---|---|---|
| P0-01a | `7d6b544` | production pipeline | Actions run 43583126199 | catalog of 2026-11-14 (24 sources) | 0070 and 0108 in one reel | PASS | 2026-11-14 | — | #376 |
| P0-01b | `7d6b544` | production pipeline | Actions run 43583126199 | same | 0143 and 0152 in one reel | FAIL | 2026-11-14 | detections not readable from this environment | — |
| P0-01c | `7d6b544` | production pipeline | Actions run 43583126199 | same | reel produced from 0095 | FAIL | 2026-11-14 | same | — |
| P0-01d | `7d6b544` | production pipeline | Actions run 43583126199 | same | tandem 25.8–33.8 s against 16.9–36.7 s | FAIL | 2026-11-14 | same | #378 partial |
| P0-01f | `7d6b544` | production DB | `select … from draft_publishability` for run `3eb136fd` | — | 12 PASS publishable, 1 FAIL not publishable | PASS | 2026-11-14 | — | — |
| P0-02b | PR #382 head | local, in-process fakes | `NODE_ENV=test npx tsx --test scripts/entitlement-adversarial.test.ts` | — | 11 of 11 pass | PASS (isolated) | 2026-11-14 | not deployed | #382 |
| P0-02c | — | production DB | `pg_policies` on `storage.objects` | — | bucket `reels`: service role only | PASS | 2026-11-14 | — | — |
| P0-02d | — | production DB | `pg_policy` on `public.reels` | — | `token_access`: `token is not null`, all roles | FAIL | 2026-11-14 | migration not applied | #382 |
| P0-04 | — | production DB | `supabase_migrations.schema_migrations` | — | latest `20261006190446` | BLOCKED | 2026-11-14 | owner approval | #382 |
| P0-05a | `7d6b544` | production DB + CI | `draft_publishability`; `pipeline-real-mp4.yml` | — | `technical_issues=[]` on 12 publishable rows | PASS | 2026-11-14 | — | #382 adds measured values |
| P0-06 | — | production DB | `select count(*)` on `ground_truth.*` | — | 0 evaluation runs, 0 predictions | FAIL | 2026-11-14 | — | — |
| P0-07a | PR #382 head | CI | `Prepare Android qualification APK` on PR #382 | — | recorded in the PR checks | see PR | 2026-11-14 | — | #382 |
| P1-04a | — | production | Supabase security advisors | — | definer function executable by anon; 3 mutable `search_path`; leaked-password protection off | FAIL | 2026-11-14 | migration not applied | #382 |

Observed processing cost and time: run 43583126199, about 43 minutes, model cost about $0.23 with the analysis
cache warm, 12 of 13 reels published; run 43303438106, 82 minutes, about $1.65 cold.

## D. Blocked actions, prepared

1. **Apply the two migrations to production, then merge PR #382.** Order matters: the new web-api writes
   `purchases.user_id` and reads `reels.full_storage_path`. Both files are additive and idempotent; production has
   0 reels and 0 purchases, so no row changes. Rollback for the hardening file is written at its bottom; the
   feature file is rolled back by dropping the three new tables and the added columns. Merging deploys the web-api
   to production through Vercel; the previous deployment `7d6b544` remains the rollback target.
2. **Read the diagnostics artifact** of run 43583126199 (artifact 14110304094, 4.4 MB): this environment may not
   reach the Actions artifact storage host. Either allow that host for the environment or attach the zip. It
   unblocks P0-01b, c, d and e.
3. **Store submission**: Apple id and App Store Connect app id in `mobile/eas.json`, a Play service-account key
   as an EAS secret, then `eas build --profile production` and `eas submit`. Not done here: it needs the owner's
   accounts and is a public release.
4. **Live payments**: provider credentials (Stripe live keys, or the Grow API documentation and keys for the
   placeholder provider) and a decision on in-app purchase for the stores.
5. **Supabase dashboard**: turn on leaked-password protection.

## E. Residual risk if released as is

Wrong-athlete reels (0143/0152) would be sold to the wrong person; a source judged not sellable still produces a
reel; some rides are cut short. These are caught today only by the operator's review before approval.
