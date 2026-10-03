package expo.modules.sportreelsourcereader

/** Minimal durable key/value boundary so the store is testable without Android. */
interface KeyValueStorage {
  fun get(key: String): String?
  fun put(key: String, value: String)
  fun all(): Map<String, String>
  fun remove(key: String)
}

/**
 * Durable, serialized job store. Every mutation is a single synchronized
 * read-modify-write so a worker and the Expo module never interleave updates.
 * Corrupt records are isolated (skipped) rather than invented into state.
 */
class BackgroundUploadStore(private val storage: KeyValueStorage) {
  @Synchronized fun get(localId: String): BackgroundUploadJob? =
    storage.get(localId)?.let(BackgroundUploadJob::fromJsonOrNull)

  @Synchronized fun list(): List<BackgroundUploadJob> =
    storage.all().values.mapNotNull(BackgroundUploadJob::fromJsonOrNull).sortedBy { it.createdAt }

  @Synchronized fun put(job: BackgroundUploadJob) { storage.put(job.localId, job.toJson()) }

  /** Idempotent: a duplicate enqueue for the same logical upload returns the existing job untouched. */
  @Synchronized fun enqueue(job: BackgroundUploadJob): BackgroundUploadJob {
    val existing = get(job.localId)
    if (existing != null) return existing
    put(job)
    return job
  }

  /** Atomic transform; returns null when the job does not exist. */
  @Synchronized fun update(localId: String, transform: (BackgroundUploadJob) -> BackgroundUploadJob): BackgroundUploadJob? {
    val current = get(localId) ?: return null
    val next = transform(current).copy(updatedAt = java.time.Instant.now().toString())
    put(next)
    return next
  }

  /** Forget terminal verified records of a batch once the pipeline has consumed it. Never touches unfinished jobs. */
  @Synchronized fun removeVerifiedBatch(batchId: String): Int {
    val done = list().filter { it.batchId == batchId && it.status == BackgroundUploadStatus.VERIFIED }
    done.forEach { storage.remove(it.localId) }
    return done.size
  }

  fun listByBatch(batchId: String): List<BackgroundUploadJob> = list().filter { it.batchId == batchId }

  /** Jobs that must be (re)scheduled on app launch / reboot. FAILED is terminal until explicitly retried. */
  fun eligibleForResume(): List<BackgroundUploadJob> =
    list().filter { it.status != BackgroundUploadStatus.VERIFIED && it.status != BackgroundUploadStatus.FAILED }

  /** Explicit user retry of a failed job: keeps durable multipart identity, clears the terminal state. */
  fun requeueFailed(localId: String): BackgroundUploadJob? = update(localId) {
    if (it.status == BackgroundUploadStatus.FAILED) it.copy(status = BackgroundUploadStatus.QUEUED, attempt = 0, lastError = null) else it
  }
}
