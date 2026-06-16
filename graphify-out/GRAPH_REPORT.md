# Graph Report - .  (2026-06-16)

## Corpus Check
- 164 files · ~75,876 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 926 nodes · 2059 edges · 68 communities (55 shown, 13 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 25 edges (avg confidence: 0.84)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Web API Routes|Web API Routes]]
- [[_COMMUNITY_Pipeline Debug Utils|Pipeline Debug Utils]]
- [[_COMMUNITY_Mobile App Config|Mobile App Config]]
- [[_COMMUNITY_Mobile Dependencies|Mobile Dependencies]]
- [[_COMMUNITY_Project Governance & Assets|Project Governance & Assets]]
- [[_COMMUNITY_Pipeline Identity Tests|Pipeline Identity Tests]]
- [[_COMMUNITY_Pipeline Edit Tests|Pipeline Edit Tests]]
- [[_COMMUNITY_Scripts & Notes|Scripts & Notes]]
- [[_COMMUNITY_Gemini Integration|Gemini Integration]]
- [[_COMMUNITY_Supabase Uploader|Supabase Uploader]]
- [[_COMMUNITY_UI Components|UI Components]]
- [[_COMMUNITY_Pipeline AI Tests|Pipeline AI Tests]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 61|Community 61]]

## God Nodes (most connected - your core abstractions)
1. `ok()` - 60 edges
2. `fail()` - 60 edges
3. `section()` - 60 edges
4. `Colors` - 30 edges
5. `enforceRateLimit()` - 29 edges
6. `Spacing` - 26 edges
7. `Text()` - 24 edges
8. `requireOperator()` - 24 edges
9. `expo` - 18 edges
10. `SafeArea()` - 17 edges

## Surprising Connections (you probably didn't know these)
- `SportReel App Icon (cyan play button on dark background)` --references--> `Mobile Operator App (React Native / Expo)`  [INFERRED]
  mobile/assets/icon.png → CLAUDE.md
- `SportReel Splash Screen` --references--> `Mobile Operator App (React Native / Expo)`  [INFERRED]
  mobile/assets/splash.png → CLAUDE.md
- `D to R Drone Content Pipeline Overview` --references--> `Brand Watermark Logo (blank/transparent)`  [EXTRACTED]
  README.md → assets/logo.png
- `test_cut_clip()` --calls--> `_get_duration()`  [INFERRED]
  debug.py → services/music.py
- `test_slowmo_duration_ratio()` --calls--> `_get_duration()`  [INFERRED]
  debug.py → services/music.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Automated Pipeline Trigger Chain: Drive Upload → Apps Script → repository_dispatch → GitHub Actions → run.py** — concept_google_drive_folders, concept_apps_script_watcher, concept_repository_dispatch, workflows_pipeline_run_workflow, concept_run_py [EXTRACTED 1.00]
- **SportReel Three-Tier Architecture: Mobile App + Web API + Pipeline** — concept_mobile_app, concept_web_api, concept_pipeline_orchestrator, concept_supabase_db [EXTRACTED 1.00]
- **SportReel Payment Layer: Stripe + Meshulam via Web API** — concept_web_api, concept_stripe_payment, concept_meshulam_payment [EXTRACTED 1.00]
- **Mobile App Build and Deploy CI/CD Workflows** — workflows_android_gradle_check_workflow, workflows_eas_build_workflow, workflows_eas_update_workflow, concept_eas_build_system, concept_mobile_app [EXTRACTED 1.00]
- **Engineering OS Governance Documents in this Project** — engineering_os_reference_reference, commands_security_review_security_review_command, commands_use_engineering_os_use_engineering_os_command, claude_md_project_context, engineering_os_governance_layer [EXTRACTED 1.00]

## Communities (68 total, 13 thin omitted)

### Community 0 - "Web API Routes"
Cohesion: 0.07
Nodes (44): GET(), POST(), POST(), GET(), GET(), ALLOWED, POST(), PATCH() (+36 more)

### Community 1 - "Pipeline Debug Utils"
Cohesion: 0.13
Nodes (48): fail(), _ffmpeg_guard(), _make_test_video(), ok(), יוצר סרטון בדיקה דינמי (testsrc2) עם FFmpeg — ללא קבצים חיצוניים., Return True if FFmpeg is available; print a skip message and return False if not, section(), test_analyzer_parsing() (+40 more)

### Community 2 - "Mobile App Config"
Cohesion: 0.05
Nodes (43): backgroundColor, foregroundImage, adaptiveIcon, googleServicesFile, package, permissions, versionCode, projectId (+35 more)

