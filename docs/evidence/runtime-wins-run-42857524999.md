# Where run 42857524999 still waited, and what changed

Run 42857524999 took 38 min in "Run pipeline" with every analysis cached. Timeline from the job log:

| Window | Duration | What happened |
|---|---|---|
| 16:50:13 → 16:53:46 | **3.5 min** | 29 sources (~7 GB) downloaded from R2 one after another, each hashed |
| 16:53:47 → 16:55:04 | 1.3 min | analysis (all cached) |
| 16:55:06 → 16:57:51 | **2.75 min** | identity clustering: 23 thumbnails uploaded one by one, the Gemini call, then 76 s of the same 23 thumbnails deleted one by one |
| 16:57:51 → 17:25 | ~27 min | 13 reels rendered (render_reels 1634 s) with QA alongside |

## Changes (none alters what is produced)

1. **Concurrent source downloads** (`source_upload_dedup._download_in_order`).
   - Up to `SPORTREEL_DOWNLOAD_WORKERS` (default 4) transfers at once.
   - Results are consumed in input order, so the exact-duplicate admission decisions stay sequential (the first
     copy of duplicate bytes remains canonical) and failures propagate exactly as before.
   - The run now logs `⏱️ download_sources took`.
   - Test: `scripts/test_parallel_source_download_contract.py`.
2. **One hash per source.** The dedup now uses the memoized `llm_cache.file_sha256`, which the perception sidecar
   key, the analysis cache key and the evidence cache also use. That removes one full read of each source.
3. **Concurrent Files API uploads and deletes in visual identity clustering.**
   - The thumbnails are uploaded in parallel but placed in the request in the original order, so Gemini receives the
     same request.
   - The deletes run in parallel too.
   - Test: `scripts/test_identity_files_api_concurrency_contract.py`.
4. **Persisted QA evidence copies.**
   - The single decode's 1280 px evidence copy is also kept in the LLM cache dir (saved between runs), keyed by the
     source's content hash and the evidence encoding settings. It is restored when a later run's perception comes
     from the sidecar cache.
   - Before, such a run had no evidence copy, so QA cut every evidence window from the 4K source while the next reel
     rendered.
   - Copies unused for 14 days are pruned before the cache is saved.
   - **Sources whose perception was cached before this change** never run the single decode. The first QA cut
     for such a source therefore encodes its copy from the whole source once (`ensure_evidence_copy`, same settings,
     PSNR-checked against the single-decode copy) and persists it. That costs about one 4K window cut, and every
     later window, reel and run cuts from the copy.
   - Test: `scripts/test_persisted_qa_evidence_contract.py`. The restored copy is byte-identical, and QA demonstrably
     cuts from it, not from the source. `test_single_decode_perception_contract.py` now modifies the source bytes
     (not only the mtime), because the persisted copy is content-addressed.

## Measured locally (4 vCPU, synthetic 4K60 HEVC ~100 Mb/s)

| | before | after |
|---|---|---|
| one 19 s QA evidence window | 28.2 s (cut from 4K) | 4.5 s (cut from the copy) |
| 17 s reel render with 2 QA windows cut alongside | 120.1 s | 87.0 s (83 s with nothing alongside) |
| visual-clustering Files API traffic (12 files, fake 0.05-0.2 s each) | 3.30 s | 0.65 s |

**Expected on a run like 42857524999:**
- Render + QA: ~27 → ~20 min. Production rendered at 6.7 s per reel-second against 4.9 s with an idle CPU.
- Clustering: ~2.75 → ~1.2 min.
- Downloads: they were limited by sequential transfers. The real gain depends on R2 throughput and is logged by the
  next run.
- Overall: roughly 8-10 min less on a cached run.

**Runs with new videos:** they keep the download and clustering gains. The evidence copy already existed there
(perception runs).
