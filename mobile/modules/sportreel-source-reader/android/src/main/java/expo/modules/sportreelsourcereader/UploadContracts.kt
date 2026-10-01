package expo.modules.sportreelsourcereader

/** Failure from the upload API / part transport. `status` is null for transport-level failures. */
class UploadApiException(val status: Int?, message: String, val retryable: Boolean, cause: Throwable? = null) :
  Exception(message, cause) {
  companion object {
    /** 408/429/5xx are transient; every other 4xx (auth, validation, conflict) fails closed. */
    fun isRetryableStatus(status: Int): Boolean = status == 408 || status == 429 || status >= 500
  }
}

data class StartResult(
  val uploadId: String, val batchId: String, val storageKey: String,
  val partSizeBytes: Long, val expectedPartCount: Int, val sourceSizeBytes: Long
)

data class ServerStatus(
  val uploadId: String, val batchId: String, val storageKey: String, val sourceSizeBytes: Long,
  val status: String, val partSizeBytes: Long, val expectedPartCount: Int,
  val parts: List<BackgroundUploadPart>, val cleanupStatus: String
)

data class PartTarget(val uploadUrl: String, val sizeBytes: Long)
data class CompleteResult(val status: String, val verifiedSizeBytes: Long)

/** Existing operator multipart upload API contract. No R2 credentials ever cross this boundary. */
interface UploadApi {
  fun start(job: BackgroundUploadJob): StartResult
  fun status(job: BackgroundUploadJob): ServerStatus
  fun partUrl(uploadId: String, partNumber: Int): PartTarget
  fun recordPart(uploadId: String, part: BackgroundUploadPart)
  fun complete(uploadId: String): CompleteResult
  fun cleanup(uploadId: String, artifactCount: Int, reclaimedBytes: Long, sourcePreserved: Boolean)
}

interface SourceReader {
  fun size(uri: String): Long
  fun readRange(uri: String, offset: Long, length: Int): ByteArray
}

/** PUTs one part to its signed URL and returns the exact ETag header. */
interface PartTransport {
  fun put(url: String, source: SourceReader, sourceUri: String, offset: Long, length: Int): String
}