### Community 3 - "Mobile Dependencies"
Cohesion: 0.05
Nodes (38): dependencies, base64-arraybuffer, esutils, expo, expo-asset, expo-build-properties, expo-constants, expo-device (+30 more)

### Community 4 - "Project Governance & Assets"
Cohesion: 0.11
Nodes (37): Brand Watermark Logo (blank/transparent), SportReel Project Context (CLAUDE.md), Use Engineering OS Claude Command, Google Apps Script Drive Watcher (trigger.gs), Cloudflare Stream (DRM Video Streaming), Cross-Project Learning Loop Protocol, deliver.py — Phase 2a Delivery Script, Expo Application Services (EAS) Build System (+29 more)

### Community 5 - "Pipeline Identity Tests"
Cohesion: 0.09
Nodes (33): test_cluster_empty_fallback(), test_e2e_two_athletes(), test_identity_clustering(), test_resource_optimizations(), _extract_thumbnail(), Extract a JPEG frame from video at timestamp using FFmpeg. Returns path or None., _build_clusters_from_data(), _cleanup_thumbnails() (+25 more)

### Community 6 - "Pipeline Edit Tests"
Cohesion: 0.09
Nodes (30): test_color_and_crop(), test_cut_clip(), test_music_overlay(), test_music_smart_selection(), test_qa_agent(), test_quality_drive_flag(), test_quality_reason_codes(), test_quality_targeted_fix_and_basic_mode() (+22 more)

### Community 7 - "Scripts & Notes"
Cohesion: 0.11
Nodes (27): _list_notes(), main(), scripts/add_note.py — Add operator editing notes to a specific draft reel.  Note, clear_operator_note(), _decay_weight(), get_all_label_injections(), get_operator_notes(), get_qa_calibration_hint() (+19 more)

### Community 8 - "Gemini Integration"
Cohesion: 0.12
Nodes (13): _CompatFile, delete_video(), _GenaiCompat, _get_client(), _Model, Client, integrations/gemini.py — Gemini Files API wrapper (google-genai SDK v2). Provide, Delete a Gemini Files API file after use to free storage. (+5 more)

### Community 9 - "Supabase Uploader"
Cohesion: 0.12
Nodes (23): close_queued_reprocess(), Mark all 'queued' requests as done — called after a successful run that     cons, Upsert pipeline_status table (id=1). Called from orchestrator to show progress i, write_pipeline_status(), _apply_qa_fixes(), _check_disk_space(), _classify_input(), _group_appearances() (+15 more)

### Community 10 - "UI Components"
Cohesion: 0.13
Nodes (14): Badge(), BadgeType, formatCountdown(), Props, styles, Card(), Props, styles (+6 more)

### Community 11 - "Pipeline AI Tests"
Cohesion: 0.14
Nodes (22): test_editor_improvements(), test_music_analysis(), test_prompt_to_edit_gaps(), add_music(), _adjust_clip(), _find_meta(), add_music.py — Beat-sync a song onto an existing no-music reel.  Usage:     pyth, Re-time a clip by speed_factor using FFmpeg setpts (video) + atempo (audio-less) (+14 more)

### Community 12 - "Community 12"
Cohesion: 0.17
Nodes (12): styles, Button(), Props, SafeArea(), styles, Spacer(), usePricing(), PricingScreen() (+4 more)

### Community 13 - "Community 13"
Cohesion: 0.16
Nodes (10): AnalyticsSummary, EventType, PricingRow, StreamData, apiFetch(), operatorFetch(), clearOperatorSecret(), getOperatorSecret() (+2 more)

### Community 14 - "Community 14"
Cohesion: 0.17
Nodes (19): _drive_retry(), get_new_videos(), _get_upload_service(), _load_processed_ids(), mark_as_processed(), move_to_pending_payment(), integrations/drive.py — Google Drive integration. סורק תיקיית RAW, מוריד סרטונים, Query PROCESSED_FOLDER_ID and return the set of file IDs found there.     Drive (+11 more)

### Community 15 - "Community 15"
Cohesion: 0.10
Nodes (19): dependencies, next, resend, stripe, @supabase/supabase-js, @upstash/ratelimit, @upstash/redis, devDependencies (+11 more)

### Community 16 - "Community 16"
Cohesion: 0.10
Nodes (19): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+11 more)

### Community 17 - "Community 17"
Cohesion: 0.18
Nodes (12): Index(), AuthState, useAuth(), PipelineStatus, Profile, useProfile(), supabase, NewSupportTicketScreen() (+4 more)

