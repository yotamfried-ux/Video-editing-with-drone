# Ground Truth — environment variables

All Studio variables are prefixed `STUDIO_`. **Never reuse the production names** (`R2_*`, `SUPABASE_*`, `OPERATOR_SECRET`,
`GOOGLE_SERVICE_ACCOUNT_JSON`); a test fails the build if Studio code reads them. None of these belong in GitHub Actions secrets of the
pipeline workflows, in `NEXT_PUBLIC_*`, in browser bundles, or in logs.

## Studio server (`annotation-studio/`)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `STUDIO_HOME` | no | `~/.sportreel-annotation-studio` | local state: token, cache, outputs, SQLite file (when no DB URL) |
| `STUDIO_PORT` | no | `4173` | bound to `127.0.0.1` only |
| `STUDIO_TOKEN` | no | random, stored `0600` in `STUDIO_HOME/token` | UI/API access token (launch URL `/?t=…`) |
| `STUDIO_RECONCILE_ROOTS` | no | – | `dir:prefix,…` operational folders to catalog (`review/ approved/ previews/ pending_payment/` are refused) |
| `STUDIO_DB_URL` | for Postgres | – (SQLite) | connection string for role **`gt_studio`** (search_path set by the role) |
| `STUDIO_R2_ACCOUNT_ID` or `STUDIO_R2_ENDPOINT` | for R2 | – | protected archive endpoint |
| `STUDIO_R2_BUCKET` | for R2 | – | **a dedicated bucket, not the pipeline bucket** |
| `STUDIO_R2_ACCESS_KEY_ID` / `STUDIO_R2_SECRET_ACCESS_KEY` | for R2 | – | token scoped to that bucket only |
| `STUDIO_R2_PREFIX` | no | `sources/` | object key prefix |

Wiring the R2 archive into the server (`server/main.mjs`) selects the backend from these variables (`r2ConfigFromEnv`).

## Operator-run tools

| Variable | Used by | Purpose |
|---|---|---|
| `STUDIO_ADMIN_DB_URL` | `npm run migrate` | **admin** connection used only to apply `db/migrations` and `db/roles.sql`; never held by the running app |
| `STUDIO_TEST_DB_URL` | tests | superuser URL of a **disposable** Postgres; tests create/drop their own schemas/databases |
| `GT_SKIP_QUALIFICATION=1` | tests | skip the pipeline-render qualification test |

## Pipeline (observational exporters; unrelated to Studio code)

| Variable | Default | Purpose |
|---|---|---|
| `SPORTREEL_EXPORT_EDL` | unset = **off** | `1` enables EDL recording and the `predictions/v1` step in the diagnostics wrapper |
| `PIPELINE_RUN_ID`, `GITHUB_SHA` / `SPORTREEL_COMMIT` | – | recorded in every export; the importer rejects exports without them |

## Credential separation matrix

| Principal | Archive bucket | GT database | Production DB / bucket |
|---|---|---|---|
| Pipeline / web-api (existing) | **none** | **none** (`REVOKE` + tests) | existing |
| `gt_studio` + archive **write** token | read/write | working tables, INSERT-only history, no DELETE | none |
| Playback/evaluator | archive **read-only** token (recommended) | `gt_evaluator`: frozen views + own results | none |
