# BASE-01 — Baseline, dependency map, and execution-surface qualification

**Result: PASS** (baseline established; see the capability findings, which are
inputs to every later experiment)

Executed: 2026-09-19, by the validation execution agent.

---

## 1. Repository baseline

| Item | Value |
| --- | --- |
| `main` HEAD | `356d5812097ba935401ecf3a145a2608cda68cb9` — "Fix EAS APK download working directory (#210)" |
| Tool-qualification branch HEAD | `51a3d75afbfa7fd17db91b4bd0371141f67c01e1` — "test: reduce software ATD resource pressure" |
| Prior campaign branch HEAD | `186d3640c21cfd13fe496ab888f056b42977aada` — "test: qualify R2 read access without creating or deleting objects" |
| This campaign branch | `claude/sportreel-validation-execution-b9thw3` |

### Validation branches vs `main` — validation-only modifications

`validation/eas-maestro-tool-qualification` adds **5 files, 454 insertions, zero
product-code change**:

```
.github/workflows/validation-android-emulator-qualification.yml   235 +
.github/workflows/validation-eas-maestro-qualification.yml        122 +
.github/workflows/validation-eas-status.yml                        64 +
mobile/.eas/workflows/tool-qualification.yml                       20 +
mobile/.maestro/tool-qualification.yaml                            13 +
```

`validation/real-world-campaign-20260919` adds **3 files, 705 insertions**, also
workflow-only.

**Conclusion: no validation branch modifies SportReel product code.** Every
experiment below therefore tests `main` behaviour, not a validation-modified
variant. This is the precondition the brief requires for distinguishing current
`main` from validation-only modifications.

### Open PRs at baseline

| PR | Title | State |
| --- | --- | --- |
| 203 | fix(mobile): make Supabase reachable on a fresh clone | draft |
| 194 | Add durable R2 multipart upload foundation | draft |
| 192 | Harden mobile Stripe payments from official Stripe samples | open |
| 191 | Harden payments, perception evidence, and uploads from official references | open |
| 188 | Make R2 uploads resilient to network failures | open |
| 134 | Upload pipeline diagnostics | open |

Note PRs 188 and 194 are directly relevant to UPL-02/UPL-03 (network
interruption, resume, multipart durability) and are **not merged into `main`**.
Upload resilience experiments therefore test the un-hardened `main` behaviour.

---

## 2. Evidence-based dependency map

Derived by reading the actual route handlers and workflow definitions on `main`,
not from architecture documents.

```
Android app (Expo / React Native, mobile/)
  mobile/src/app/(auth)/login.tsx, register.tsx
  mobile/src/app/(operator)/index.tsx, pipeline.tsx, review.tsx, reels.tsx
  mobile/src/shared/lib/api.ts          -> operatorFetch boundary
  mobile/src/shared/lib/supabase.ts     -> direct Supabase auth/session
  mobile/modules/sportreel-source-reader -> native SD/USB source reader
        |
        v
Web API (Next.js on Vercel, project prj_ucNsOHpdQBum3FHgED5ZPuGimrTq)
  /api/operator/upload                  -> single-shot upload
  /api/operator/upload/multipart/{start,part-url,record-part,complete,
                                    abort,status,cleanup}
  /api/operator/upload/verify, /batch
  /api/operator/pipeline/start          -> THE dispatch boundary
  /api/operator/pipeline/{status,run,runs,reset}
  /api/operator/drafts/{,approve,feedback}, /reprocess, /delivery-status
  lib/r2-storage.ts, lib/supabase-admin.ts, lib/operator-auth.ts
        |
        +--> Supabase  (pipeline_runs, upload batch manifest, auth)
        +--> Cloudflare R2 (bucket "sportreel", raw/<batch_id>/...)
        |
        v
GitHub dispatch  (pipeline/start/route.ts)
  env GITHUB_DISPATCH_TOKEN + GITHUB_REPO
  -> repository_dispatch type "new-raw-video"
  -> .github/workflows/pipeline-run.yml
        |
        v
Pipeline (pipeline-run.yml, ubuntu-latest, timeout 350 min)
  ffmpeg via apt; torch/torchvision CPU; requirements.txt; lap; torchvision.ops.nms
  inputs: reset, full_clean, pipeline_run_id, batch_id
  concurrency group "pipeline-run", cancel-in-progress false
        |
        +--> Gemini semantic analysis
        +--> Ultralytics / BoT-SORT perception (mandatory;
             pipeline/required_perception_policy.py)
        +--> decision layer -> editor (FFmpeg 4K/30, 2160x3840, <=90s, silent)
        +--> QA / re-edit
        |
        v
Output storage + delivery
  /api/download/[download_token], /api/stream/[token]
```

### Correlation identities available in the chain

`pipeline_runs.id` (created by the API before dispatch) is passed to the
workflow as the `pipeline_run_id` input, and `github_run_url` is written back on
the row. `batch_id` links the R2 object prefix `raw/<batch_id>/` to the run. This
is the spine that PIPE-01 and E2E-01 correlation depends on, and it exists.

---

## 3. Execution-surface qualification

### 3.1 Validation workstation (this container) — **severely limited**

