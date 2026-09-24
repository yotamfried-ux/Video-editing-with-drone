# Application qualification: operator app, web-api, and backend side effects (2026-09-24)

## Identity

| Item | Value |
|---|---|
| Revision under test | `main@4846d5f` |
| Production API | Vercel `dpl_8X8PCTkozC4WNyiXc2bgibiC6e7Z`, which is `main@4846d5f` (the same revision) |
| Database | Supabase project `sportreel`. All queries were read-only. |
| Fix branch / PR | `claude/sweet-hypatia-ov5utx` / #222 (draft) |
| Out of scope | Payments: checkout completion, Stripe, payment webhooks |

## Evidence types used

- **Static**: `tsc` (mobile, web-api), `next build`, and 95 Python contract tests.
- **HTTP-local**: the built web-api (`next start`) against a recording stub of the
  Supabase REST and R2 surfaces. This proves status codes *and* the exact backend
  calls each request causes. It does not prove the behaviour of real Supabase or R2.
- **HTTP-prod**: GET requests to the production API through the Vercel connector.
  This host's network policy blocks direct access, and the connector sends GET only,
  with no custom headers.
- **DB-prod**: read-only SQL on production tables, used for cross-layer consistency.
- **Device E2E**: UPL-01 Maestro on an API-35 emulator against production
  (run 35967252145 on `main@4846d5f`).

## Capability matrix

| Capability | What was tested | Evidence | Status | Remaining gap |
|---|---|---|---|---|
| Build integrity (mobile, web-api) | tsc, jest 18/18, `next build` | Static | PASS | Proves compilation only |
| Operator authorization boundary | 27 protected handlers × 4 bad secrets = 108 requests → 401 with 0 backend calls; 9 GET positive controls | HTTP-local + HTTP-prod (3 GET routes → 401) | PASS after fix | POST boundaries not probed on production (connector is GET-only) |
| Support reply authorization ordering | Rejected callers wrote a rate-limit row, and got 503 instead of 401 when the limiter was down | HTTP-local | FAIL → fixed | Not yet deployed |
| Approval gate | Missing evidence, name mismatch, QA FAIL → 409 with no R2 move and no `delivery_runs` insert. Publishable → R2 `review/`→`approved/` move, row insert, `dispatch_failed` when dispatch is unconfigured | HTTP-local | PASS | No real approval exercised end to end this session. Retrying after `dispatch_failed` needs manual recovery, because the object has already moved. |
| Delivery status transitions | Production rows compared with GitHub run outcomes | DB-prod + Actions | FAIL → fixed in code | 2 historical delivery rows and 5 historical pipeline rows remain stale. Backfilling them needs approval. |
| Historical delivery success semantics | 5 rows are `succeeded` with a 415 error and no reel (2026-09-20, before `4c78d70`); later runs fail closed | DB-prod | PASS (current code) | Historical rows remain misleading |
| Pipeline start / reset / re-edit dispatch | Fail closed with no DB write when no verified batch exists or dispatch is unconfigured | HTTP-local | PARTIAL | No real dispatch this session |
| Pipeline status presentation | Status route shape and nullable meta handled by the screen; contract drift fixed | HTTP-local + Static | PARTIAL | Stale `queued` rows were visible until the finaliser ships |
| Gallery upload + permission/cancel/error paths (UPL-01) | Positive upload, cancelled picker, missing operator secret | Device E2E + DB-prod | PASS (no-secret negative FLAKY once on infrastructure) | SD/USB multipart, interruptions, 5xx/409 paths, real device, API ≤ 32 permission denial, filename preservation |
| Discover listing | Production `/api/sessions` → `[]`; `reels` has 0 rows. Reels expire 48 h after creation and are removed, so there is no live reel to list. Paging inputs clamped. | HTTP-prod + DB-prod + HTTP-local | PARTIAL | Needs a live published reel to prove listing contents |
| Mobile↔web-api contract | Compile-time assignability of 25 shared + 4 renamed types; 4 drifts fixed | Static | PASS after fix | Request (body) shapes are not covered |
| Auth / session (athlete) | APP-02 signup-email E2E, last green 2026-09-21 on `main@503aec2` | Actions (prior) | PARTIAL | Not re-run; login/session persistence not device-tested |
| Launch, navigation, biometric unlock | UPL-01 launches and navigates Settings → Pipeline, with biometric bypassed | Device E2E | PARTIAL | Biometric and the login screen are not exercised |
| Review / re-edit UI, delivery UI, persistence and reload | Not driven on a device | — | NOT TESTED | Needs Maestro flows |

## UPL-01 on `main@4846d5f`

Run [35967252145](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35967252145),
`workflow_dispatch` on `main@4846d5f`. Final conclusion **success** (attempt 2).

| Scenario | Result | Evidence |
|---|---|---|
| APK preparation | PASS | Checkpoint cache **missed** on `main`, so the Gradle build ran in full (11m17s) |
| `gallery-upload` (positive) | PASS (attempt 1) | Supabase: exactly one row since 06:59Z, `gallery_1790234184012_0_d5oz94xs9b`, `verified`, `single_put`, 66989 = 66989 bytes, key `raw/batch_2026-09-24T07-16-24_nmjugriv/…_1000000016.mp4`; the harness HEAD-verified the R2 object through the production verify API |
| `picker-cancelled` (negative) | PASS (attempt 1) | No new row |
| `no-operator-secret` (negative) | **FLAKY → PASS** | Attempt 1: emulator `device offline` / `DeviceServerDiedException` during `launchApp`; the final screen was the Android launcher, so no test step ran. One rerun, as policy allows for an infrastructure failure before any test body. Attempt 2 PASS. Still exactly one row after both attempts. |

The filename finding from the 2026-09-23 audit reproduces on `main`:
`source_filename = 1000000016.mp4` (a MediaStore ID), not the operator's file name.

Wall-clock: dispatch 06:59:53Z → attempt 1 done 07:16:48Z (APK 11m43s, parallel
scenarios ~5m); rerun 07:20:47Z → 07:24:52Z.

## Findings recorded

FRICTION-005 to FRICTION-009 in `docs/AI-FRICTION-LOG.md`. FRICTION-002 was
updated: the APK checkpoint is also cold on `main`.

## Independent PR review (2026-09-24, later the same day)

A review of PR #222 at `1c0d386` found and fixed two gaps (FRICTION-010): the
finaliser skipped cancelled and timed-out runs, and the probe could not see an
operator route missing auth.

The finaliser's UPDATE was validated against the real production schema with
`EXPLAIN` (no execution) for both tables. Its query string is byte-identical to
the one `supabase-js` generates for `.not('status','in',…)`. Real PostgREST over
HTTP is blocked from the agent host, so the request itself was not sent.

