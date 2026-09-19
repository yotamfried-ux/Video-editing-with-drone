# Gap registry — SportReel real-world validation campaign

Status of this file: live during execution. Every confirmed gap stays recorded
even after it is fixed.

Severity: **P0** blocks the product working as intended; **P1** blocks or
materially weakens validation; **P2** quality/maintenance.

---

## GAP-001 — Android validation harness disabled available hardware acceleration

| Field | Value |
| --- | --- |
| Severity | **P1** (validation harness; blocks all rendered UI evidence) |
| Class | A — infrastructure/tooling |
| Affected experiments | TOOL-01, APP-01, APP-02, UI-01, UI-02, UI-03, PERM-01, INSTALL-01, NET-01, DEV-01, DEV-02 |
| Code change made | Yes — new workflow, no product code touched |
| Rerun result | **Fixed and proven** |

**Observed evidence.** Capability probe run
[35436000030](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436000030):

```
dev_kvm_present=true
dev_kvm_perms=crw-rw---- root:kvm
dev_kvm_rw_for_runner=false
cpu_virt_flags=svm,
```

**Proven root cause.** `/dev/kvm` exists on the GitHub-hosted `ubuntu-24.04`
runner and the CPU advertises AMD `svm`. Hardware virtualization was available
the whole time. The device node is mode `0660`, owner `root:kvm`, and the
runner user is not in the `kvm` group — a *file permission*, not a missing
capability.

The existing qualification workflows concluded acceleration was unavailable and
compensated with `-accel off`, `disable-linux-hw-accel: true`, and the
lightweight `aosp_atd` image
(`.github/workflows/validation-android-emulator-qualification.yml`). That choice
is the direct cause of both previously observed harness failures:

- `aosp_atd` + `-accel off` stayed up but `screencap` returned **black frames**,
  so no UI was ever actually observed (campaign branch commit `db8dadb`,
  "after observing black ATD captures").
- `google_apis` + software emulation **system-ANRed** before reaching the app:
  run [35422604322](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35422604322)
  failed at `post-boot-health-3`, run
  [35422721820](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35422721820)
  failed at `post-install-health`. Boot alone took 422 s.

**Smallest fix.** One udev rule before the emulator starts:

```
KERNEL=="kvm", GROUP="kvm", MODE="0666", OPTIONS+="static_node=kvm"
udevadm control --reload-rules && udevadm trigger --name-match=kvm
```

**Result after fix.** Run
[35436104913](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436104913):
`kvm-ok` passed, and a `google_apis` API-35 emulator booted, installed the APK
and captured the full UI sequence in **4 m 24 s**, on the same runner class where
the software configuration had failed outright. Both BEFORE (the two failed
runs) and AFTER evidence are preserved.

---

## GAP-002 — Stability gate is not 3/3 cold; it required a retry

| Field | Value |
| --- | --- |
| Severity | P2 |
| Class | A — infrastructure/tooling |
| Affected experiments | TOOL-01 |
| Code change made | No |

**Observed evidence.** Run `35398470732` is green, but at `run_attempt: 2`.
Attempt 1 jobs:

| Job | Attempt 1 | Attempt 2 |
| --- | --- | --- |
| cold-run-1 | success | retained |
| cold-run-2 | success | retained |
| cold-run-3 | **failure** | success |
| stability-verdict | failure | success |

The gate's own message prints "STABILITY PROVEN: 3/3 independent cold
deterministic Android qualification runs passed", which is true only within
attempt 2 — GitHub re-runs failed jobs only. Across the whole campaign it is
**3 passes in 4 executions**, a ≈25 % cold-run failure rate.

**Root cause.** Same as GAP-001: software emulation is marginal, so cold runs
are flaky. Expected to disappear with acceleration; not yet re-measured over
three accelerated cold runs.

---

## GAP-003 — APK provenance is asserted, never verified

| Field | Value |
| --- | --- |
| Severity | **P1** |
| Class | B — validation harness |
| Affected experiments | BUILD-01, TOOL-01, every experiment claiming to test commit `356d581` |
| Code change made | Verification added in the new workflow |

