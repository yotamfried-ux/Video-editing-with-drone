# SportReel — Drone → AI Editing → Athlete Highlights

> Turn raw drone footage into per-athlete highlight reels, automatically.

**SportReel** ingests raw drone video from Google Drive and runs a multi-stage AI
pipeline: native-video analysis with Gemini, **cross-clip identity clustering** so
each athlete's moments are grouped together, FFmpeg reel compilation, an advisory
**QA gate** (with automatic re-edit), and publishing to the **REVIEW queue** for
operator approval before delivery. Approved reels are published to the athlete
marketplace (Supabase + Cloudflare Stream) and surfaced in the mobile app's
Discover feed; face matching notifies athletes the system recognizes.

### Pipeline flow (actual)

```
Google Drive RAW
   ↓  download
Gemini native-video analysis  (per-person events + scores, chunked for long video)
   ↓
Identity clustering           (CLIP embeddings + two-signal Gemini verification)
   ↓
FFmpeg reel compiler          (one reel per athlete, music, transitions, watermark)
   ↓
QA gate (advisory)            (technical + engagement; auto re-edit on critical defects)
   ↓
Drive REVIEW folder           → operator approves in the mobile app
   ↓
deliver.py (Phase 2a)         → 480p preview + email + publish to Discover (Supabase/Stream)
   ↓
payment → deliver_final.py    (Phase 2b) → full-quality delivery
```

