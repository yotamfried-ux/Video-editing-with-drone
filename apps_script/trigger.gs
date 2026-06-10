/**
 * trigger.gs — D to R Pipeline: Google Apps Script RAW-folder watcher.
 *
 * Watches RAW_FOLDER_ID and, when new video(s) appear, fires a GitHub
 * `repository_dispatch` event that kicks off the "Run Pipeline" GitHub Actions
 * workflow (.github/workflows/pipeline-run.yml) within ~1 minute of upload.
 *
 * One-time setup:
 *  1. Fill in RAW_FOLDER_ID, GITHUB_OWNER, GITHUB_REPO below.
 *  2. Create a GitHub Personal Access Token with permission to trigger workflows:
 *       - Fine-grained token: repo access + "Contents: read & write" (dispatch
 *         needs the `repo` / contents scope). Classic token: `repo` scope.
 *  3. In the Apps Script editor: Project Settings → Script Properties →
 *     add a property  GITHUB_TOKEN = <your token>.  (Never hard-code it here.)
 *  4. Run setupTrigger() once to register the recurring time trigger and
 *     authorize the script when prompted.
 *
 * Optional: set NOTIFY_OWNER = true to also receive an email on each trigger.
 */

// ── Configuration ──────────────────────────────────────────────────────────
var RAW_FOLDER_ID = "YOUR_RAW_FOLDER_ID_HERE";
var GITHUB_OWNER  = "yotamfried-ux";
var GITHUB_REPO   = "video-editing-with-drone";
var EVENT_TYPE    = "new-raw-video";   // must match the workflow's repository_dispatch type
var OWNER_EMAIL   = "yotam.fried@gmail.com";
var NOTIFY_OWNER  = false;             // set true to also send yourself an email

// ── Trigger registration ───────────────────────────────────────────────────

/**
 * Run ONCE manually to register the recurring watcher.
 * Polls every minute — Drive has no native push to Apps Script, so 1 min is
 * the lowest latency available here (≈ "near-instant").
 */
function setupTrigger() {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "checkForNewVideos") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  ScriptApp.newTrigger("checkForNewVideos")
    .timeBased()
    .everyMinutes(1)
    .create();
  Logger.log("✅ Watcher registered — checkForNewVideos() runs every minute.");
}

// ── Main watcher ────────────────────────────────────────────────────────────

/**
 * Detects new videos in RAW and fires a GitHub repository_dispatch for each batch.
 * Processed IDs are remembered in Script Properties so we never re-trigger the
 * same file. (The pipeline itself also tracks processed IDs in Drive, so a
 * double-trigger is harmless — it just finds nothing new.)
 */
function checkForNewVideos() {
  var props = PropertiesService.getScriptProperties();
  var knownIds = JSON.parse(props.getProperty("processedIds") || "[]");

  try {
    var folder = DriveApp.getFolderById(RAW_FOLDER_ID);
    var files  = folder.getFiles();
    var newFiles = [];

    while (files.hasNext()) {
      var file = files.next();
      if (file.getMimeType().indexOf("video/") !== 0) continue;
      if (knownIds.indexOf(file.getId()) === -1) {
        newFiles.push({ id: file.getId(), name: file.getName(), url: file.getUrl() });
      }
    }

    if (newFiles.length === 0) {
      return;  // nothing new — stay quiet
    }

    Logger.log("🎬 " + newFiles.length + " new video(s) — dispatching to GitHub Actions...");
    _dispatchPipeline(newFiles);

    for (var j = 0; j < newFiles.length; j++) {
      knownIds.push(newFiles[j].id);
    }
    props.setProperty("processedIds", JSON.stringify(knownIds));

    if (NOTIFY_OWNER) {
      _notifyOwner(newFiles);
    }
  } catch (e) {
    Logger.log("❌ checkForNewVideos error: " + e.message);
    MailApp.sendEmail(OWNER_EMAIL, "⚠️ D to R watcher error", String(e.message));
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Fire the GitHub repository_dispatch that starts the pipeline workflow. */
function _dispatchPipeline(newFiles) {
  var token = PropertiesService.getScriptProperties().getProperty("GITHUB_TOKEN");
  if (!token) {
    throw new Error("GITHUB_TOKEN script property is not set — see setup step 3.");
  }
  var url = "https://api.github.com/repos/" + GITHUB_OWNER + "/" + GITHUB_REPO + "/dispatches";
  var payload = {
    event_type: EVENT_TYPE,
    client_payload: {
      count: newFiles.length,
      files: newFiles.map(function (f) { return { id: f.id, name: f.name }; })
    }
  };
  var resp = UrlFetchApp.fetch(url, {
    method: "post",
    contentType: "application/json",
    headers: {
      "Authorization": "Bearer " + token,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  var code = resp.getResponseCode();
  if (code === 204) {
    Logger.log("✅ Dispatched — GitHub Actions pipeline starting.");
  } else {
    throw new Error("GitHub dispatch failed (" + code + "): " + resp.getContentText());
  }
}

function _notifyOwner(newFiles) {
  var lines = ["New footage detected — pipeline triggered:", ""];
  for (var i = 0; i < newFiles.length; i++) {
    lines.push("  • " + newFiles[i].name + " — " + newFiles[i].url);
  }
  MailApp.sendEmail(OWNER_EMAIL,
    "🎬 D to R — pipeline triggered (" + newFiles.length + " video(s))",
    lines.join("\n"));
}

/** Utility: clear remembered IDs so already-seen files trigger again. */
function clearProcessedIds() {
  PropertiesService.getScriptProperties().deleteProperty("processedIds");
  Logger.log("✅ processedIds cleared.");
}
