# SportReel Android — Living Application Gap Register

**Established:** 2026-11-16  
**Status:** OPEN — living gap register; not a production-readiness certificate  
**Repository baseline inspected:** main at a11b4012296c2ecb967f37280952c35598b66677 (PR #390 merged).  
**Scope:** Android client, account/auth, operator UI, approved-reel delivery to Discover, preview, payment, entitlement, customer support, release and store compliance.  
**Out of scope for this register:** CV accuracy, segmentation, identity inference, render/pipeline algorithms and their separate RC-01–RC-10 qualification. The app still depends on a safe publishability decision from those systems.
**Separate pipeline quality gaps and 20-run regression analysis:** [PIPELINE-QUALITY-GAP-REGISTER.md](./PIPELINE-QUALITY-GAP-REGISTER.md).

## Reading this document

This is an evidence-backed **inventory of gaps**, not a claim that fixes have been made or tested. The owner will supply additional gaps over time. **Never mark an item CLOSED solely because a PR exists, CI passed, a mock screen looks right or a developer reports success.**

Status vocabulary: **CONFIRMED_GAP** (direct code evidence), **UNVERIFIED** (missing end-to-end evidence), **POLICY_DECISION** (store/platform determination needed), **IMPROVEMENT** (quality opportunity), **RESOLVED_VERIFIED** (only with final-head test and appropriate runtime evidence).

Priority vocabulary: **P0** blocks public release or a core paid journey; **P1** important for usable/secure beta; **P2** polish/measurement. A P0 marked policy-dependent is *not* permission to bypass the policy.

For each future gap, maintain an immutable ID, date, source report, reproducer, expected/actual behavior, user impact, priority, evidence strength, code links, fix proposal, tests, dependency, owner decision, PR/commit, deployed environment and verified status. New reports should be appended, not used to overwrite historical claims. Distinguish issues in the app from issues upstream of its API.

## A. Current observed product path

1. Operator approves a draft in mobile/src/app/(operator)/review.tsx through POST /api/operator/drafts/approve.
2. web-api/src/lib/operator-draft-approve.ts checks server-side publishability and an active re-edit block, moves the draft to Approved, creates a delivery_runs row and dispatches the GitHub 'reel-approved' delivery workflow.
3. .github/workflows/deliver.yml calls deliver.py -> services/delivery.py::deliver_preview, generating a watermarked preview and publishing a record via integrations/supabase_uploader.py::publish_reel_approved.
4. GET /api/sessions selects reels in published/viewed/sold states, grouped by date and sport. mobile/src/app/(tabs)/discover.tsx lists these reels; mobile/src/features/sessions/components/ReelThumb.tsx currently shows a sport icon rather than an actual extracted thumbnail.
5. GET /api/stream/:token returns a short, watermarked, signed preview. The full clean file is not returned from this public endpoint.
6. Customer checkout is created via POST /api/checkout/:token. The mobile app opens a hosted URL, then the authenticated ownership endpoint checks a confirmed paid purchase and signs the full-resolution download.

**Important:** An approved draft is not itself a Discover item. Discovery must show it **only after** delivery has successfully published a valid preview and protected full asset, with server-authoritative status. Never make every approved file publicly visible by querying Approved storage directly.

## B. Priority register

| ID | Priority | Status | Gap / required product outcome | Evidence and test gate |
|---|---|---|---|---|
| APP-001 | P0 | CONFIRMED_GAP | Implement real Grow adapter and production payment verification; no Stripe default assumption | Grow provider stub returns false and throws; sandbox contract + signed/corroborated webhook + controlled live sale/refund |
| APP-002 | P0 | POLICY_DECISION | Define Google Play-compliant purchase experience while retaining Grow wherever allowed | Google's digital-content billing restrictions; country/program review + Play Console evidence |
| APP-003 | P0 | UNVERIFIED | End-to-end payment, ownership, download, refund and duplicate-purchase behavior | Zero production purchases in the inspected environment; device + provider + DB/storage E2E |
| APP-004 | P1 | CONFIRMED_GAP | Do not show 'not purchased' when ownership lookup fails; recover purchases and downloads across app restarts | mobile/src/features/reel/useReelOwnership.ts catch resets to null; state-machine and failure tests |
| APP-005 | P1 | CONFIRMED_GAP | Real thumbnail images and useful metadata/search in Discover | ReelThumb renders icons; API lacks thumbnail URL; actual published asset test |
| APP-006 | P0 | UNVERIFIED | One approval -> exactly one safely delivered Discover reel; no phantom publish or duplicates | approveDraftPost + deliver_preview; verify dispatch failure, retry and idempotent output |
| APP-007 | P1 | IMPROVEMENT | Short continuous signup/signin, post-confirmation resume, guest browsing | two-step signup with password/name; email-confirmation branch; real-device onboarding study |
| APP-008 | P1 | CONFIRMED_GAP | Email password reset with Supabase Auth and Resend SMTP | No reset screen/handler in mobile; reset email -> trusted link -> new password -> login |
| APP-009 | P1 | IMPROVEMENT | Task-centered operator home and clearer navigation/actions | Eight horizontally scrolling sections in OperatorNav, separate Pipeline/Review/Reels views |
| APP-010 | P0 | UNVERIFIED | Signed production release AAB, Play review package, versioning and native binary validation | Recent CI produced Android qualification APK, not a store-approved release |
| APP-011 | P0 | UNVERIFIED | Physical-device reliability, Android 16, launch/rotation/network/background/restart, media and large uploads | Emulator Maestro success alone is insufficient |
| APP-012 | P0 | CONFIRMED_GAP | Public account-deletion-request web route plus verified in-app deletion/data retention | In-app DELETE /api/account exists; no public self-service deletion request route evidenced |
| APP-013 | P1 | UNVERIFIED | Auth/RLS, secret segregation, checkout authorization and privacy security reviewed on exact release | SecureStore and server checks exist; adversarial production-profile qualification still required |
| APP-014 | P1 | UNVERIFIED | Payment return/deep link and receipt experience without false success | Checkout opens browser; success page supports return, but real-device continuity unproven |
| APP-015 | P0 | UNVERIFIED | Accurate Terms/Privacy, marketplace billing/refund declarations, Data Safety and support | Existing documents are draft text; console declarations and legal review unverified |
| APP-016 | P1 | IMPROVEMENT | Observability for approval -> delivery -> Discover -> purchase -> download, without PII leakage | Existing delivery_runs, crash endpoint and partial analytics; linked funnel not proven |
| APP-017 | P1 | UNVERIFIED | RTL/Hebrew, accessibility, touch targets, screen readers, slow/offline states and adaptive layouts | Majority of present app copy English; device UX qualification not recorded |
| APP-018 | P1 | UNVERIFIED | Full customer purchase-support process (receipts, refund support, entitlement restore) | Support UI exists; real ticket/receipt/refund journey unproven |
| APP-019 | P1 | UNVERIFIED | Operator authorization lifecycle, unlock/relock, sensitive actions, test-only bypass impossible in release | Biometric local unlock + SecureStore secret; verify server-side authorization and release build env |
| APP-020 | P2 | IMPROVEMENT | Real-world usability metrics, search-to-preview conversion, drop-off analysis | Existing analytics incomplete; require consent-safe measurement and baseline |

## C. Detailed remediation and acceptance

### APP-001 / APP-002 — Grow + Google Play policy

**Code evidence:** web-api/src/lib/payments/providers/grow.ts explicitly describes itself as a placeholder; isConfigured() is false, and createCheckout/parseWebhook/getSessionStatus throw. web-api/src/lib/payments/registry.ts defaults to Stripe when PAYMENT_PROVIDER is absent. The user has selected **Grow** as the intended merchant provider, but the repository does **not** yet establish a working Grow payment integration.

**Implementation:** obtain the actual Grow/Meshulam merchant API documentation, sandbox credentials and verified notification format; implement the existing PaymentProvider interface without guessing provider field names, security headers or amounts. Keep credentials server-side, select Grow explicitly and fail closed if misconfigured. Verify authenticated provider notifications or server-to-server transaction status before granting access. Support duplicate/out-of-order webhook, cancellation, expiry, partial/full refunds, failed session creation and idempotent fulfillment. Amounts are integer agorot.

**Google Play decision:** purchased personal video is likely a digital good accessible in-app. The default rule prohibits an in-app link to external checkout for digital goods unless a current applicable exception/program permits it. **Grow being the payment processor does not itself confer an exception.** Determine distribution channels and purchaser countries; review official policy and enrolled programs with evidence. Choose a compliant route: (A) eligible Play Billing for in-app digital purchases while Grow remains for other permitted channels; (B) approved regional alternative/external-offer route if *confirmed eligible*; or (C) an approved consumption-only Play app with no prohibited steering and Grow checkout outside the app, if its UX and policy allow. Do not display a non-compliant Grow pay CTA in the Play build; do not invent enrollment eligibility. A separately distributed Android build may have a different payment policy, subject to applicable law/security.

**Acceptance:** exact merchant sandbox transaction verified independently; fake webhook cannot grant ownership; one paid transaction -> one purchase entitlement; refund revokes where contract requires; purchase can be restored; Google Play channel behavior backed by written policy determination and a working binary. Owner must approve any real-money trial and marketplace enrollment.

**Reuse:** web-api/src/lib/payments/types.ts, providers/stripe.ts only as an *adapter architecture* example, payments/fulfillment.ts, web-api/scripts/payments-plugin.test.ts and entitlement-adversarial.test.ts. Do not copy Stripe-specific payload fields into Grow.

### APP-003 / APP-004 / APP-014 / APP-018 — Customer purchase experience

**Current components:** mobile/src/app/reel/[token].tsx, checkout/[token].tsx, features/payment/hooks/useCheckout.ts, features/reel/useReelOwnership.ts and web-api/src/app/checkout/success/page.tsx.

**Desired journey:** open watermarked preview -> see exact price, contents, expiry and refund policy -> permitted purchase flow -> authoritative pending/paid/failed/refunded status -> automatic in-app recognition or clear receipt/restore -> full-file download and access on another device -> support/refund path.

Separate entitlement state **UNKNOWN_LOADING / NETWORK_ERROR / NOT_OWNED / PENDING / OWNED / REFUNDED**. A network error must not reactivate Buy as if the user definitively has no purchase. If guest checkout remains enabled, provide verifiable recovery via purchase email/link/claim and fraud-resistant account association; otherwise require a minimal account before creating a non-recoverable purchase. Avoid charging twice and do not trust a browser redirect as proof of payment.

**Acceptance:** purchase and return from external app in test environment (where permitted), same session on fresh phone, process death mid-payment, unpaid redirect, delayed webhook, double tap, timeout, chargeback/refund, retry after network loss, download failure/retry and expired signed link are tested against authoritative backend rows. No unconfirmed success screens.

### APP-005 / APP-006 — Approval-to-Discover as one reliable transaction journey

**Required behavior:** Review approval is the **only operator-triggered path** into Discover, after publishability checks. Preserve draft id, source/revision, approved_by, approval time, delivery_run_id, preview asset checksum, protected full-asset reference and eventual reel id. The API must never reveal raw or unapproved drafts.

**Delivery states:** APPROVED -> DELIVERY_QUEUED -> GENERATING_PREVIEW -> ASSETS_VERIFIED -> DISCOVER_PUBLISHED; explicit DELIVERY_FAILED / RETRY_WAITING / REVOKED. Do not conflate 'approved', 'dispatch sent', 'assets uploaded' and 'publicly discoverable'. Make retries idempotent by stable approval/output revision and an atomic DB constraint or equivalent; handle moved file + DB failure, a failing workflow dispatch, duplicate dispatch, partial uploads and expired previews. The delivery worker should publish the reels row only when preview and full asset are verifiably present, watermark and metadata correct; reconcile any incomplete transitions safely.

**Discover UI:** replace placeholder sport icons with thumbnails extracted from the **approved preview**, stored under the existing private media storage. The public list should receive a permitted signed/short-lived thumbnail URL and alt/description, sport, session date, optional grounded location/time, preview duration, availability and pricing when verified. Support skeletons, empty/error/retry, pagination, filtering by date/sport and search; do not assume every viewer owns a reel. No exposure of full quality before payment. Verify that returning to Discover after approval actually displays exactly the new published item (freshness/reload).

**Important cross-system boundary:** This work does not attempt to repair CV/pipeline content or auto-approve blocked drafts. It only handles what happens *after* a server-authorized approval.

**Acceptance:** one manually approved draft creates exactly one public Discover card whose thumbnail corresponds to the right preview; an unapproved, QA-blocked or only-in-progress draft never appears; repeated dispatch produces no duplicates; playback uses watermarked preview; full file remains protected; failure and retry are auditable. Correlate UI, delivery_runs, database and storage; use a safe known sample, not a paid pipeline rerun.

**Reuse:** web-api/src/lib/operator-draft-approve.ts, services/delivery.py, integrations/supabase_uploader.py::publish_reel_approved, web-api/src/app/api/sessions/route.ts and mobile/src/features/sessions/hooks/useSessions.ts. Extend these instead of creating a duplicate media service.

### APP-007 / APP-008 — Short registration and email recovery

**Desired new-user path:** Discover may be browsed without an account where policy permits; defer authentication until the user needs purchasing history, follows or profile access. Keep registration minimal: email + password, honest terms, then a short optional/prompted name step. After email verification return the user to the original reel, complete onboarding without duplicate account creation and avoid forcing a second login unnecessarily. Clarify pending confirmation and resend confirmation, with abuse limits.

**Password reset:** 'Forgot password?' -> request email -> neutral success (do not reveal whether the account exists) -> Supabase recovery link -> app/web deep link verified against a strict allowlist -> new password -> verified session -> clear success/return. Do not create custom reusable reset tokens or send email directly from the device. Recommend using existing Supabase Auth password recovery and **Resend as custom SMTP** (or an authorized Auth Send Email Hook if truly needed), rather than duplicating credential management. Configure SPF/DKIM/DMARC, authenticated sending domain, rate limits and recovery templates; secret is dashboard/server-side only. Reuse an existing Resend account/key when possible; do not require a new account without a documented reason.

**Acceptance:** email received in real mailbox, link once/expiry and malformed/cross-device cases, no account enumeration, successful password update, previous credentials no longer work, deep link survives app process death, no tokens in logs. Test a fresh account and a confirmed account. Validate no unnecessary screens/mandatory data entry.

**Reuse:** mobile/src/features/auth/hooks/useRegistration.ts, Supabase Auth, mobile/src/shared/lib/secureStorage.ts; Engineering-OS docs/ui-ux/SCREEN-CONTENT-PLAYBOOK.md. Official: https://supabase.com/docs/guides/auth/auth-smtp .

### APP-009 / APP-016 / APP-017 — Operator navigation, observability, accessibility

**Operator information architecture:** group eight horizontally scrolling destinations under (1) 'Today' dashboard with pending approvals, failed deliveries, uploads needing retry and support tickets, (2) 'Reels' (review, published, athlete links), (3) 'Operations' (uploads, pipeline status, pricing, analytics), (4) 'Settings & Support'. A large operator-only screen must not be required for a normal customer's journey. Retain existing working routes; new IA should not remove capabilities.

**Interaction contract:** every critical action uses explicit confirmation with meaningful consequence, truthful progress, non-duplicating submission, recoverable state and final server-backed outcome. Show delivery status distinctly from approval. Provide direct navigation from a failed delivery or blocked draft to its cause/action. Ensure logout/relock and app background behavior protect operator access. Accessibility: TalkBack, 200% font, touch targets, contrast, safe areas, keyboard, RTL Hebrew and understandable text.

**Acceptance:** run representative operator journeys on installed APK and check backend side effects (not just taps). Record usability feedback, time-to-approve and number of accidental wrong actions. Add privacy-safe trace IDs to approval -> delivery -> discover -> purchase -> entitlement; no raw tokens/secrets in crash logging.

**Reuse:** mobile/src/features/operator/components/OperatorNav.tsx, mobile/src/app/(operator)/review.tsx, pipeline.tsx, reels.tsx and delivery_runs. Consult Engineering-OS docs/ui-ux/EXPERIENCE-ROUTING.md, PRODUCT-EXPERIENCE-QUALITY-GATE.md and capability-registry/application-testing/maestro-mcp.md.

### APP-010 / APP-011 / APP-012 / APP-013 / APP-015 / APP-019 — Release and security

**Distribution:** create a signed production AAB with stable application ID, incremented versionCode, current target API and Play App Signing. Check native libraries for current platform requirements including 16 KB pages where relevant; verify Expo/EAS channels, secrets, production backend and deep links. No test-only bypass or debugging credential in release. The emulator qualification APK is **not** equivalent to Play release approval.

**Physical-device matrix:** Android versions/devices including Android 16; first install; cold start offline; signup/recovery; media playback; permission denial/regrant; background/foreground; process killed during purchase and upload; storage low; reconnect; app upgrade; push notifications; TalkBack; Hebrew RTL; crash and ANR review. Test actual signed release binary.

**Privacy/compliance:** in-app deletion exists, but verify a public external deletion request URL and its identity verification, deletions vs legally retained transaction records, audit/data export, support channel, privacy disclosures and actual SDK/network data flows. Align Google Play Data Safety and age/ads/permissions with code. Confirm operator's secret is server-validated, biometric gate does not replace server authorization, and Expo validation-only bypass is absent from production. Complete store screenshots, truthful listing and reviewer account via private console fields.

**Acceptance:** release-qualified AAB installed through internal/closed Play track; device and security test evidence tied to SHA/build version; refund/account deletion data and privacy claims verified; store access and payment policy accepted by appropriate reviewer; owner authorizes rollout. Do not imply approval from green CI.

## D. Work packages and dependencies

| Package | Depends on | Deliverable | Exit proof |
|---|---|---|---|
| W1 — Commerce architecture | Grow API docs + Google Play billing policy choice | Compliant channel-aware checkout and real Grow provider | Provider sandbox, signed webhook and policy decision |
| W2 — Identity and recovery | Resend verified sender + Supabase Auth settings | Simplified signup, email recovery, verified deep links | Device + mailbox E2E |
| W3 — Publish to Discover | Existing approval and delivery contracts | Atomic/idempotent approval -> assets -> Discover; real thumbnails | Single approved fixture + DB/storage/UI correlation |
| W4 — Customer experience | W1, W2, W3 | Preview, checkout, entitlement restoration, download, refunds/support | Payment E2E and failure matrix |
| W5 — Operator UX | Existing operator API + W3 statuses | Task-first interface and recovery actions | Maestro + representative operator walkthrough |
| W6 — Store and stability | W1–W5 | Signed release, privacy, console pack, real-device reliability | Play closed-track qualification + owner approval |

Safe independent steps (docs, tests, mock/sandbox UI, read-only audit) may proceed in parallel. **Do not** apply production schema changes, spend real money, deploy a new billing model or publish to the store without owner approval. Keep original protected video and user data unchanged.

## E. Reusable code and Engineering-OS references

Project-native:
- PaymentProvider and provider-neutral checkout/webhook: web-api/src/lib/payments/types.ts, registry.ts, providers/stripe.ts (architecture only, not Grow protocol), payments/fulfillment.ts.
- Approval/delivery: web-api/src/lib/operator-draft-approve.ts, services/delivery.py, .github/workflows/deliver.yml, integrations/supabase_uploader.py.
- Listing/viewing: web-api/src/app/api/sessions/route.ts, mobile/src/features/sessions/hooks/useSessions.ts, ReelThumb.tsx and mobile/src/app/reel/[token].tsx.
- Auth/recovery primitives: mobile/src/features/auth/hooks/useRegistration.ts, mobile/src/shared/lib/supabase.ts and secureStorage.ts.
- Tests: mobile/.maestro/app-e2e/, mobile/.maestro/upl01/, scripts/test_discover_preview_contract.py, web-api/scripts/entitlement-adversarial.test.ts.

Engineering-OS:
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/ui-ux/EXPERIENCE-ROUTING.md
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/ui-ux/SCREEN-CONTENT-PLAYBOOK.md
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/ui-ux/PRODUCT-EXPERIENCE-QUALITY-GATE.md
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/patterns/testing/FAST-PATH.md
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/capability-registry/application-testing/maestro-mcp.md
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/capability-registry/release-readiness/GOOGLE-PLAY-SUBMISSION.md
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/reference-repositories/supabase-examples.md
- https://github.com/yotamfried-ux/Engineering-OS/blob/main/docs/official-docs/expo.md

Official policy / implementation references (recheck at implementation and submission):
- https://support.google.com/googleplay/android-developer/answer/10281818
- https://support.google.com/googleplay/android-developer/answer/14372887
- https://support.google.com/googleplay/android-developer/answer/10144311
- https://supabase.com/docs/guides/auth/auth-smtp
- https://docs.expo.dev/build/introduction/

## F. Acceptance gates

GATE-MOB-01: Every user-facing critical action produces observable and authoritative success/failure, including recoverable errors.
GATE-MOB-02: Approved-and-delivered reels appear once in Discover with a truthful visual preview; blocked/unapproved media never appears.
GATE-MOB-03: Payments are channel-compliant, verified server-side; full files and entitlement recovery work without unauthorized disclosure.
GATE-MOB-04: Signup, verification, password reset, session restore and account deletion work on real devices with correctly delivered email.
GATE-MOB-05: Operator can safely approve, monitor delivery, retry a failed operation and correlate its outcome; server checks every privilege.
GATE-MOB-06: Signed release artifact and production backend pass physical-device, security, accessibility and store checks.

Each gate has one of PASS_VERIFIED / FAIL / BLOCKED_EXTERNAL / NOT_TESTED; evidence must identify final SHA, device, backend, test date and backend artifact. **Current verdict: NOT_READY for public release** — no inference from source-only work.

## G. Append-only intake for next user-reported gap

Copy this block for the next ID (APP-021 onward):

    ### APP-021 — [short neutral symptom]
    Reported: [date; user's exact observation]
    Component/journey: [specific screen, user role and action]
    Expected: [behavior]
    Actual: [observed behavior; unknown unless reproduced]
    Impact: [wrong charge / lost customer / confusion / operator risk]
    Hypotheses: [labeled, not yet proven]
    Evidence: [device, app build, logs, request/DB IDs, screen/video]
    Priority/status: [P0/P1/P2; CONFIRMED_GAP/UNVERIFIED/...]
    Proposed fix: [smallest safe change + existing code reuse]
    Verification: [negative/positive fixture + real device/API]
    PR/commit/deployment: [when available]
    Closure: [independent result, never an agent assertion]

On future reports, append and cross-link rather than silently modifying older evidence. Keep all conclusions tied to the exact current revision, not a past PR.

---
**Owner-controlled operations:** no production writes or deletions, no real-money payments, no new paid service, no rollout, no automatic merge of application changes. This document itself is safe to merge independently of those decisions.
