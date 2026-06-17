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
6. Applied all 3 Supabase migrations via MCP — verified 15/15 ✅.
7. Fixed 6 mobile app bugs (branch `claude/engineering-os-setup-w42yk1`):
   - `Colors.error` → `Colors.danger` in pipeline.tsx
   - Tab active detection: exact segment comparison in OperatorNav
   - `usePipelineStatus`: added `loading` + `error` state (was silently null on failure)
   - Operator secret missing: Alert with "Go to Settings" navigation in pipeline/review/reels
   - Review screen: `ActivityIndicator` while loading (was blank)
   - Reels screen: added `loaded`/`loadError` state + spinner + error card

## What still needs to be done
### Storage bucket
Create bucket `athlete-photos` (Private) at:
`https://supabase.com/dashboard/project/bcndgmymnismbxvdeetc/storage/buckets`

### GitHub Actions secrets still needed
`SUPABASE_URL` and `SUPABASE_SERVICE_KEY` must be added to:
`https://github.com/yotamfried-ux/Video-editing-with-drone/settings/secrets/actions`

Without these, pipeline status updates (progress bar in operator app) will silently fail.

`CLAUDE_API_KEY` must be added for the security-review CI check to pass (currently ❌ failing).

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
## Engineering OS — governance layer (read-only reference)

This project is governed by **Engineering OS**, a read-only reference at
`/root/.engineering-os` (see `.engineering-os/REFERENCE.md`).

**Before any task**, read and apply:
- `/root/.engineering-os/CLAUDE.md` — role, precedence, skill activation, end-of-task usage report
- `/root/.engineering-os/core/` — workflow, git cadence, quality gates, skill orchestration, documentation
- `/root/.engineering-os/patterns/` — reusable, security-reviewed code patterns
- `/root/.engineering-os/external-skills/` — external skill wrappers (SIP) + which are default-on

Apply these rules to THIS project's code. **Never modify anything under
`/root/.engineering-os`** — it is shared, read-only reference. Run
`/root/.engineering-os/scripts/skill-bootstrap.sh` to see which skills are present here.

### Manual install required — superpowers plugin

superpowers cannot be installed by a script. Inside Claude Code CLI, run:
```
/plugin install superpowers@claude-plugins-official
```
This is a one-time step per machine. Verify with `/plugin list`.

### Cross-project learning loop

When you encounter a bug, lesson, failed solution, or validated pattern in THIS project
that is relevant beyond it, follow the two-step protocol:

1. **Document locally first** — create `lessons-learned/` or `failed-solutions/` in
   this repo using the schema in `/root/.engineering-os/core/learning-loop.md`.
2. **Promote to Engineering OS when confidence ≥ Medium** (root cause proven, not just
   "it stopped happening") — open a PR to `https://github.com/yotamfried-ux/Engineering-OS` adding the lesson to
   `lessons-learned/` or `patterns/`. This is how Engineering OS accumulates
   cross-project wisdom. Read `/root/.engineering-os/core/learning-loop.md › <learning_loop>`
   for the full promotion protocol (Observation → Verified Lesson → Best Practice).

Never write directly to `/root/.engineering-os` — all contributions go via PR.
<!-- END engineering-os (managed) -->