**Observed evidence.** In
`.github/workflows/validation-android-emulator-qualification.yml` the APK is
fetched by build id only:

```yaml
BUILD_ID: 3884d669-850c-4b76-bba5-5e57ffcd2245
EXPECTED_APP_SHA: 356d5812097ba935401ecf3a145a2608cda68cb9
...
eas build:download --build-id "$BUILD_ID"
```

and the evidence file then states the commit as fact:

```
{"tested_app_commit":"$EXPECTED_APP_SHA", ...}
```

`EXPECTED_APP_SHA` is a hardcoded environment variable that is **never compared
against anything**. Nothing in that workflow establishes the binary was built
from `356d581`. Every downstream claim of the form "tested against commit
356d581" therefore rested on an unverified assertion.

**Fix applied in this campaign.** The new workflow calls `eas build:view
--json` and prints `PROVENANCE_EXPECTED_SHA`, `PROVENANCE_ACTUAL_SHA` and
`PROVENANCE_MATCH` from the build record's own `gitCommitHash`.

---

## GAP-004 — No pipeline run is correlatable to a specific GitHub Actions run

| Field | Value |
| --- | --- |
| Severity | **P1** |
| Class | D — product |
| Affected experiments | PIPE-01, PIPE-02, E2E-01, E2E-02, and every cross-layer correlation the brief mandates |
| Code change made | No — reported, not patched |

**Observed evidence.** PIPE-02 forensics run
[35436364183](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436364183):

```
PIPE02_WITH_GH_URL=55 PIPE02_WITH_SPECIFIC_RUN_ID=0
```

All 55 rows carry a `github_run_url`, and **not one** points at a specific run.
Every row holds the identical static workflow-page URL
`https://github.com/yotamfried-ux/Video-editing-with-drone/actions/workflows/pipeline-run.yml`.

**Root cause (from source).** In
`web-api/src/app/api/operator/pipeline/start/route.ts`:

```ts
const actionsUrl = (repo: string) =>
  `https://github.com/${repo}/actions/workflows/pipeline-run.yml`;
