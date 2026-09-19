# Master experiment matrix — SportReel real-world validation campaign

Executed 2026-09-19 against `main` HEAD `356d5812097ba935401ecf3a145a2608cda68cb9`.
Validation branch: `claude/sportreel-validation-execution-b9thw3`.

Allowed outcomes: PASS / FAIL / BLOCKED / PARTIAL / NOT RUN.

**Contract caveat (BLOCKER-001).** `SportReel_Codex_Real_World_Validation_Brief_v2_2.docx`
could not be located in the repository, in git history across all branches, on
the container filesystem, or in the connected Google Drive. Experiment IDs and
ordering are taken from the task description, which enumerates them in full, but
the brief's exact per-experiment acceptance criteria are unavailable. Every PASS
below is against criteria reconstructed from the task description and the
`CLAUDE.md` non-negotiable runtime rules, and is provisional pending the brief.

---

| ID | Result | What actually happened | Evidence | Gap / next action |
| --- | --- | --- | --- | --- |
| **BASE-01** | **PASS** | Recorded `main` HEAD `356d581`, both validation branch HEADs, and the diff: all three validation branches are **workflow-only**, no product code differs. Built the dependency map from route handlers and workflow files. Qualified both execution surfaces. Re-verified stability run `35398470732` and found it green at **attempt 2**, not 3/3 cold. | `validation-evidence/BASE-01/BASE-01.md`; runs `35436000030`, `35398470732` | GAP-002, GAP-003 |
| **TOOL-01** | **PASS (re-qualified)** | Prior harness was mis-qualified. Capability probe showed `/dev/kvm` present, `svm` flags, runner lacking group access. Applying the udev rule let a `google_apis` API-35 emulator boot, install the APK and capture UI in **4m24s** — the same runner class where software emulation had failed outright. | Runs `35436000030` (probe), `35436104913` (accelerated) | GAP-001 fixed; GAP-002 open (3 accelerated cold runs not yet measured) |
| **TOOL-02** | **PASS** | Agent push → automatic workflow trigger proven. R2 credentials valid (`head_bucket_status: 200`, bucket `sportreel`). Supabase service-role reads working. GitHub MCP run/job/log reads working. Workstation limits recorded: no Android, no ffmpeg, no KVM, egress denies non-allowlisted hosts. | Runs `35436000030`, `35422757493`, `35436291908` | GAP-010 (artifact download blocked) |
| **BUILD-01** | **PASS** | EAS build record reports `gitCommitHash=356d5812097ba935401ecf3a145a2608cda68cb9`, matching the expected commit exactly (`BUILD01_MATCH=true`). APK SHA-256 `997c3b4c…daa47789`, 84 409 443 bytes, reproducible across runs. The check the existing gate never performed was added and passed. | `validation-evidence/BUILD-01/BUILD-01.md`; run `35437001884` | GAP-003 closed as a verification gap; APK signing identity still unexamined |
| **APP-01** | **PASS** | Clean install (`Success`) onto a fresh API-35 emulator, `pm clear` to first-run state, cold launch via the real launcher intent: `Status: ok`, `LaunchState: COLD`, **TotalTime 3210 ms**. No fatal exception, no ANR. | `validation-evidence/UI-01/UI-01.md`; run `35436648784` | — |
| **APP-02** | **PASS** | HOME → `am force-stop` → relaunch: `Status: ok`, **TotalTime 2311 ms**, no crash on the kill/restart path. | `validation-evidence/UI-01/UI-01.md`; run `35436648784` | — |
| **UI-01** | **PASS** | Login surface captured and **visually reviewed**: "Welcome Back", email/password fields, Sign In, Create Account. No clipping, overlap or truncation; safe areas respected at 1080×2400/420 dpi. All six frames measured RENDERED (e.g. login: 1009 colours, non-black 0.9739); launcher frames ~30k colours prove the render pipeline independently. | `validation-evidence/UI-01/` (frames committed); run `35436648784` | GAP-001 fixed |
| **UI-02** | **PASS** | "Create Account" located in the live uiautomator dump and tapped at its true rendered centre **(540, 1702)**. App navigated to the registration surface: title, email, "Password (min 6 chars)", Continue, "Already have an account?", two-step progress indicator. | `validation-evidence/UI-01/`; run `35436648784` | — |
| **UI-03** | **PASS** | After force-stop the app returns to the **login** screen rather than the half-completed registration screen — correct reset for an unauthenticated session, no stale partial-signup state. | `validation-evidence/UI-01/`; run `35436648784` | — |
| **UPL-01** | **BLOCKED** | Normal upload not executed. Requires real media and creates durable R2 + Supabase state. | — | BLOCKER-002, BLOCKER-003 |
| **UPL-02** | **BLOCKED** | Network-interruption upload not executed. | — | BLOCKER-002/003. Note PR 188 (upload resilience) is **unmerged**, so `main` is the un-hardened path |
| **UPL-03** | **BLOCKED** | Resume-after-interruption not executed. | — | BLOCKER-002/003. PR 194 (multipart foundation) unmerged |
| **UPL-04** | **BLOCKED** | Process/app-restart mid-upload not executed. | — | BLOCKER-002/003 |
| **UPL-05** | **BLOCKED** | Physical SD-card source. Cannot be simulated; the brief forbids passing it on emulator evidence. | — | Requires physical hardware |
| **UPL-06** | **BLOCKED** | Physical USB source. Same. | — | Requires physical hardware |
| **DATA-01** | **PASS** | Durable state fully characterised read-only. `pipeline_runs=55`, and `reels`, `source_uploads`, `source_upload_parts`, `upload_batches`, `delivery_runs`, `draft_publishability` are **all 0**. `reprocess_requests=15`, `pricing=13`. Schema has no `created_at` on `pipeline_runs`. | Runs `35436291908`, `35436364183`, `35436448928` | GAP-005, GAP-007, GAP-009 |
| **R2-01** | **PARTIAL** | Connectivity and authorization proven (`head_bucket` 200). Inventory proves the bucket contains **only zero-byte folder placeholders** under `raw/`, `approved/`, `review/`, `processed/`; `outputs/` empty; zero in-flight multipart uploads. Correct-source-upload verification is impossible because no source object exists. | Run `35436291908` | GAP-005; BLOCKER-002 |
| **PIPE-01** | **BLOCKED** | Requires the real in-app action to dispatch a pipeline, which requires a ready upload batch, which requires real footage. Not substituted with a manual dispatch, per the brief. | — | BLOCKER-002/003 |
| **PIPE-02** | **PASS** | Full forensic characterisation of all 55 historical runs: status, stage, source, error, completion and correlation fields. Established that **0/55 carry any GitHub run identity**, **34/34 "succeeded" runs have empty `output_drafts`**, and **0/55 have `input_files`**. Dominant failure is `no_drafts_after_analyzing` (7). | Runs `35436364183`, `35436448928` | GAP-004, GAP-006, GAP-009 |
| **PIPE-03** | **BLOCKED** | Requires a fresh dispatched run to inspect execution and artifacts. | — | BLOCKER-002/003 |
| **CV-01** | **BLOCKED** | No footage exists in R2 and none in the repo. Detector/tracker output cannot be produced or inspected. | — | BLOCKER-002 |
| **CV-02** | **BLOCKED** | Same. Track IDs, athlete binding, continuity not observable. | — | BLOCKER-002 |
| **CV-03** | **BLOCKED** | Same. Ambiguous-identity and failure-closed behaviour not observable. | — | BLOCKER-002 |
| **DEC-01** | **BLOCKED** | No predictions exist to compare against ground truth. | — | BLOCKER-002, BLOCKER-004 |
| **DEC-02** | **BLOCKED** | Same. | — | BLOCKER-002/004 |
| **DEC-03** | **BLOCKED** | Same. | — | BLOCKER-002/004 |
| **EDIT-01** | **BLOCKED** | No generated reel exists anywhere to inspect: `reels=0`, bucket empty. ffprobe verification has no input. | — | BLOCKER-002 |
| **EDIT-02** | **BLOCKED** | Same — framing/crop decisions not observable. | — | BLOCKER-002 |
| **EDIT-03** | **BLOCKED** | Same — and the brief requires the final reel be **actually viewed**, which needs a reel to exist. | — | BLOCKER-002 |
| **QA-01** | **PARTIAL** | Not executed as a deliberate live failure injection. However historical state provides real evidence bearing on the same question: 34 runs report `succeeded/finished/progress=1.0` while recording no inputs and no output drafts, and no reel exists. Truthfulness of the success signal is therefore **not** established, and is actively doubtful. | Run `35436448928` | GAP-009 |
| **QA-02** | **PARTIAL** | Re-edit path not exercised live. Historical `reprocess_requests` shows a request resolving to `status=source_not_found` with `reel_id=null` — the re-edit path failed to locate the source of a draft the system itself produced. Full status distribution across the 15 rows not yet enumerated. | Run `35436364183` | GAP-008 |
| **PERF-01** | **BLOCKED** | Representative high-resolution processing cannot be measured without footage and a real run. No runtime/memory metrics are invented. | — | BLOCKER-002/003 |
| **RES-01** | **BLOCKED** | Controlled interruption/recovery of a real run not executed. | — | BLOCKER-002/003 |
| **SEC-01** | **PASS** | Eleven real unauthenticated requests to the live production API; all ten operator routes returned 401, and a wrong-but-present secret was also rejected. No durable mutation: `pipeline_runs` 55 → 55. Dispatch endpoint probed with a deliberately safe discriminator that cannot start a run. | `validation-evidence/SEC-01/SEC-01.md`; run `35436251541` | Webhook signature verification and media-token scoping remain untested |
| **E2E-01** | **BLOCKED** | The full chain cannot be demonstrated. It requires real footage → upload → dispatch → pipeline → CV → decision → edit → QA → viewable reel. | — | BLOCKER-002/003 |
| **E2E-02** | **BLOCKED** | Truthful failure/recovery cannot be demonstrated live. | — | BLOCKER-002/003 |
| **DEV-01** | **BLOCKED** | Physical-device evidence. The brief explicitly forbids inferring it from emulator success. No real-device cloud tooling is connected to this session. | — | Requires physical hardware or a device-farm credential |
| **DEV-02** | **PASS** (emulator scope) | The exact APK installs, launches and renders on **Android 11 (API 30), 13 (API 33) and 15 (API 35)**. `Success` / `Status: ok` on all three. Cold start rises 1651 → 3014 → 4903 ms with API level. | `validation-evidence/DEV-02/DEV-02-PERM-01-NET-01.md`; run `35437507304` | Not transferable to hardware (BLOCKER-005) |
| **PERM-01** | **PASS** | Declared and granted permissions enumerated from `dumpsys` on all three OS versions. **No runtime permission is granted or prompted at first launch** — the app reaches login without asking. Legacy storage permissions examined and found vestigial, not broken: the native source reader is SAF/`content://`-only, which needs no storage permission. | `validation-evidence/DEV-02/DEV-02-PERM-01-NET-01.md`; run `35437507304` | GAP-011 |
| **INSTALL-01** | **PARTIAL** | Clean install of the exact APK onto a fresh emulator succeeded repeatedly (`adb install -r` → `Success`) on **Android 11, 13 and 15**, including `pm clear` to a first-run state. Upgrade-over-existing and downgrade paths not tested. | Runs `35398470732`, `35436648784`, `35437507304` | Extend to upgrade/downgrade |
| **NET-01** | **PARTIAL** | Fully offline (airplane mode confirmed), Sign In driven at its live position. App does **not** crash, hang, or report false success; stays foreground; recovers to a usable login screen on reconnect on all three versions. API 30 and 35 surface **"Network request failed"**; **API 33 showed no error** at the same observation point. | `validation-evidence/DEV-02/DEV-02-PERM-01-NET-01.md`; run `35437507304` | GAP-012 — root cause UNKNOWN |
| **LOAD-01** | **BLOCKED** | Load behaviour requires real upload/processing traffic. | — | BLOCKER-002/003 |
| **REALDEV-01** | **BLOCKED** | Physical-device reality check. | — | Requires physical hardware |

