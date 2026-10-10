# SportReel pipeline qualification — focused scope

Tracking: [#267](https://github.com/yotamfried-ux/Video-editing-with-drone/issues/267).
Engineering-OS policies: [testing fast path](https://github.com/yotamfried-ux/Engineering-OS/blob/main/patterns/testing/FAST-PATH.md), [project qualification](https://github.com/yotamfried-ux/Engineering-OS/blob/main/patterns/testing/project-qualification.md), [evidence and simulation](https://github.com/yotamfried-ux/Engineering-OS/blob/main/patterns/testing/evidence-and-simulation.md).

## What is connected now

One **fast PR workflow** runs existing targeted identity, athlete-coverage, QA-evidence, final publishability, and production QA simulations alongside new offline diagnostics positive and negative controls. It deliberately does **not** build Android, exercise payments, upload raw files, deploy to production, call Gemini, start a pipeline run, or provision GPUs.

When manually invoked with a **completed** Actions `diagnostics_run_id`, the workflow reads the existing GitHub artifact `pipeline-diagnostics-<id>` and checks **cross-artifact invariants**. It produces JSON/Markdown reports and fails on any unmet condition, while preserving those reports as artifacts. A failed historical run **should still fail** this audit; this is a feature, not test flakiness.

### Read-only local audit

```bash
python scripts/test_pipeline_qualification.py
python scripts/qualify_pipeline_diagnostics.py path/to/pipeline-diagnostics.zip \
  --run-id 38035345924 --out /tmp/qualification-report.json \
  --markdown /tmp/qualification-report.md
```

Run the actual PR fast suite via GitHub Actions or execute the eight listed `scripts/test_*.py` checks in the qualification workflow. The archived run [#38035345924](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/38035345924) is a **negative reference**, not a passing fixture.

## Gates and evidence levels

| Gate | Check | Evidence level |
|---|---|---|
| Perception inventory | Sidecar counts/schema errors | Offline structural; **not** real CV correctness |
| Candidate decision | Every entry selected/discarded; explain drops | Offline cross-artifact |
| Draft/REVIEW | Every draft has exactly one manifest part | Offline cross-artifact |
| QA | Every final part carries same-outcome PASS or FAIL; no silent PASS | Offline field validity; **not** proof that LLM was called |
| Athlete coverage | Complete coverage or supported no-output reason | Offline report; identity ground truth still needed |
| Subject and business gates | No blocking mixed-subject windows; business gate passed | Offline fail-closed validation |

**Critical distinction:** `offline_status=PASS` does not make `system_e2e_status=PASS`. The latter remains `NOT_TESTED` until actual MP4 quality and external boundaries have independent evidence. Avoid reporting a global success percentage from mismatched test layers.

## Next, without expanding scope

1. Reproduce and fix the **concrete observed failures** using the fast suite: source-evidence QA result not recorded, multiple drafts for one athlete overwritten/omitted from manifest, path alias mismatch, and selector-selected event disappearing without an explicit outcome. Add a failing regression **before** each product fix.
2. Build an isolated MP4 fixture path using ffmpeg/ffprobe and the real decoder/editor under controlled provider adapters. Assert source timestamp → athlete → draft lineage and media specs. No production sources.
3. Qualify the Engineering-OS [local video analyzer](https://github.com/yotamfried-ux/Engineering-OS/blob/main/capability-registry/video-analysis/mcp-video-analyzer.md) on the **target CI host** before treating it as available. Use Supervision/OpenCV overlays for track/subject verification. Attach timestamp/frame/burst evidence to visual defect claims, including before/after the same event.
4. Finally add **separately triggered** isolated R2/Supabase/provider tests with capped credentials/budget and cleanup. Only after those pass consider a real full 24-video rerun, requiring explicit approval. Keep Android/payment/security-release suites outside this pipeline-only qualification.

Safety invariants: no reset, no `full_clean`, no real production dispatch, no original R2 source deletion/rewrites, no mutation of the frozen October 3 batch. Every CI failure and missing tool must remain visible as `FAIL` or `BLOCKED`; no silent fallbacks to success.