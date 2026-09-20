# SportReel — Remaining Reality Validation

Updated: 2026-09-20

This is the live remaining-test queue for the reality-validation phase. A test is PASS only with auditable real-execution evidence. CI/static analysis alone does not substitute for real-world proof where the Validation Brief requires it.

## Autonomous validation operating procedure
- Execute validation as a continuous loop: Run -> inspect result -> diagnose any failure -> implement the smallest correct fix -> add/adjust regression coverage -> rerun -> verify -> continue.
- A FAIL is a trigger to investigate and fix; it is not a stopping point and must not be reported as though the work is complete.
- Do not stop merely to tell the operator that a run failed. Continue autonomously through routine, reversible diagnosis, branch fixes, regression tests, and reruns.
- Update the operator only on a meaningful PASS milestone, completion of a test group, a true blocker requiring operator action, or a dangerous/irreversible decision requiring explicit approval.
- Do not merge to main without explicit operator approval. Do not make destructive production changes.
- Real E2E requirements cannot be replaced by unit, contract, static, emulator, or mocked evidence.
- Preserve auditable evidence for each result: commit SHA, workflow/run ID, job/result, relevant logs/artifacts, and correlated Supabase/R2/API identifiers.
- Whenever a GitHub Actions run is mentioned to the operator, include a direct link to that exact run.
- Test fixtures must remain isolated and identifiable, and cleanup must not erase evidence needed for audit.

## Already evidenced PASS
- APP-01 and authenticated app journey coverage already closed.
- APP-03, APP-04, APP-05, APP-06.
- UI-01, UI-02, UI-03.
- DATA-01, DATA-02, DATA-03.
- SEC-01.
- API-01.
- R2-01, R2-02.
- Android Stability Gate: 3/3.

## Active
- APP-DLV-01 — full real Review -> Approval -> Delivery -> Discover -> public Discover E2E. Current validation branch includes MP4 MIME preservation and fail-fast behavior when Discover publication fails. Full real run must still PASS with auditable evidence.

## Remaining / must be completed
1. APP-02 — real Supabase Auth email confirmation end-to-end. Previous attempts did not establish a clean PASS; repeat after SMTP/auth configuration is verified.
2. PAY-01 — payment initiation from the actual app/client flow; verify correct product/reel/order context reaches the payment boundary.
3. PAY-02 — successful payment callback/webhook -> entitlement/final-delivery state transition, idempotency included.
4. PAY-03 — declined/cancelled/abandoned payment must not grant delivery or entitlement; retry must recover safely.
5. UPL-01 — real app upload -> R2/Supabase/backend correlation with exact object/run IDs and metadata.
6. UPL-02 — interrupted upload/restart/cancel and retry; no duplicate or orphaned authoritative state.
7. NET-01 — slow/intermittent network and Wi-Fi/mobile transition during critical app operations.
8. PERM-01 — Android permissions: allow, deny, revoke, and re-grant on a physical device.
9. INST-01 — clean install plus upgrade from the previous supported build; persisted auth/profile state checked.
10. DEV-01 — physical Android smoke on supported hardware. Emulator evidence does not count as physical-device PASS.
11. DEV-02 — physical-device coverage across the Validation Brief's required Android profiles when devices are available.
12. STORAGE-01 — low-storage behavior and recovery without corrupting upload/run state.
13. LOAD-01 — multi-video/long-session/resource-pressure validation.
14. PIPE-REAL-01 — real-footage pipeline run correlated across app/API, GitHub Actions, Supabase and R2 from one evidence chain.
15. CV-REAL-01 — real-footage detection/tracking/identity behavior; inspect false positives, misses, ID switches and multi-person cases.
16. GT-01 — compare pipeline output against ground-truth annotations/expected moments and record measurable recall/precision-style evidence required by the brief.
17. EDIT-01 — rendered clip/media validation: duration, codec/container, orientation/resolution, audio and source/time-range correctness.
18. VIS-01 — human visual review of real rendered outputs for framing, cuts, continuity, overlays and obvious quality defects.
19. QA-REAL-01 — real QA rejection -> re-edit -> re-QA -> approval loop with evidence that blocked drafts cannot bypass the gate.
20. FAIL-01 — deliberate processing/delivery failure: app and backend must expose truthful failed state, preserve evidence, and support safe retry.
21. GOLDEN-01 — golden success E2E: real user/app input -> upload -> processing -> review -> approval -> Discover -> payment/final delivery, with correlated IDs/artifacts.
22. GOLDEN-02 — golden failure/recovery E2E: inject a meaningful failure mid-flow, verify truthful state and successful recovery without duplicate publication/delivery.
23. FINAL-DEVICE-01 — final physical Android smoke after all fixes, including login, Discover, profile, upload/processing status, review/delivery surfaces and payment path.

## Closure rule
Do not declare the app-side validation complete until every applicable item above is PASS with evidence, or explicitly BLOCKED with the exact external blocker. PARTIAL, NOT RUN, emulator-only physical-device coverage, and contract-only CI checks are not PASS.