| Capability | State |
| --- | --- |
| `adb`, `emulator`, `sdkmanager`, `avdmanager`, `maestro` | ABSENT |
| `/dev/kvm` | **does not exist** — no emulator possible locally at any speed |
| `ffmpeg`, `ffprobe` | ABSENT |
| `eas`, `expo`, `gh`, `aws`, `wrangler`, `supabase` CLI | ABSENT |
| `node` 22, `npm`, `python3`, `java`, `docker`, `psql`, `curl`, `git` | present |
| CPU / RAM / disk | 4 cores / 15 Gi / 30 G free |
| Outbound egress | via agent proxy; **Azure blob storage is DENIED** |

**Consequence 1:** no Android work of any kind can run locally. Every UI, app,
install, and permission experiment must run on a GitHub Actions runner.

**Consequence 2 (harness constraint):** `actions/upload-artifact` artifacts are
stored on `productionresultssa19.blob.core.windows.net`, which the egress policy
rejects with `CONNECT tunnel failed, response 403`. Artifacts uploaded by a
workflow **cannot be downloaded to this workstation**. Evidence that must be
inspected has to be emitted into the workflow *log* as well as the artifact.
This is why later experiments print render statistics and inline base64
thumbnails rather than relying on artifact download.

### 3.2 GitHub Actions runner — capability probe

Run [`35436000030`](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436000030),
job `105878629303`, commit `7af8d3258917867ec65824af207313d3f5fb5d1d`,
workflow `.github/workflows/validation-capability-probe.yml`. Conclusion: success.

```
## host
runner_image=ubuntu-24.04
nproc=4
mem_total_kb=16373452
disk_avail=87G
## kvm
dev_kvm_present=true
dev_kvm_perms=crw-rw---- root:kvm
dev_kvm_rw_for_runner=false
cpu_virt_flags=svm,
## android sdk
ANDROID_SDK_ROOT=/usr/local/lib/android/sdk
adb=absent
emulator=absent
avdmanager=absent
## media tools
ffmpeg=absent
ffprobe=absent
## preinstalled system images
none preinstalled
kvm-ok skipped: /dev/kvm not usable by runner
```

**This is the single most important baseline finding of the campaign.**
`/dev/kvm` **is present** and the CPU **does** advertise the `svm`
virtualization flag. Hardware acceleration is physically available on the
runner. The only obstacle is a file permission: the node is `root:kvm` mode
`0660` and the runner user is not a member of the `kvm` group.

See GAP-001 in the gap registry. This invalidates the premise the existing
Android qualification harness was built on.

### 3.3 Backend surface — proven reachable

Run [`35422757493`](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35422757493)
(prior campaign branch, read-only, zero mutating calls) returned:

```json
{"status": "PASS", "bucket": "sportreel", "head_bucket_status": 200,
 "head_object_status": 404, "historical_probe_absent": true,
 "mutating_calls": []}
```

R2 credentials in the `production` environment are valid and the `sportreel`
bucket is reachable. This is genuine proof of R2 connectivity — it is **not**
proof that any correct source object was ever uploaded (R2-01 requires that
separately).

### 3.4 Agent dispatch capability — qualified

Push to `claude/sportreel-validation-execution-b9thw3` succeeded and
automatically triggered run `35436000030`. The agent can therefore commit, push,
and cause real workflow execution. GitHub MCP read access to runs, jobs, logs
and artifact metadata is confirmed working.

---

## 4. Re-verification of the claimed established state

The task brief states run `35398470732` passed "3/3 independent cold Android
qualification runs". Verified directly:

| Field | Observed |
| --- | --- |
| Run ID | 35398470732 |
| Workflow | Validation Android Emulator Stability Gate |
| Conclusion | success |
| head_sha | `51a3d75afbfa7fd17db91b4bd0371141f67c01e1` (matches claim) |
| **run_attempt** | **2** |

Attempt-level breakdown, retrieved from the attempt 1 jobs endpoint:

| Job | Attempt 1 | Attempt 2 |
| --- | --- | --- |
| cold-run-1 | success | (retained) |
| cold-run-2 | success | (retained) |
| cold-run-3 | **failure** — step "Run deterministic ATD stability qualification" | success |
| stability-verdict | failure | success |

**Correction to the established state.** The green run is real, but it is
**3 passes out of 4 executions across two attempts**, not 3/3 cold first-pass.
GitHub re-runs only failed jobs, so attempt 2 re-ran cold-run-3 alone. The
harness has a demonstrated ≈25% cold-run failure rate. Recorded as GAP-002.

Additionally, what the gate actually proves is narrower than "healthy Android
environment": inspection of the workflow shows it asserts
`"tested_app_commit": "$EXPECTED_APP_SHA"` into `evidence.json` from a
**hardcoded env var that is never checked against the build**. The APK is
fetched by `BUILD_ID` only. Nothing in that workflow verifies the binary was
built from `356d581`. Recorded as GAP-003.

---

## 5. Authoritative-contract blocker

`SportReel_Codex_Real_World_Validation_Brief_v2_2.docx` is **not reachable**
from this session. Searched: repository working tree, full git history across
all branches (`--diff-filter=A`), the whole container filesystem, `/mnt/attach`,
`/mnt/user-data`, and the connected Google Drive (by title, by full text, and by
exhaustive `.docx` MIME listing). It is not present in any of them.

Consequence: the experiment IDs and execution order are taken from the task
description, which enumerates them completely. The **exact per-experiment
acceptance criteria and evidence requirements from the brief are unavailable**,
so no experiment can be marked PASS against the brief's own wording. Where an
experiment is marked PASS below, it is against criteria reconstructed from the
task description and `CLAUDE.md` runtime rules, and that reconstruction is
stated explicitly. See BLOCKER-001.
