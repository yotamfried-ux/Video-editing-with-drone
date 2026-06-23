# SportReel — Claude Code Context

## Project overview
Drone video pipeline → AI editing → athlete highlights marketplace.

- **Pipeline**: GitHub Actions (`pipeline-run.yml`) — triggered by `repository_dispatch: new-raw-video`. Downloads footage from Google Drive, analyzes with Gemini, edits with ffmpeg, uploads drafts back to Drive.
- **Operator app**: React Native (Expo) in `mobile/` — operator reviews drafts, triggers pipeline, manages pricing.
- **Web API**: Next.js in `web-api/` — deployed to Vercel. Handles payments, webhooks, sessions, operator auth.
- **Supabase**: project `bcndgmymnismbxvdeetc` — DB + auth + storage.

## Active branch
`claude/drone-pipeline-bootstrap-Yf0Hs` — open PR against `main`.

## What was done this session
1. Fixed `GITHUB_DISPATCH_TOKEN` env var in Vercel (was empty → 503 → 403 → fixed with Contents:write PAT).
2. Fixed `GITHUB_REPO` env var in Vercel.
3. Confirmed pipeline runs end-to-end when triggered from the operator app.
4. Created Supabase migrations for all missing tables.
5. Allowed Supabase MCP tools in `.claude/settings.json`.

## What still needs to be done
### Supabase migrations — NOT YET APPLIED to the live DB
Run these in order at `https://supabase.com/dashboard/project/bcndgmymnismbxvdeetc/sql/new`:
1. `supabase/migrations/20260611_add_drafts_and_reprocess_requests.sql`
2. `supabase/migrations/20260612_add_pipeline_status.sql`
3. `supabase/migrations/20260612_create_core_schema.sql`

Then verify with `supabase/verify_schema.sql` — every row must return `true`.

### Storage bucket
Create bucket `athlete-photos` (Private) at:
`https://supabase.com/dashboard/project/bcndgmymnismbxvdeetc/storage/buckets`

### GitHub Actions secrets still needed
`SUPABASE_URL` and `SUPABASE_SERVICE_KEY` must be added to:
`https://github.com/yotamfried-ux/Video-editing-with-drone/settings/secrets/actions`

Without these, pipeline status updates (progress bar in operator app) will silently fail.

## Key env vars
| Where | Var | Value / note |
|-------|-----|-------------|
| Vercel | `GITHUB_DISPATCH_TOKEN` | Fine-grained PAT, Contents:write on this repo |
| Vercel | `GITHUB_REPO` | `yotamfried-ux/Video-editing-with-drone` |
| GitHub Secrets | `SUPABASE_URL` | `https://bcndgmymnismbxvdeetc.supabase.co` |
| GitHub Secrets | `SUPABASE_SERVICE_KEY` | service_role key from Supabase dashboard |

## Architecture notes
- `pipeline/orchestrator.py` → `_write_status()` upserts `pipeline_status` table (id=1). Silent on failure.
- Mobile app polls `pipeline_status` every 5s via `usePipelineStatus` hook.
- `match_athlete_face` RPC: cosine similarity over JSONB face embeddings (128-float arrays from `face_recognition`).
- Auth trigger: `on_auth_user_created` → inserts row in `athlete_profiles` on every new signup.

<!-- BEGIN engineering-os (managed) -->
## Engineering OS — governance layer

This repository uses **Engineering OS** as a read-only engineering governance and knowledge layer.

Reference source:
- Local reference path: `${ENGINEERING_OS_HOME:-$HOME/.engineering-os}`
- Source repo: `https://github.com/yotamfried-ux/Engineering-OS`

Before code changes, apply the Engineering OS workflow:
1. Read this project context and the Engineering OS reference instructions.
2. Use the relevant skill/workflow for the task type.
3. Prefer existing patterns and documented lessons before inventing new structure.
4. Validate with tests or explicit checks before pushing.
5. Use PRs for changes; do not merge to `main` without explicit owner approval.
6. When CodeRabbit reviews a PR, address actionable comments before merge.

Do not commit generated Graph/analysis artifacts or local machine paths as part of governance setup. Keep this project-specific PR surface small and auditable.
<!-- END engineering-os (managed) -->
