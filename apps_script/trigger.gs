/**
 * trigger.gs — D to R Pipeline: Google Apps Script hourly watcher.
 * Scans RAW_FOLDER_ID for new video files and notifies the owner.
 *
 * Setup:
 *  1. Replace RAW_FOLDER_ID and OWNER_EMAIL below.
 *  2. Run setupHourlyTrigger() once manually to register the time trigger.
 *  3. Authorize the script when prompted.
 */

// ── Configuration ──────────────────────────────────────────────────────────
var RAW_FOLDER_ID = "YOUR_RAW_FOLDER_ID_HERE";
var OWNER_EMAIL   = "YOUR_EMAIL_HERE";

// ── Trigger registration ───────────────────────────────────────────────────

/**
 * Run this function ONCE manually to set up the recurring hourly trigger.
 */
function setupHourlyTrigger() {
  // Remove any existing triggers to avoid duplicates
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "checkForNewVideos") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }

  ScriptApp.newTrigger("checkForNewVideos")
    .timeBased()
    .everyHours(1)
    .create();

  Logger.log("✅ Hourly trigger registered for checkForNewVideos()");
}

// ── Main watcher function ──────────────────────────────────────────────────

/**
 * Runs every hour. Checks for new video files in the RAW folder.
 * Sends an email notification to OWNER_EMAIL if new videos are found.
 * Stores processed file IDs in PropertiesService to avoid re-notifying.
 */
function checkForNewVideos() {
  var props = PropertiesService.getScriptProperties();
  var knownIdsRaw = props.getProperty("processedIds");
  var knownIds = knownIdsRaw ? JSON.parse(knownIdsRaw) : [];

  try {
    var folder = DriveApp.getFolderById(RAW_FOLDER_ID);
    var files  = folder.getFiles();
    var newFiles = [];

    while (files.hasNext()) {
      var file = files.next();
      var mime = file.getMimeType();

      // Only consider video files
      if (mime.indexOf("video/") !== 0) continue;

      if (knownIds.indexOf(file.getId()) === -1) {
        newFiles.push({
          id:      file.getId(),
          name:    file.getName(),
          created: file.getDateCreated().toISOString(),
          url:     file.getUrl()
        });
      }
    }

    if (newFiles.length === 0) {
      Logger.log("📁 No new videos found.");
      return;
    }

    Logger.log("🎬 Found " + newFiles.length + " new video(s). Sending notification...");
    _sendNotification(newFiles);

    // Record new IDs so we don't re-notify
    for (var j = 0; j < newFiles.length; j++) {
      knownIds.push(newFiles[j].id);
    }
    props.setProperty("processedIds", JSON.stringify(knownIds));

  } catch (e) {
    Logger.log("❌ Error in checkForNewVideos: " + e.message);
    MailApp.sendEmail(
      OWNER_EMAIL,
      "⚠️ D to R Script Error",
      "An error occurred in the Apps Script trigger:\n\n" + e.message
    );
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────

function _sendNotification(newFiles) {
  var subject = "🎬 D to R — " + newFiles.length + " new video(s) ready to process";

  var bodyLines = [
    "New drone footage has been detected in your RAW folder.",
    "",
    "Files:"
  ];

  for (var i = 0; i < newFiles.length; i++) {
    var f = newFiles[i];
    bodyLines.push("  • " + f.name + " — " + f.url);
  }

  bodyLines.push("");
  bodyLines.push("Run your pipeline to process them:");
  bodyLines.push("  python run.py");
  bodyLines.push("");
  bodyLines.push("— D to R Automation");

  MailApp.sendEmail(OWNER_EMAIL, subject, bodyLines.join("\n"));
  Logger.log("✅ Notification sent to " + OWNER_EMAIL);
}

/**
 * Utility: clear stored processed IDs (run manually to reset state).
 */
function clearProcessedIds() {
  PropertiesService.getScriptProperties().deleteProperty("processedIds");
  Logger.log("✅ processedIds cleared.");
}
