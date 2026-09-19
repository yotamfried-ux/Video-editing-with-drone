# Blockers requiring the user — SportReel validation campaign

Each entry gives: experiment IDs, what was attempted, what is already proven,
the exact blocker, the exact action needed, and the evidence needed back.

---

## BLOCKER-001 — The authoritative validation brief is unavailable

**Experiment IDs:** all (defines acceptance criteria for every one)

**What I attempted.** Located `SportReel_Codex_Real_World_Validation_Brief_v2_2.docx` by
searching, in order:

- the repository working tree;
- full git history across all branches (`git log --all --diff-filter=A`);
- every branch tree on the remote;
- the entire container filesystem (`find / -iname "*.docx"`, `find / -iname "*Validation_Brief*"`);
- `/mnt/attach` and `/mnt/user-data` (both empty);
- the connected Google Drive — by title (`Validation`+`Brief`), by `SportReel`
  full-text, by `Codex`/`Real_World` title match, and by exhaustive listing of
  every `.docx` in the account.

It is in none of them.

**What is already proven.** The experiment IDs and execution order in your task
description are complete and self-consistent, so the *matrix* is intact — all 43
IDs are carried through with terminal classifications. What is missing is the
brief's per-experiment **acceptance criteria and evidence requirements**.

**Exact blocker.** I cannot verify any experiment against its authoritative
acceptance criteria. Every PASS I recorded is against criteria reconstructed
from your task description plus the `CLAUDE.md` non-negotiable rules, and is
explicitly marked provisional.

**Exact action required from you.** Attach the `.docx`, or paste its contents,
or share it to the Google Drive account `yotam.fried@gmail.com` (I can then read
it directly).

**Evidence needed back.** The document itself.

---

## BLOCKER-002 — No validation footage exists anywhere reachable

**Experiment IDs:** CV-01, CV-02, CV-03, DEC-01, DEC-02, DEC-03, EDIT-01,
EDIT-02, EDIT-03, PERF-01, LOAD-01, E2E-01, E2E-02, and the source side of
UPL-01..04

**What I attempted.** A read-only inventory of the R2 bucket `sportreel`
(run [35436291908](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436291908)),
listing every object under `raw/`, `approved/`, `review/`, `processed/`,
`outputs/`, plus in-flight multipart uploads; and a search of the repository for
any tracked media.

**What is already proven.**

```
R2_TOP_PREFIXES=['approved/','metadata/','pending_uploads/','previews/','processed/','raw/','review/']
R2_PREFIX raw/       objects=1 bytes=0     <- zero-byte folder placeholder only
R2_PREFIX approved/  objects=1 bytes=0
R2_PREFIX review/    objects=1 bytes=0
R2_PREFIX processed/ objects=1 bytes=0
R2_PREFIX outputs/   objects=0
R2_INFLIGHT_MULTIPART_COUNT=0
```

The bucket holds **no media of any kind**. The repository tracks no video files.
R2 credentials and connectivity are proven working (`head_bucket_status: 200`),
so this is genuinely "nothing is there", not "I could not look".

**Exact blocker.** There is no source footage to run perception, decision or
editing against, and no output reel to inspect. These experiments cannot be
executed, not merely cannot be passed.

**Exact action required from you.** Provide frozen validation footage and say
where it should live. Smallest useful first step, matching the brief's
"start small" rule: **one short 4K/30 surf or drone clip** (10–30 s) containing
one clearly identifiable athlete performing one complete action. Either upload
it to `raw/<batch_id>/` in the `sportreel` bucket yourself, or authorize me to
(see BLOCKER-003).

**Evidence needed back.** The R2 object key, byte size and SHA-256 of each
uploaded source file, plus confirmation of the `batch_id`.

---

## BLOCKER-003 — Authorization to create durable state and incur processing cost

**Experiment IDs:** UPL-01..04, PIPE-01, PIPE-03, RES-01, PERF-01, LOAD-01,
E2E-01, E2E-02, QA-01, QA-02

**What I attempted.** Nothing mutating. Every experiment executed so far was
read-only or confined to a throwaway emulator. The one probe that touched a
mutation endpoint (SEC-01 against `/api/operator/pipeline/start`) was
deliberately constructed so it could not dispatch under any outcome, and I
verified afterwards that `pipeline_runs` stayed at 55.

