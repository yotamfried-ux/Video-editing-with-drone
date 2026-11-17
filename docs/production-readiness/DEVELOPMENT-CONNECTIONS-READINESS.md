# Development tools and connections readiness (Phase 0)

Date: 2026-11-17 · Base: PR #396 head `3ec5717` merged into branch `ccr-1f0e3de1-q1x8w1`.
No secret values, tokens or private URLs appear in this file. Status values only.

## 1. Connections file
**NOT FOUND.** Searched (names only, no contents read): home dirs, `/root`, `/mnt`, `/opt`, `/workspace`, recently added files outside the repos, and environment-variable *names*. The only credential-bearing names present are sandbox/proxy ones (GitHub token, proxy-injected cloud auth, an `AWS_*` pair used by the proxy for object storage tooling, one third-party model key name). None was used or printed. Nothing was copied. **Needed from the owner:** the path of the file, or confirmation that the connected MCP integrations below are the intended access.

## 2. Connection map (via connected MCP integrations)
| Service | Used by | Check performed (non-destructive) | Result | Mode | Missing / needs approval |
|---|---|---|---|---|---|
| GitHub | repo, PRs, Actions | PR #391/#396 read, workflow-run list, artifact list | PASS | read; push to own branch | Artifact **download** has no tool here (BLOCKED, see 3) |
| Supabase `sportreel` (ACTIVE_HEALTHY) | GT, Annotation Studio | `information_schema` listing, row counts of `ground_truth.*` | PASS | read-only SQL used | writes/migrations not used, need explicit approval |
| Cloudflare R2 bucket `sportreel` | raw/proxy/output media | bucket list | PARTIAL: bucket exists; **object GET/list not exposed** by the available tool | read | no object access from this host |
| Vercel | web-api | not checked (no task needs it) | NOT TESTED | - | - |
| Gemini | pipeline VLM | not called (cost policy) | NOT TESTED | - | key lives in CI secrets only |
| Docker | local | `docker --version` | present, not exercised | - | - |
| 1Password / secrets manager | - | none present | NOT APPLICABLE | - | - |

Live GT: `ground_truth` counts 24 sources, 14 athletes, 27 appearances, 1 frozen dataset; `action_occurrences`/`physical_actions`/`pipeline_predictions` are empty tables here, so rides/segments are read from the frozen dataset and `evaluation/ground_truth/gtv1_frozen.json` (cycle 6 verified its digest equals the live dataset). GT-v1 was not modified.

## 3. Blockers
1. **Real SportReel media not reachable from this host** (no R2 object access, artifact zip download unavailable). Consequence: `MEDIA_VERIFIED` and `HOLDOUT_VERIFIED` cannot be claimed. Existing CI artifact `visual-review-frames` (run 44058396657, 17 MB, unexpired until 2026-12-01) holds R2 stills; it needs a download path, or a read-only R2 credential granted by the owner.
2. Connections file missing (section 1).

## 4. Tool audit
| Tool | Purpose | Was installed | Installed now / source | Version | Qualification | Token/cost effect |
|---|---|---|---|---|---|---|
| ripgrep | focused code search | yes | - | 14.1.0 | used | high saving |
| fd | path search | no | `cargo install fd-find` | 10.5.2 | `fd --version` ok | saving |
| jq | JSON filtering of CI/QA results | yes | - | 1.7 | used | high saving |
| yq | YAML | yes | - | present (reports 0.0.0, a shim) | not exercised | - |
| ast-grep | AST/symbol search | no | `uv tool install ast-grep-cli` | 0.51.3 | `--version` only | saving vs full reads |
| repomix | repo map | no | not installed: `npm` registry reachable (v1.19.0 exists) but ripgrep+ast-grep cover the need; install only if a bounded map is needed (exclude `.env*`, media, artifacts) | - | NOT INSTALLED | avoided |
| Context7 | library docs | MCP connected | - | - | available, unused yet | saving |
| Exa | research | not connected | - | - | NOT AVAILABLE; WebSearch is the fallback | - |
| coverage | test coverage | no | `uv pip` in `/tmp/claude-0/venv-tools` | 7.17.3 | import ok | - |
| pytest/ruff/mypy/pyright/uv | Python quality | yes | - | 9.1.1/0.16.9/2.3.1/1.1.414/0.11.32 | present | - |
| ffmpeg/ffprobe | decode, probe | yes | - | 6.1.1 | used in test | local, free |
| mediainfo | container inspection | no | apt | 24.01 | `--Version` ok | - |
| OpenCV (headless) | frame analysis | no | `uv pip` (scratch venv) | 5.0.0 | used in vinspect | - |
| PyAV | exact PTS decode | no | `uv pip` (scratch venv) | 19.0.2 | used in vinspect | - |
| mcp-video-analyzer | metadata+frames MCP | not installed here | npm package exists (0.11.0), **not installed or tested in this session** | - | NOT TESTED | - |
| Project tools (Superpowers, RTK, Graphify, Maestro) | per `agent-tools.lock.env` | **missing** per `eos_capabilities.py status` | `scripts/bootstrap-agent-tools.sh` available, **not run** (heavy; Graphify graph and RTK not needed for the next steps) | - | READY=false | - |

The project's own `requirements.txt` lists opencv-free `ultralytics`, `supervision`, `boto3`, `supabase`; `cv2/boto3/moto/psycopg/ultralytics` are not installed in the system Python, which is why PR #396 reports identical local failures on `main`. Scratch venv was used instead of changing the project environment.

## 5. Video viewing capability — `tools/video_inspect/vinspect.py`
Subcommands: `probe`, `frames` (exact-time decode, manifest with pts + sha256), `sheet` (labelled contact sheet), `health` (black / frozen / PTS-jump scan on decoded frames), `compare` (source vs reel side by side).
Qualification on a **synthetic** 10 s / 25 fps clip with a known black window (4.0–4.2 s): fps/duration correct; requested 1.0/5.0/9.0 s decoded at exactly 1.0/5.0/9.0 s (2.5 s → 2.52 s, nearest 40 ms frame); `health` found black frames from 4.00 s; the contact sheet was viewed and shows black at 4.08 s. Test: `tools/video_inspect/test_vinspect.py` (1 passed).
Not covered: person/bounding-box localisation, tracking overlays, motion analysis over sequences, source-vs-reel EDL mapping (only a side-by-side frame helper), and anything on real media.

**Status: `VIDEO_ANALYSIS_TECHNICALLY_READY` (synthetic only). `VIDEO_ANALYSIS_READY` is NOT claimed** — no SportReel video has been opened.

## 6. Open items
- Provide connections file path or R2 read access / artifact download route.
- Decide whether to run `bootstrap-agent-tools.sh` (installs Graphify, RTK, Maestro, Superpowers).
- Next work (Phase 1+): rides/reel cardinality fixes identified in `CYCLE-06-*.md` (first loss stage is the event window for 16–17 of 24 rides in both baseline runs; no code change made yet in this session).
