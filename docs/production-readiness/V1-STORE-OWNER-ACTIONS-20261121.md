# SportReel V1 — release candidate ledger (2026-11-21)

**Status: NOT_READY / DRAFT FIXES.** This document tracks release work, not a production certification. No store submission, production migration, payment transaction, or environment change has been performed by this PR.

**Baseline:** main `90fa08e17b5828bb25541043c1b5dee35a29d5c6`. This PR is intended to restore missing consumer-app changes and must remain draft until checks and device validation complete. The separately stacked pipeline drafts #399/#401/#402/#403/#404/#406 remain unmerged and must not be pulled in accidentally.

## Evidence and product gates

| Gate | Verified finding | Status |
|---|---|---|
| Account deletion (in app) | `mobile/src/features/account/deleteAccount.ts` + `web-api/src/app/api/account/route.ts` already exist on main | CODE_EXISTS; live test pending |
| Public account deletion | Authenticated web deletion form added in this PR, reusing the server endpoint | CANDIDATE; HTTPS production smoke pending |
| Password recovery | Native screens and scheme-bound recovery handler added; requires Supabase redirect allowlist and actual email/cold-start verification | CANDIDATE; device test pending |
| Purchase ownership error | Distinguishes ownership network failure from `not_owned`, hides buy until authoritative retry | CANDIDATE; CI/device test pending |
| Signed Play artifact | Workflow now distinguishes `.aab` production from `.apk` preview | CANDIDATE; actual build and signing proof pending |
| Marketplace billing | Current mobile checkout opens external hosted payment for an in-app digital video; cannot assume policy exemption | BLOCKED on approved billing strategy and real integration |
| Grow provider | `web-api/src/lib/payments/providers/grow.ts` is a nonfunctional placeholder | FAIL until official API/sandbox and signed webhook + refund tests |
| iOS upload parity | Custom bounded source-reader only supports Android; iOS operator large-media workflow must not be claimed | NOT_TESTED |
| Video quality | Last inspected pipeline run had wrong/missing action evidence versus frozen GT; human Review gate stays mandatory | NOT_READY for autonomous publishing |
| Production security | Account deletion, refund, RLS, signed links, data retention and rollback need production evidence | NOT_TESTED |
| Store content | App descriptions, screenshots, privacy/data safety, content rights and reviewer accounts not certified | NOT_TESTED |

## Required owner-controlled configuration

1. **Supabase Authentication:** Add `sportreel://reset-password` to allowed Redirect URLs in Authentication → URL Configuration; verify email SMTP/delivery, expiry, repeated use, and deep-link behavior using the exact signed preview build. Do not paste service-role keys or recovery tokens into GitHub.
2. **Android:** An Expo account with access to `yotam102/sportreel` is already referenced in `mobile/app.json`. EAS can generate and remotely manage the signing keystore: a locally supplied keystore is **not** inherently required. Verify ownership and inspect `eas credentials --platform android`. Build an actual **signed production AAB**, inspect its package/version/target API/native-library 16KB compatibility, and upload to a Play internal/closed testing track.
3. **Google Play:** Create/verify the app in Play Console, complete Data Safety, privacy/support and public account-deletion URL (`https://video-editing-with-drone.vercel.app/account-deletion` after deployment), content rating and store listing. A Google service-account JSON is needed only for automated API submission, not for manually uploading an AAB. Never commit signing secrets. If a new personal account is subject to the 12-testers/14-days policy, complete the closed test before public access.
4. **iOS:** Join/verify the Apple Developer Program, set the real App Store Connect `appleId` and `ascAppId` (currently `FILL_IN` in `mobile/eas.json`), generate managed distribution credentials through an authorized Apple login, build an IPA and test in TestFlight on real iPhones. An app store build must not be equated with an Expo JavaScript export.
5. **Payments:** Determine and implement a **store-compliant in-app purchase path** for digital videos (Google Play Billing / Apple IAP unless a documented, applicable exception or program has been approved). Grow cannot be enabled merely by changing `PAYMENT_PROVIDER`; its placeholder must first be implemented from official docs and sandbox credentials. Any provider must grant an entitlement only after server-authoritative settlement.
6. **Real-device validation:** Test sign-up/recovery, deletion, session restoration, preview, approved delivery, entitlement, purchase/refund, persistent download access, network loss and app restart. The `sportreel://reset-password` link must open the installed signed build; browser and simulator-only tests cannot close this gate.
7. **Business/legal:** Verify that operators have rights to film, process, display and sell sports footage and provide a complaint/takedown channel. Review real retention/deletion behavior and accurate privacy-language with qualified counsel where necessary.

## Safe commands after owner configuration

From `mobile/`, with developer accounts authenticated and managed signing configured:

```sh
npm ci
npm run type-check
npm test -- --runInBand
eas credentials --platform android
eas build --platform android --profile production
eas build --platform ios --profile production
```

`eas submit` and public production rollouts require a separate owner-approved step, correct console IDs, policy approval and working billing. Do not use the Android internal preview APK as the Play release artifact.

## Remediation completion rule

A gate is closed only after the exact candidate SHA has passing build checks and the relevant external, device, email, payment and database evidence. No merging, deployment, production database mutation, real transaction or store submission is authorized by this document.