### Community 18 - "Community 18"
Cohesion: 0.18
Nodes (14): Props, ReelThumb(), SPORT_EMOJI, styles, Props, SessionCard(), styles, Spacing (+6 more)

### Community 19 - "Community 19"
Cohesion: 0.12
Nodes (19): test_compile_reel(), test_create_reel(), test_dual_reel_output(), test_e2e_simulation(), test_io_parallelism(), test_partition_no_over_split(), test_src_injection_routing(), test_zero_clip_warning() (+11 more)

### Community 20 - "Community 20"
Cohesion: 0.14
Nodes (13): RegisterScreen(), STEPS, styles, Props, styles, Variant, variantStyles, FaceUploadStep() (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.18
Nodes (10): CrashContextSync(), RootLayout(), syncPushToken(), useAuthStore, _context, CrashContext, installJsCrashReporter(), setCrashContext() (+2 more)

### Community 22 - "Community 22"
Cohesion: 0.16
Nodes (17): test_run_robustness(), _failed_ids_path(), flag_quality_issue(), _load_failed_ids(), Increment fail count for file_id. Returns True when limit is reached., Update the raw video's Drive description with a quality flag for operator visibi, Returns {file_id: fail_count}., record_failure() (+9 more)

### Community 23 - "Community 23"
Cohesion: 0.18
Nodes (14): deliver_final.py — D to R pipeline Phase 2b: Final Delivery entry point., get_pending_payment_drafts(), mark_draft_delivered(), Move a delivered reel from APPROVED to PROCESSED folder., Scan PENDING_PAYMENT_FOLDER_ID for reels awaiting payment. Returns [{id, name, w, find_client(), services/client_manager.py — Client lookup from clients.json. Matches a person d, Match a person description or draft filename against clients.json patterns. (+6 more)

### Community 24 - "Community 24"
Cohesion: 0.16
Nodes (16): Upload a local MP4 to Cloudflare Stream, return the stream UID., upload_to_stream(), fetch_pending_reprocess(), _get_drive_recording_date(), lookup_draft_sources(), mark_reprocess(), publish_reel(), publish_reel_approved() (+8 more)

### Community 25 - "Community 25"
Cohesion: 0.18
Nodes (11): CheckoutScreen(), styles, BitWebView(), Props, styles, MeshulamCheckout, StripeCheckout, useCheckout() (+3 more)

### Community 26 - "Community 26"
Cohesion: 0.17
Nodes (9): OperatorNav(), styles, TABS, OperatorUnlockState, useOperatorUnlock, OperatorLayout(), styles, Suggestion (+1 more)

### Community 27 - "Community 27"
Cohesion: 0.20
Nodes (9): Props, RevenueChart(), styles, Props, Text(), Variant, useOperatorAnalytics(), AnalyticsScreen() (+1 more)

### Community 28 - "Community 28"
Cohesion: 0.25
Nodes (12): init_sentry(), Initialize Sentry if SENTRY_DSN is configured. Safe to call multiple times., _get_service(), _get_user_service(), _list_folder(), main(), _move_file(), scripts/reset_and_rerun.py --------------------------- 1. Delete all MP4 files f (+4 more)

### Community 29 - "Community 29"
Cohesion: 0.20
Nodes (11): test_retry_logic(), test_video_chunking(), _chunk_video(), _gemini_call_session(), _merge_session_results(), pipeline/stages/analyzer.py — Gemini 2.5 Pro native video analysis. שולח את הסרט, Merge per-chunk analysis dicts: shift timestamps, pick dominant activity,     me, Retry fn() on transient Gemini errors (429 / quota / 503) with exponential back- (+3 more)

### Community 30 - "Community 30"
Cohesion: 0.27
Nodes (11): compute_pending_embeddings(), match_and_notify(), match_reel_and_notify(), Face recognition — compute embeddings for registered athletes and match against, For every athlete_profile with a photo but no face_embedding, compute and store, Send Expo push notification to athlete., Match each person from the pipeline against registered athletes; push-notify on, Match a pre-extracted video frame against registered athletes.      Called at Ph (+3 more)

### Community 31 - "Community 31"
Cohesion: 0.18
Nodes (11): get_reel_specs(), get_source_info(), integrations/ffmpeg.py — FFprobe/FFmpeg utility helpers. Provides reusable funct, Return dict with width, height, fps, zoom_headroom, can_slowmo for a video file., Technical specs for social-media compliance checks. Best-effort; never raises., _check_technical_compliance(), _persist_qa_result(), qa_check_reel() (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.22
Nodes (9): PipelineBar(), Props, styles, usePipelineStatus(), PipelineScreen(), ReprocessRow, STAGES, STATUS_LABEL (+1 more)

### Community 33 - "Community 33"
Cohesion: 0.24
Nodes (8): Props, ProtectedPlayer(), styles, POSITIONS, Props, styles, WatermarkOverlay(), useScreenCapture()

### Community 34 - "Community 34"
Cohesion: 0.22
Nodes (11): download_video(), get_approved_drafts(), _get_drive_service(), Download a Drive file to TMP_DIR.     Writes to filename.part first, then rename, Scan APPROVED_FOLDER_ID with pagination. Returns [{id, name, webViewLink}]., Service-account credentials — used for read-only operations (list, download)., deliver_preview(), _load_previewed() (+3 more)

### Community 35 - "Community 35"
Cohesion: 0.29
Nodes (10): test_narrative_order(), test_remaining_prompt_edit_gaps(), test_single_slowmo_rule(), _break_slowmo_runs(), _enforce_single_slowmo(), _ev_slowmo(), _narrative_order(), Reorder events to avoid consecutive slowmo=true clips (sluggish pacing).      Po (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.27
Nodes (10): Upload a draft reel to REVIEW_FOLDER_ID. Returns webViewLink., upload_draft(), Upsert the draft → raw-source mapping (drafts table). Enables operator     repro, record_draft(), _compile_clusters(), _process_long_video(), Persist draft → raw-source mapping in Supabase (CI runners are ephemeral;     th, _record_draft_sources() (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.22
Nodes (8): devDependencies, @babel/core, @types/react, typescript, expo, main, name, version

### Community 38 - "Community 38"
Cohesion: 0.29
Nodes (6): compilerOptions, paths, strict, extends, include, @/*

### Community 39 - "Community 39"
Cohesion: 0.40
Nodes (5): _get_gmail_service(), integrations/notifier.py — Gmail delivery via Google service account. שולח אימיי, Send an HTML summary email to all recipients.      The first recipient in the li, Build Gmail API service using service account with domain-wide delegation.     T, send_summary_email()

### Community 40 - "Community 40"
Cohesion: 0.33
Nodes (6): scripts, android, ios, postinstall, start, type-check

### Community 41 - "Community 41"
Cohesion: 0.47
Nodes (4): create_folder(), main(), setup_drive.py — One-time setup script. יוצר את שלוש תיקיות ה-Drive הנדרשות ומדפ, share_folder()

### Community 44 - "Community 44"
Cohesion: 0.50
Nodes (3): get_signed_stream_url(), Cloudflare Stream integration — upload videos and generate signed URLs., Return a signed Cloudflare Stream URL valid for ttl_seconds.

### Community 45 - "Community 45"
Cohesion: 0.67
Nodes (3): chunkKey(), clearChunks(), secureStorage

### Community 46 - "Community 46"
Cohesion: 1.00
Nodes (3): Security Review Claude Command, OWASP Top 10 Security Review Process, Claude Code Security Review CI Workflow

## Knowledge Gaps
- **213 isolated node(s):** `Client`, `Client`, `name`, `slug`, `version` (+208 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `qa_check_reel()` connect `Community 31` to `Pipeline Debug Utils`, `Scripts & Notes`, `Gemini Integration`, `Supabase Uploader`, `Community 29`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **Why does `main()` connect `Supabase Uploader` to `Community 36`, `Scripts & Notes`, `Community 14`, `Community 22`, `Community 24`, `Community 28`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **Why does `cluster_clips()` connect `Pipeline Identity Tests` to `Pipeline Debug Utils`, `Community 19`, `Supabase Uploader`, `Community 22`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **What connects `config — re-exports all settings for backward-compatible `import config` usage.`, `config/settings.py — Load all pipeline configuration from environment variables.`, `Return True if FFmpeg is available; print a skip message and return False if not` to the rest of the system?**
  _357 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Web API Routes` be split into smaller, more focused modules?**
  _Cohesion score 0.0683526999316473 - nodes in this community are weakly interconnected._
- **Should `Pipeline Debug Utils` be split into smaller, more focused modules?**
  _Cohesion score 0.12653061224489795 - nodes in this community are weakly interconnected._
- **Should `Mobile App Config` be split into smaller, more focused modules?**
  _Cohesion score 0.045454545454545456 - nodes in this community are weakly interconnected._