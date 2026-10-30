# SportReel Annotation Studio

Local, single-operator, desktop-first tool for building **permanent human-verified Ground Truth**
for the SportReel pipeline and for evaluating real pipeline output against it.

Spec: [`docs/specs/ground-truth-annotation-studio.md`](../docs/specs/ground-truth-annotation-studio.md) ·
M0 analysis: [`docs/annotation-studio/M0-gap-analysis.md`](../docs/annotation-studio/M0-gap-analysis.md) ·
Milestone report: [`docs/annotation-studio/STATUS.md`](../docs/annotation-studio/STATUS.md)

## Run it

Requires Node >= 22.13 and `ffmpeg`/`ffprobe`. **No npm install** — zero dependencies.

```bash
cd annotation-studio
npm run seed            # builds ./.demo-home from SYNTHETIC footage only (no real data)
STUDIO_HOME=.demo-home STUDIO_TOKEN=demo-token npm start
# open http://127.0.0.1:4173/?t=demo-token
```

For real use, omit the seed and point it at operational folders to catalog:

```bash
STUDIO_HOME=~/.sportreel-studio \
STUDIO_RECONCILE_ROOTS="/data/raw:raw/,/data/processed:processed/" \
npm start      # prints a one-time launch URL containing a random token
```

`review/ approved/ previews/ pending_payment/` prefixes are refused as sources (they are generated outputs).

## Tests

```bash
npm run check      # syntax check of every file
npm test           # 48+ node:test unit/integration/security tests (needs ffmpeg)
npm run test:e2e   # Playwright browser scenarios + screenshots (needs `playwright` + chromium)
```

## Layout

| Path | Purpose |
|---|---|
| `server/db.mjs` | SQLite schema; append-only/protected tables enforced with triggers |
| `server/archive.mjs` | Write-once, content-addressed, hash-verified source archive (adapter seam for R2) |
| `server/ingest.mjs` | Hash → dedup → archive → derivatives; reconcile; archive integrity audit |
| `server/annotations.mjs` | Drafts (optimistic concurrency), approval, immutable revisions, athletes |
| `server/datasets.mjs` | Dataset freeze, deterministic group-aware splits, JSONL export, blind manifest |
| `server/evaluate.mjs` | Deterministic blind evaluator |
| `server/edl.mjs` | `edl/v1` validation, source→output transforms, editing metrics, crop proposals |
| `server/app.mjs` | Localhost-only authenticated JSON API + range-capable media streaming |
| `web/` | Precision Studio UI (RTL Hebrew chrome, LTR timecodes), vanilla ES modules |

## Isolation guarantees (tested)

* Separate state directory, database file, token, and archive. No production secrets are read.
* No production code, workflow, or script references this folder (`tests/api.test.mjs`).
* Every `/api` and `/media` route returns 401 without the token; Host and Origin are checked.
* `annotation_revisions`, datasets, predictions, evaluations, EDL records and the audit log are
  append-only at the database level; source identity (`id`, `sha256`, `byte_size`) cannot be updated.
* The blind manifest handed to a pipeline contains only `sha256`, `byte_size`, `display_name`.

## Not production integration

The archive is a **local filesystem** implementation and the DB is **SQLite**. Real R2 (separate bucket
and credentials) and a separate Supabase project are *adapter work awaiting operator approval* — see
STATUS.md. Nothing here has touched production storage, credentials, or the pipeline.