...
github_run_url: actionsUrl(repo),
```

The URL is computed before dispatch and is constant by construction.
`repository_dispatch` does not return a run id, so capturing the real one
requires a follow-up lookup that is not performed.

**Confirmed by follow-up.** Run
[35436448928](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436448928)
measured the dedicated column too:

```
PIPE02_WITH_GH_URL=55  PIPE02_URL_WITH_RUN_ID=0
PIPE02_WITH_GITHUB_RUN_ID_COLUMN=0
```

`github_run_id` is **NULL in all 55 rows**. Neither the URL nor the dedicated
column identifies a run. **Zero of 55 pipeline runs can be correlated to a
specific GitHub Actions run.** The gap is confirmed, not provisional.

This is precisely the failure mode the brief names: *"GitHub workflow success ≠
proof it belongs to the exact app request."* On current `main` that proof
cannot be constructed from stored state.

---

## GAP-005 — The R2-backed product path has never produced a durable reel

| Field | Value |
| --- | --- |
| Severity | **P0** |
| Class | D — product (pending confirmation of intended backend) |
| Affected experiments | DATA-01, R2-01, CV-01/02/03, DEC-01/02/03, EDIT-01/02/03, QA-01/02, E2E-01, E2E-02 |
| Code change made | No |

**Observed evidence.** Read-only inventory run
[35436291908](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436291908):

```
R2_TOP_PREFIXES=['approved/','metadata/','pending_uploads/','previews/','processed/','raw/','review/']
R2_PREFIX raw/       objects=1 bytes=0     <- the zero-byte folder placeholder only
R2_PREFIX approved/  objects=1 bytes=0
R2_PREFIX review/    objects=1 bytes=0
R2_PREFIX processed/ objects=1 bytes=0
R2_PREFIX outputs/   objects=0
R2_INFLIGHT_MULTIPART_COUNT=0
```

Every prefix contains exactly one zero-byte placeholder key and nothing else.
**The bucket holds no media whatsoever** — no source footage, no drafts, no
previews, no approved reels.

Supabase, same run and run `35436364183`:

```
pipeline_runs        = 55
reels                = 0
source_uploads       = 0
source_upload_parts  = 0
upload_batches       = 0
delivery_runs        = 0
draft_publishability = 0
reprocess_requests   = 15
pricing              = 13
```

**Interpretation, stated carefully.** 55 pipeline runs exist, of which 34 are
`status=succeeded, stage=finished, progress=1.0`, yet there are zero reels, zero
source uploads, zero upload batches, zero delivery runs, and an empty bucket.

The 55 runs are **historical and Drive-era**: the most recent is
`2026-07-22T21:05:15Z` (`status=no_input`), the last `succeeded` run is
`2026-07-16T17:10:38Z`, and one recorded error is
`"The user's Drive storage quota has been exceeded"`, which only occurs on the
Drive backend. Meanwhile `main` has advanced to `356d581` (September) and the
R2 upload/batch tables were introduced along that path.

So the defensible statement is: **the current R2-backed upload → dispatch →
pipeline → reel path has no execution history at all.** Not one source upload,
upload batch, or reel row has ever been written. No run has occurred in roughly
two months.

Whether this is a product defect or simply an unexercised new path cannot be
decided from stored state alone — it requires actually running the chain, which
is blocked on BLOCKER-002 (no footage).

---

## GAP-006 — Pipeline's dominant historical failure is "no REVIEW drafts"

| Field | Value |
| --- | --- |
| Severity | P1 |
| Class | D — product |
| Affected experiments | PIPE-02, DEC-01/02/03, QA-01, E2E-02 |
| Code change made | No |

**Observed evidence.** Of 14 runs carrying an error:

```
n=7  Pipeline completed without REVIEW drafts. Last observed stage: analyzing.
n=2  All draft uploads failed after QA; no REVIEW drafts were created.
n=2  GitHub dispatch failed (403): Resource not accessible by personal access token
n=1  All draft uploads failed: HttpError 403 ... "The user's Drive storage quota has been exceeded."
n=1  Pipeline completed without REVIEW drafts. Last observed stage: qa.
n=1  Pipeline completed without REVIEW drafts.
```

Stage breakdown:

```
finished=34, no_drafts_after_analyzing=7, all_draft_uploads_failed=3,
dispatching_reset=3, dispatch_failed=2, no_drafts_after_qa=1,
no_drafts_produced=1, workflow_dispatched=1, dispatching=1, no_input=2
```

The single most common failure is the pipeline reaching `analyzing` and
producing **no publishable draft at all** (7 occurrences). This bears directly
on the non-negotiable rule that *every eligible athlete receives one primary
publishable reel or an explicit evidence-backed rejection* — "completed without
REVIEW drafts" is neither a reel nor an evidence-backed rejection.

Two runs also failed with a GitHub PAT permission error (`Resource not
accessible by personal access token`), i.e. the dispatch credential has at some
point lacked workflow-dispatch rights.

**Not yet root-caused.** These are historical Drive-era runs; the analyzing-stage
failure has not been reproduced under the current code.

---

## GAP-007 — `pipeline_runs` has no `created_at` column

| Field | Value |
| --- | --- |
| Severity | P2 |
| Class | C — environment/schema |
| Affected experiments | PIPE-02, correlation records generally |
| Code change made | No |

Querying `pipeline_runs?order=created_at.desc` returns:

```json
{"code":"42703","message":"column pipeline_runs.created_at does not exist",
 "hint":"Perhaps you meant to reference the column \"pipeline_runs.updated_at\"."}
```

Actual columns: `error, finished_at, github_event, github_run_id,
github_run_url, id, input_files, meta, output_drafts, progress, queued_at,
source, stage, started_at, status, updated_at`.

`queued_at`/`started_at` carry creation semantics. Minor, but any correlation
tooling that assumes the Supabase convention `created_at` will fail outright.

---

## GAP-008 — Re-edit requests fail with `source_not_found`

| Field | Value |
| --- | --- |
| Severity | P1 |
| Class | D — product |
| Affected experiments | QA-02 |
| Code change made | No |

`reprocess_requests` holds 15 rows. The sampled row:

```json
{"reel_id": null,
 "draft_name": "DRAFT_surfer in a red shirt and black shorts on a white_20260612.mp4",
 "notes": "...", "status": "source_not_found",
 "created_at": "2026-06-12T20:44:10Z", "processed_at": "2026-06-13T18:45:47Z"}
