# D to R — Drone Content Pipeline

> Turn raw drone footage into branded sport highlight clips, automatically.

**D to R** (Drone to Reel) is an automated pipeline that ingests raw drone video from Google Drive, uses Gemini AI to detect highlight moments, cuts and watermarks clips with FFmpeg, and delivers them to the client via Gmail — hands-free.

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

Create three folders in Google Drive:
- **RAW** — drop new drone footage here
- **CLIPS** — processed highlight clips will be uploaded here
- **PROCESSED** — original videos are moved here after processing

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

The pipeline will:
1. Scan the RAW Drive folder for new videos
2. Download each unprocessed video to `TMP_DIR`
3. Send it to Gemini for sport detection + highlight timestamp extraction
4. Cut each highlight clip and overlay your watermark logo
5. Upload the finished clips to the CLIPS folder
6. Move the original to PROCESSED
7. Email the client a summary with all clip links

Logs are written to `logs/pipeline.log`.

---

## Folder Structure

```
dtor-pipeline/
├── README.md               # This file
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── .env                    # Your secrets (never commit this)
├── .gitignore
├── config.py               # Loads all config from .env
├── pipeline/
│   ├── __init__.py
│   ├── drive.py            # Google Drive: download, upload, track processed
│   ├── analyzer.py         # Gemini AI: detect sport + highlight timestamps
│   ├── editor.py           # FFmpeg: cut clips + overlay watermark
│   └── notifier.py         # Gmail: send summary email to client
├── apps_script/
│   └── trigger.gs          # Google Apps Script hourly Drive watcher
├── assets/
│   └── logo.png            # Your brand watermark (replace this)
├── logs/
│   └── .gitkeep
└── run.py                  # Main entry point
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
| `CLIPS_FOLDER_ID` | Drive folder ID for processed output clips |
| `PROCESSED_FOLDER_ID` | Drive folder ID for archiving originals |
| `NOTIFY_EMAIL` | Client email for the summary delivery |
| `LOGO_PATH` | Path to the watermark PNG (default: `assets/logo.png`) |
| `TMP_DIR` | Local temp directory for downloads (default: `/tmp/dtor`) |

---

## License

MIT — built for drone operators and sports content creators.
