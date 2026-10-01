package expo.modules.sportreelsourcereader

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.ForegroundInfo

/** Foreground upload notification whose text and progress come only from durable job state. */
object UploadNotification {
  const val CHANNEL_ID = "sportreel_uploads"
  const val NOTIFICATION_ID = 4101
  const val RESULT_NOTIFICATION_ID = 4102

  private fun ensureChannel(context: Context) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val nm = context.getSystemService(NotificationManager::class.java)
    if (nm.getNotificationChannel(CHANNEL_ID) == null) {
      nm.createNotificationChannel(NotificationChannel(CHANNEL_ID, "Video uploads", NotificationManager.IMPORTANCE_LOW).apply {
        description = "Shows progress while SportReel uploads your footage in the background"
        setShowBadge(false)
      })
    }
  }

  private fun builder(context: Context): NotificationCompat.Builder {
    ensureChannel(context)
    val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
    val pending = launch?.let {
      PendingIntent.getActivity(context, 0, it, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }
    return NotificationCompat.Builder(context, CHANNEL_ID)
      .setSmallIcon(context.applicationInfo.icon.takeIf { it != 0 } ?: android.R.drawable.stat_sys_upload)
      .setContentIntent(pending)
  }

  fun progress(context: Context, s: UploadProgressSummary): Notification =
    builder(context).setContentTitle(s.title).setContentText("${s.percent}% — keeps uploading if you leave the app")
      .setProgress(100, s.percent, false).setOngoing(true).setOnlyAlertOnce(true)
      .setCategory(NotificationCompat.CATEGORY_PROGRESS).setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE).build()

  fun foregroundInfo(context: Context, s: UploadProgressSummary): ForegroundInfo =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
      ForegroundInfo(NOTIFICATION_ID, progress(context, s), ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
    else ForegroundInfo(NOTIFICATION_ID, progress(context, s))

  fun update(context: Context, s: UploadProgressSummary) {
    try { context.getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, progress(context, s)) } catch (_: SecurityException) {}
  }

  /** Terminal state: replace the ongoing notification with a dismissible result. */
  fun showResult(context: Context, s: UploadProgressSummary) {
    val text = when {
      s.failed > 0 -> "${s.failed} upload${if (s.failed == 1) "" else "s"} need attention — open SportReel to retry"
      else -> "${s.verified} video${if (s.verified == 1) "" else "s"} uploaded and verified"
    }
    val n = builder(context).setContentTitle(if (s.failed > 0) "SportReel — Upload needs attention" else "SportReel — Upload complete")
      .setContentText(text).setAutoCancel(true).setOngoing(false).build()
    try { context.getSystemService(NotificationManager::class.java).notify(RESULT_NOTIFICATION_ID, n) } catch (_: SecurityException) {}
  }
}