Components: **pipeline/** (Python, this repo's core), **mobile/** (Expo operator +
athlete app), **web-api/** (Next.js on Vercel — payments, sessions, operator auth),
**Supabase** (DB/auth/storage), **Sentry** (error monitoring), **LangSmith**
(optional tracing).

---

## Supported Sports

- 🏄 **Surfing** — wave catches, aerials, tube rides
- 🏈 **Football** — goals, key plays, standout moments

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python --version` |
| FFmpeg | `sudo apt install ffmpeg` / `brew install ffmpeg` |
| Google Cloud Project | With Drive API + Gmail API enabled |
| Gemini API Key | [Google AI Studio](https://aistudio.google.com/) — free tier |
| Google Service Account | With Drive API access + domain-wide delegation for Gmail |

---

## Step-by-Step Setup

### 1. Clone & install Python dependencies

```bash
git clone <repo-url>
cd dtor-pipeline
pip install -r requirements.txt
```

### 2. Install FFmpeg (if not already installed)

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 3. Google Cloud setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the following APIs:
   - **Google Drive API**
   - **Gmail API**
   - **Generative Language API** (for Gemini)
4. Create a **Service Account**:
   - IAM & Admin → Service Accounts → Create
   - Grant it **Editor** role
   - Create a JSON key and download it as `service_account.json`
5. For Gmail sending, enable **domain-wide delegation** on the service account and grant the `https://www.googleapis.com/auth/gmail.send` scope in Google Workspace admin

### 4. Set up Google Drive folders

Create these folders in Google Drive:
- **RAW** — drop new drone footage here
- **REVIEW** — draft reels are uploaded here for operator approval
- **PROCESSED** — original videos are moved here after processing
- **APPROVED** / **PREVIEW** / **PENDING_PAYMENT** — delivery-stage folders (Phase 2)

Share each folder with the service account email (found in `service_account.json` → `client_email`).

Copy each folder's ID from the URL: `drive.google.com/drive/folders/FOLDER_ID_HERE`

### 5. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your values
```

Fill in all values in `.env` — see `.env.example` for the full list.

### 6. Add your logo

Replace `assets/logo.png` with your actual branded logo.
Recommended: PNG with transparency, ~300px wide.

---

## Running the Pipeline

```bash
python run.py
```

`run.py` runs preflight checks (ffmpeg, Gemini key, Drive, disk), then Phase 1:
1. Scan the RAW Drive folder for new videos and download them to `TMP_DIR`
2. Analyze with Gemini (native video) → per-person highlight events + scores
3. Cluster appearances across clips into per-athlete identities (CLIP + Gemini)
4. Compile one highlight reel per athlete (FFmpeg: music, transitions, watermark)
5. Run the advisory QA gate; auto re-edit reels with critical defects
6. Upload drafts to the **REVIEW** folder and move originals to **PROCESSED**
7. Record draft→source mapping + run status in Supabase (mobile app progress bar)

Operators then approve drafts in the app; `deliver.py` handles preview + Discover
publishing, and `deliver_final.py` handles post-payment delivery.

Logs are written to `logs/pipeline.log`; errors flow to Sentry (when `SENTRY_DSN`
is set), tagged with a per-run `pipeline_run_id`.

---

## Folder Structure

```
Video-editing-with-drone/
├── README.md
├── requirements.txt          # runtime deps    (requirements-dev.txt adds pytest)
├── .env.example
├── config/                   # settings.py loads all config from env (timeouts,
│                             #   proxy quality, CLIP thresholds, folder IDs, …)
├── run.py                    # Phase 1 entry: preflight → orchestrator.main()
├── deliver.py / deliver_final.py   # Phase 2a / 2b delivery entry points
├── pipeline/
│   ├── orchestrator.py       # Phase 1 orchestration, QA re-edit loop, uploads
│   ├── preflight.py          # startup health checks
│   ├── run_context.py        # per-run pipeline_run_id correlation
│   ├── clustering.py         # pure merge-gate + frame-selection helpers
│   ├── text_utils.py         # normalize_description (identity merge key)
│   └── stages/
│       ├── analyzer.py       # Gemini native-video analysis + multi-frame thumbs
│       ├── identity.py       # CLIP + Gemini cross-clip identity clustering
│       ├── editor.py         # FFmpeg reel compiler + clip QA
│       ├── qa_gate.py        # reel QA gate decision + reporting
│       └── feedback.py       # approval/feedback feedback loop
├── integrations/
│   ├── drive.py  gemini.py  ffmpeg.py  notifier.py
│   ├── retry.py              # shared transient-error backoff
│   ├── observability.py      # Sentry init + scope/breadcrumb/capture helpers
│   ├── supabase_uploader.py  # reels/drafts/status + Discover publishing
│   ├── cloudflare_stream.py  face_matcher.py
├── eval/                     # identity-clustering eval harness + fixtures + baseline
├── tests/                    # pytest unit/eval tests
├── mobile/                   # Expo operator + athlete app
├── web-api/                  # Next.js (Vercel): payments, sessions, operator auth
└── supabase/                 # SQL migrations + schema
```

---

## Setting Up the Apps Script Trigger

The Apps Script in `apps_script/trigger.gs` runs every hour in Google Drive and notifies the pipeline owner when new videos are detected.

1. Go to [script.google.com](https://script.google.com)
2. Create a new project
3. Paste the contents of `apps_script/trigger.gs`
4. Set the constants at the top: `RAW_FOLDER_ID` and `OWNER_EMAIL`
5. Run `setupHourlyTrigger()` once manually to register the time-based trigger
6. Authorize the script when prompted

> **Note:** The Apps Script is a lightweight notifier/scheduler only. The actual heavy processing runs via `python run.py` on your machine or server. For fully automated end-to-end runs, schedule `run.py` with cron:

```bash
# Run every hour at :05
5 * * * * /usr/bin/python3 /path/to/dtor-pipeline/run.py >> /path/to/logs/cron.log 2>&1
```

---

## Environment Variables Reference

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Gemini API key from Google AI Studio |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to service account JSON key file |
| `RAW_FOLDER_ID` | Drive folder ID for incoming raw footage |
| `REVIEW_FOLDER_ID` | Drive folder ID for draft reels awaiting approval |
| `PROCESSED_FOLDER_ID` | Drive folder ID for archiving originals |
| `APPROVED_FOLDER_ID` / `PREVIEW_FOLDER_ID` / `PENDING_PAYMENT_FOLDER_ID` | Phase-2 delivery folders |
| `OWNER_EMAIL` / `NOTIFY_EMAIL` | Operator summary + fallback client email |
| `LOGO_PATH` | Path to the watermark PNG (default: `assets/logo.png`) |
| `TMP_DIR` | Local temp directory for downloads (default: `/tmp/dtor`) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | SportReel DB/storage (status + Discover) |
| `SENTRY_DSN` | Optional error monitoring |
| `PROXY_CRF` / `PROXY_MAX_WIDTH` / `CLIP_MERGE_THRESHOLD` / `CLIP_HIGH_CONF` / `IDENTITY_FRAMES` | Quality/identity tuning (sensible defaults) |

---

## License

MIT — built for drone operators and sports content creators.