---

## Tally

| Outcome | Count | IDs |
| --- | --- | --- |
| PASS | 14 | BASE-01, TOOL-01, TOOL-02, BUILD-01, APP-01, APP-02, UI-01, UI-02, UI-03, DATA-01, PIPE-02, SEC-01, DEV-02, PERM-01 |
| PARTIAL | 5 | R2-01, QA-01, QA-02, INSTALL-01, NET-01 |
| NOT RUN | 0 | — |
| BLOCKED | 24 | UPL-01..06, PIPE-01, PIPE-03, CV-01..03, DEC-01..03, EDIT-01..03, PERF-01, RES-01, E2E-01, E2E-02, DEV-01, LOAD-01, REALDEV-01 |
| FAIL | 0 | — see note |

**Note on zero FAILs.** No experiment is recorded as FAIL because no experiment
that could fail on product behaviour was able to run against live product
behaviour. The serious findings (GAP-004, GAP-005, GAP-009) come from
*forensic* examination of durable state, not from a live failing experiment.
They are recorded as gaps rather than as FAIL verdicts, because the experiments
that would adjudicate them — PIPE-01, E2E-01, E2E-02 — are BLOCKED. Zero FAILs
here means **not tested**, and must not be read as "nothing is wrong".

---

## Completion condition

**SportReel is NOT validated.** The campaign's key question — *can one real
session go from Android interaction through upload, backend, pipeline, CV,
decision, editing and QA to a real human-viewable final reel, with transitions
correlated?* — is **unanswered**, and two independent findings indicate it
currently cannot be answered in the affirmative from existing state:

1. No reel has ever been durably recorded (`reels=0`, bucket empty).
2. No pipeline run can be correlated to the Actions run that executed it
   (`github_run_id` NULL in all 55 rows), so even a successful future run could
   not satisfy the brief's mandatory correlation requirement without a code
   change.
