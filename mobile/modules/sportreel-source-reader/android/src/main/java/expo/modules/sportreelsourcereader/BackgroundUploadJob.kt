package expo.modules.sportreelsourcereader

import org.json.JSONArray
import org.json.JSONObject

enum class BackgroundUploadStatus { QUEUED, UPLOADING, RETRY_WAIT, COMPLETING, VERIFIED, FAILED }

data class BackgroundUploadPart(val partNumber: Int, val etag: String, val sizeBytes: Long) {
  fun toJson() = JSONObject().put("partNumber", partNumber).put("etag", etag).put("sizeBytes", sizeBytes)
  companion object { fun fromJson(o: JSONObject) = BackgroundUploadPart(o.getInt("partNumber"), o.getString("etag"), o.getLong("sizeBytes")) }
}

data class BackgroundUploadJob(
  val localId: String, val batchId: String, val sourceUri: String, val sourceFilename: String,
  val mimeType: String, val sourceSizeBytes: Long, val apiBaseUrl: String,
  val uploadId: String? = null, val storageKey: String? = null, val partSizeBytes: Long? = null,
  val expectedPartCount: Int? = null, val completedParts: List<BackgroundUploadPart> = emptyList(),
  val status: BackgroundUploadStatus = BackgroundUploadStatus.QUEUED, val attempt: Int = 0,
  val lastError: String? = null, val createdAt: String, val updatedAt: String
) {
  fun toJson(): String = JSONObject().apply {
    put("localId", localId); put("batchId", batchId); put("sourceUri", sourceUri); put("sourceFilename", sourceFilename)
    put("mimeType", mimeType); put("sourceSizeBytes", sourceSizeBytes); put("apiBaseUrl", apiBaseUrl)
    put("uploadId", uploadId); put("storageKey", storageKey); put("partSizeBytes", partSizeBytes); put("expectedPartCount", expectedPartCount)
    put("completedParts", JSONArray().also { a -> completedParts.forEach { a.put(it.toJson()) } })
    put("status", status.name); put("attempt", attempt); put("lastError", lastError); put("createdAt", createdAt); put("updatedAt", updatedAt)
  }.toString()

  companion object {
    fun newQueued(localId: String, batchId: String, sourceUri: String, sourceFilename: String, mimeType: String, sourceSizeBytes: Long, apiBaseUrl: String): BackgroundUploadJob {
      val now = java.time.Instant.now().toString()
      return BackgroundUploadJob(localId, batchId, sourceUri, sourceFilename, mimeType, sourceSizeBytes, apiBaseUrl, createdAt = now, updatedAt = now)
    }
    fun fromJson(raw: String): BackgroundUploadJob {
      val o = JSONObject(raw); val parts = o.optJSONArray("completedParts") ?: JSONArray()
      return BackgroundUploadJob(
        o.getString("localId"), o.getString("batchId"), o.getString("sourceUri"), o.getString("sourceFilename"), o.getString("mimeType"),
        o.getLong("sourceSizeBytes"), o.getString("apiBaseUrl"), o.optString("uploadId").takeIf { it.isNotBlank() && it != "null" },
        o.optString("storageKey").takeIf { it.isNotBlank() && it != "null" }, if (o.isNull("partSizeBytes")) null else o.getLong("partSizeBytes"),
        if (o.isNull("expectedPartCount")) null else o.getInt("expectedPartCount"),
        (0 until parts.length()).map { BackgroundUploadPart.fromJson(parts.getJSONObject(it)) }, BackgroundUploadStatus.valueOf(o.getString("status")),
        o.optInt("attempt", 0), o.optString("lastError").takeIf { it.isNotBlank() && it != "null" }, o.getString("createdAt"), o.getString("updatedAt")
      )
    }
    fun fromJsonOrNull(raw: String): BackgroundUploadJob? = try { fromJson(raw) } catch (_: Exception) { null }
  }
}

/** Stable logical upload identity: the same batch + source + size always maps to the same job and server client_upload_id. */
object BackgroundUploadIdentity {
  fun localId(batchId: String, sourceUri: String, sourceSizeBytes: Long): String {
    val digest = java.security.MessageDigest.getInstance("SHA-256")
      .digest("$batchId\n$sourceUri\n$sourceSizeBytes".toByteArray())
    return "bg_" + digest.joinToString("") { "%02x".format(it) }.take(40)
  }
}

/** Bridge shape consumed by React Native; status is the lowercase durable state name. */
fun BackgroundUploadJob.toBridgeMap(): Map<String, Any?> {
  val expected = expectedPartCount
  val progress = when {
    status == BackgroundUploadStatus.VERIFIED -> 1.0
    expected != null && expected > 0 -> minOf(1.0, completedParts.size.toDouble() / expected)
    else -> 0.0
  }
  return mapOf(
    "localId" to localId, "batchId" to batchId, "sourceUri" to sourceUri, "filename" to sourceFilename,
    "status" to status.name.lowercase(), "attempt" to attempt, "lastError" to lastError,
    "uploadId" to uploadId, "storageKey" to storageKey, "sourceSizeBytes" to sourceSizeBytes,
    "completedPartCount" to completedParts.size, "expectedPartCount" to expectedPartCount,
    "progress" to progress, "updatedAt" to updatedAt
  )
}