**What is already proven.** The dispatch chain exists and is wired:
mobile → `operatorFetch` → `/api/operator/pipeline/start` → `pipeline_runs`
insert → `repository_dispatch: new-raw-video` → `pipeline-run.yml`. The operator
boundary correctly rejects unauthenticated callers. The production deployment is
live at exactly `main` HEAD `356d581`.

**Exact blocker.** Executing the upload and pipeline experiments necessarily:

1. writes real objects into the production R2 bucket;
2. inserts real rows into production Supabase (`pipeline_runs`, `upload_batches`, `source_uploads`);
3. starts a real GitHub Actions pipeline run (up to 350 min timeout);
4. **incurs real Gemini API usage**, and real CV/tracking compute.

Point 4 is new paid usage, which your safety policy says I must not incur
without explicit approval. Points 1–3 are production mutations.

**Exact action required from you.** An explicit yes/no on: *"Run one
smallest-possible real upload → dispatch → pipeline cycle against production,
using an isolated `batch_id` prefixed `validation-`, accepting the Gemini and
Actions cost of one short clip."* If yes, please also confirm whether I may
later delete the validation objects I create, or should leave them.

**Evidence needed back.** Just the approval. I will produce the correlation
record (batch id, R2 keys and hashes, `pipeline_runs.id`, Actions run id and
attempt, workflow commit, output identity) myself.

---

## BLOCKER-004 — Frozen ground truth requires human visual annotation

**Experiment IDs:** DEC-01, DEC-02, DEC-03 (and the comparison half of CV-01..03)

**What I attempted.** Searched for an existing label set. The repository contains
only *design* documents — `docs/ground-truth-annotation-guidelines-v1.md`,
`docs/ground-truth-annotation-system-design.md`, and a design-review addendum.
**No actual label file exists**, versioned or otherwise.

**Exact blocker.** The brief requires ground-truth labels to be created and
frozen **before** predictions are observed, carrying source ID, timestamps,
athlete identity, usable-action yes/no, completeness, readability and rejection
reason. Those are human visual judgements about specific footage. I cannot
author them: I have no footage, and even with footage, fabricating labels would
destroy the experiment's validity.

**Exact action required from you.** Once footage exists (BLOCKER-002), label it —
per usable action: start/end timestamps, athlete identity, complete yes/no,
readable yes/no, usable yes/no, and rejection reason where not usable.

**Evidence needed back.** The label file. I will hash and version it, commit it
unchanged, and only then compare predictions against it — and I will not modify
it afterwards.

---

## BLOCKER-005 — Physical Android device evidence

**Experiment IDs:** DEV-01, REALDEV-01, UPL-05 (SD card), UPL-06 (USB)

**What I attempted.** Established the full emulator capability now available
(accelerated `google_apis` API 35, real rendering, ~3 min per cycle) and
confirmed no real-device cloud tooling (Firebase Test Lab, BrowserStack, Sauce)
is connected to this session.

**What is already proven.** The exact APK installs and launches on a clean
Android 35 emulator. Per the brief, that is explicitly **not** transferable to
physical-device readiness.

**Exact blocker.** SD-card and USB-OTG source reading, and real-device
behaviour, need physical hardware. The app ships a native module
(`mobile/modules/sportreel-source-reader`) specifically for this; the prior
campaign only verified the `SportReelSourceReader` symbol is present in the
APK's DEX, which proves the code shipped, not that it works.

**Exact action required from you.** Either (a) connect a device-farm credential
and I will drive DEV-01/REALDEV-01 there, or (b) run the physical procedure
yourself on a real Android phone.

**Procedure for (b), UPL-05 / UPL-06:**

1. Install the exact APK (EAS build `3884d669-850c-4b76-bba5-5e57ffcd2245`) on a
   physical Android device; record device model, Android version, build number.
2. Insert an SD card (UPL-05) or connect a USB-OTG drive (UPL-06) containing one
   short 4K/30 clip.
3. Open SportReel, go to the source/upload screen, and select the clip from the
   external source.
4. Capture: a screen recording of the whole flow; the granted permission dialogs;
   the file as the app lists it (name + size); and the upload result state.
5. Mid-upload, physically remove the SD card / unplug the USB drive, and capture
   what the app does.

**Evidence needed back.** The screen recording, the screenshots, the device
identity, and the resulting R2 object key + size if an upload completed.
