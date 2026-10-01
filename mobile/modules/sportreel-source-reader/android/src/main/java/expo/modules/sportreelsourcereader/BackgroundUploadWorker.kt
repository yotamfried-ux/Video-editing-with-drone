package expo.modules.sportreelsourcereader

import android.content.Context
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

private const val TAG = "SportReelBgUpload"

class BackgroundUploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
  private val localId: String get() = inputData.getString(BackgroundUploadScheduler.KEY_LOCAL_ID).orEmpty()

  private fun summary(store: BackgroundUploadStore): UploadProgressSummary? {
    val job = store.get(localId) ?: return null
    return UploadProgressSummary.forBatch(store.list(), job.batchId)
  }

  override suspend fun getForegroundInfo(): ForegroundInfo {
    val s = summary(BackgroundUploadStores.get(applicationContext))
      ?: UploadProgressSummary("SportReel — Uploading videos", 0, 0, 0, 0)
    return UploadNotification.foregroundInfo(applicationContext, s)
  }

  override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
    val store = BackgroundUploadStores.get(applicationContext)
    val job = store.get(localId) ?: return@withContext Result.failure()
    try {
      setForeground(getForegroundInfo())
    } catch (e: Exception) {
      // Android 12+ can refuse a foreground start from the background. The durable job still runs and
      // WorkManager will resume it from the ledger if the system stops this execution.
      Log.w(TAG, "foreground promotion refused: ${e.javaClass.simpleName}")
    }

    val vault = OperatorSecretVault(applicationContext)
    val reader = ContentSourceReader(applicationContext)
    val engine = MultipartUploadEngine(
      store = store,
      api = HttpUploadApi(job.apiBaseUrl) { vault.get() },
      transport = HttpPartTransport(),
      source = reader,
      onProgress = { j -> summary(store)?.let { UploadNotification.update(applicationContext, it) }.also { Log.i(TAG, "progress ${j.localId} ${j.completedParts.size}/${j.expectedPartCount} ${j.status}") } },
      shouldContinue = { !isStopped }
    )
    val outcome = try { engine.run(localId) } finally { reader.close() }
    Log.i(TAG, "outcome $localId $outcome")

    summary(store)?.let { s ->
      val remaining = store.listByBatch(store.get(localId)!!.batchId).count {
        it.status != BackgroundUploadStatus.VERIFIED && it.status != BackgroundUploadStatus.FAILED
      }
      if (remaining == 0) UploadNotification.showResult(applicationContext, s)
    }
    when (outcome) {
      is EngineOutcome.Success -> Result.success()
      is EngineOutcome.Retry -> Result.retry()
      is EngineOutcome.Failed -> Result.failure()
    }
  }
}

object BackgroundUploadScheduler {
  const val KEY_LOCAL_ID = "local_id"
  const val TAG_WORK = "sportreel-background-upload"

  /** Unique per logical upload: duplicate enqueue / relaunch never starts a second transfer. */
  fun uniqueName(localId: String) = "sportreel-bg-upload-$localId"

  fun enqueue(context: Context, localId: String, replace: Boolean = false) {
    val request = OneTimeWorkRequestBuilder<BackgroundUploadWorker>()
      .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
      .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 10, TimeUnit.SECONDS)
      .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
      .setInputData(workDataOf(KEY_LOCAL_ID to localId))
      .addTag(TAG_WORK)
      .build()
    WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
      uniqueName(localId), if (replace) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP, request
    )
  }

  /** Called on every app start: re-schedules any durable job that is not terminal. KEEP makes this idempotent. */
  fun resumeEligible(context: Context, store: BackgroundUploadStore): List<String> =
    store.eligibleForResume().map { it.localId }.also { ids -> ids.forEach { enqueue(context, it) } }
}
