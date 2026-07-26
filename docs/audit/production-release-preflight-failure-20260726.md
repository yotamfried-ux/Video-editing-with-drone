# Protected production release preflight failure — 2026-07-26

## Exact run identity

- Repository: `yotamfried-ux/Video-editing-with-drone`
- Protected release commit: `27e0b2625b5379ff35c00434102ba226d7246c6d`
- Workflow: `Upload Foundation Production Release`
- Workflow run: `30186532868`
- Failed job: `Verify release inputs and required configuration`
- Failed job ID: `89752197790`
- Control command: Issue #199 comment `5081832440`

The owner-only Issue command dispatcher successfully produced the exact release run ID and the release checked out the authorized `main` commit. The protected release then stopped in Preflight before Vercel verification, Supabase migrations, R2 probes, production API smoke, or EAS build.

## Evidence from the failed Preflight

Present without printing values:

- `R2_ACCOUNT_ID`
- `VERCEL_TOKEN`
- `EXPO_TOKEN`

Empty under the direct-only names used by the release workflow:

- `SUPABASE_DB_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `VERCEL_PROJECT_ID`
- `PRODUCTION_OPERATOR_SECRET`

`VERCEL_TEAM_ID` and `CLOUDFLARE_API_TOKEN` were empty but are not required for this native-Android release configuration. `browser_upload_origin` was intentionally empty.

The Preflight evidence upload also failed because `release-preflight.json` was created only after all configuration checks passed. No production mutation occurred: all downstream jobs were skipped.

## Root cause and minimal correction

The repository already has established configuration compatibility that the release workflow did not reuse:

- R2 access key: `R2_ACCESS_KEY_ID` or legacy `ACCESS_KEY_ID`
- R2 secret key: `R2_SECRET_ACCESS_KEY` or legacy `SECRET_KEY_ID`
- R2 bucket: `R2_BUCKET` or canonical default `sportreel`
- operator authentication: `PRODUCTION_OPERATOR_SECRET` or existing `OPERATOR_SECRET`
- Vercel project selector: `VERCEL_PROJECT_ID` or canonical project name `video-editing-with-drone`

The correction applies these mappings consistently in Preflight and every downstream consumer. Preflight now writes a sanitized success-or-failure artifact before returning a blocking error. It records canonical names, missing names, validation errors, and resolution contracts, never secret values.

## Remaining external blocker

`SUPABASE_DB_URL` remains an explicit, independent GitHub Actions secret. It cannot be derived safely from `SUPABASE_URL` or `SUPABASE_SERVICE_KEY`, because the PostgreSQL password/connection string is separate. No fallback, bypass, or fabricated value is introduced.

## Audit state

GAP-023 remains open. GAP-013, GAP-014, GAP-015, and GAP-016 remain open. The system is not yet approved for APK installation or a first SD-card upload until a protected release completes and retains Vercel, Supabase, R2, production API, EAS, and APK evidence.