```

`reel_id` is null and the request resolved to `source_not_found` — the re-edit
path could not locate the source for a draft it had itself produced. Lineage
between draft and source was not preserved. Full status distribution across all
15 rows not yet enumerated.

---

## GAP-009 — Runs report `succeeded` while recording no inputs and no outputs

| Field | Value |
| --- | --- |
| Severity | **P0** |
| Class | D — product (durable-state truthfulness) |
| Affected experiments | PIPE-02, QA-01, E2E-01, E2E-02 |
| Code change made | No |

**Observed evidence.** Run
[35436448928](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436448928):

```
PIPE02_SUCCEEDED=34  PIPE02_SUCCEEDED_WITH_OUTPUT_DRAFTS=0
PIPE02_WITH_INPUT_FILES=0
```

and per-run detail for the eight most recent successes:

```
PIPE02_DRAFTS id=f70a8fab-... finished=2026-07-16T17:10:38Z output_drafts_count=0 sample='[]'
PIPE02_DRAFTS id=abc9939c-... finished=2026-07-12T13:38:19Z output_drafts_count=0 sample='[]'
PIPE02_DRAFTS id=9cbaabcf-... finished=2026-07-11T20:04:48Z output_drafts_count=0 sample='[]'
PIPE02_DRAFTS id=f9f525c4-... finished=2026-07-11T00:59:01Z output_drafts_count=0 sample='[]'
PIPE02_DRAFTS id=354c3dad-... finished=2026-07-10T17:47:10Z output_drafts_count=0 sample='[]'
PIPE02_DRAFTS id=e8feb833-... finished=2026-07-10T16:52:03Z output_drafts_count=0 sample='[]'
PIPE02_DRAFTS id=963fa299-... finished=2026-07-10T02:27:18Z output_drafts_count=0 sample='[]'
PIPE02_DRAFTS id=d7c34d39-... finished=2026-07-09T15:49:35Z output_drafts_count=0 sample='[]'
```

**All 34 runs marked `status=succeeded, stage=finished, progress=1.0` have an
empty `output_drafts` array, and all 55 runs have an empty `input_files`
manifest.**

**Why this matters.** The brief's central correlation rule is that
*app-reported state is not proof of work done*. Here the durable record of a
"succeeded" run contains no evidence of what it ingested and no evidence of what
it produced. A `succeeded` row is therefore not verifiable evidence that a reel
was made, and combined with GAP-005 (empty bucket, `reels=0`) and GAP-004 (no
run correlation) there is **no stored artifact anywhere that ties a successful
pipeline run to a real output**.

**Honest caveat.** These are Drive-era runs. `input_files` and `output_drafts`
may have been added to the schema after those runs executed, in which case the
emptiness is a schema-evolution artifact rather than live mis-reporting. That
distinction can only be settled by executing a fresh run under current `main`,
which is blocked on BLOCKER-002. What is **not** caveated: on the evidence that
exists today, a `succeeded` status cannot be corroborated by any durable record.

---

## GAP-010 — Emitted artifacts are unreachable from the validation workstation

| Field | Value |
| --- | --- |
| Severity | P2 |
| Class | C — environment |
| Affected experiments | all experiments producing artifacts |
| Code change made | Yes — evidence committed to the branch instead |

`actions/upload-artifact` stores to `productionresultssa19.blob.core.windows.net`.
The workstation egress policy answers `403` to `CONNECT` for that host, so no
workflow artifact can be downloaded and inspected. Screenshots in particular
therefore could not be *looked at*, which is the whole point of a UI experiment.

Worked around by having the UI workflow commit captured frames to the validation
branch (logcat excluded, since it can carry device/account identifiers).
