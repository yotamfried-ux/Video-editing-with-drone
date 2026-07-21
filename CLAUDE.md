# SportReel — Claude Code Context

## Project overview

Drone/sports footage → AI-assisted editing → personal athlete reels marketplace.

- **Pipeline**: GitHub Actions (`pipeline-run.yml`) dispatches the Python pipeline, mandatory Ultralytics/BoT-SORT perception, Gemini semantic analysis, FFmpeg 4K/30 editing, QA, and diagnostics.
- **Operator app**: React Native (Expo) in `mobile/` — upload, pipeline status, Review, re-edit, approval, and delivery controls.
- **Web API**: Next.js in `web-api/` — Vercel boundary for operator actions, uploads, Discover, checkout, webhooks, and protected media access.
- **Supabase**: DB/auth/tracking state. App-user face recognition is not part of the product.

## Product source of truth

Read before changing pipeline behavior:

1. `README.md` → **Product vision — source of truth**
2. `docs/audit/personal-publishable-reel-completion-plan-20260717.md`
3. `docs/audit/quality-first-4k-perception-and-face-removal-plan-20260721.md`
4. `docs/operator-pipeline-contract.md`

## Non-negotiable runtime rules

- Every eligible athlete receives one primary publishable reel or an explicit evidence-backed rejection.
- Other people may remain visible when the featured athlete stays identifiable, continuous, central, and owns the action.
- Surfing coverage includes every complete readable usable wave exactly once.
- Canonical output is silent, vertical 9:16, at most 90 seconds, and contains only complete actions.
- Production source is 4K/30. Canonical Parts must be 2160x3840 at 30 fps.
- Framing is `contain` by default. Crop/zoom is an exceptional CV-evidence-backed repair; Gemini hints, scores, event type, or another visible surfer cannot authorize it.
- Detector/tracker evidence is mandatory for every analyzed event. Never restore a Gemini-only production fallback.
- Do not add face-photo enrollment, face embeddings, biometric matching RPCs, or automatic account ownership based on a face in footage.
- Privileged mobile actions go through `operatorFetch` and the web-api boundary.
- Do not close footage-level gaps from CI alone. Require real-run artifacts and visual review.

## Required environment surfaces

- GitHub Actions: storage credentials, Gemini, Supabase service role, operator-run correlation, and optional perception overrides.
- Mandatory perception defaults are installed by `pipeline/required_perception_policy.py`; production may override the command/model only with another working detector/tracker producer.
- `SPORTREEL_REQUIRE_PERCEPTION` remains enabled in `.github/workflows/pipeline-run.yml`.

## Database state

- Apply tracked migrations in order.
- `supabase/migrations/20260721_remove_face_recognition.sql` removes historical biometric fields, RPCs, inferred reel ownership, and the `athlete-photos` bucket.
- The destructive migration requires explicit approval, backup awareness, application, and verification through `supabase/verify_schema.sql`.

## Working method

- Read current files, PRs, and Actions before making claims.
- Keep changes narrow and update the relevant audit.
- Add deterministic positive and negative regressions.
- Fix all CI/review findings before requesting merge.
- Do not merge without explicit user approval.
