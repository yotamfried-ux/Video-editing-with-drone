package expo.modules.sportreelsourcereader

import android.content.Context
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

class BackgroundUploadStore(context: Context) {
  private val prefs = context.applicationContext.getSharedPreferences("sportreel_background_uploads", Context.MODE_PRIVATE)
  @Synchronized fun put(job: BackgroundUploadJob) { prefs.edit().putString(job.localId, job.toJson()).commit() }
  @Synchronized fun get(localId: String): BackgroundUploadJob? = prefs.getString(localId, null)?.let(BackgroundUploadJob::fromJsonOrNull)
  @Synchronized fun list(): List<BackgroundUploadJob> = prefs.all.values.mapNotNull { (it as? String)?.let(BackgroundUploadJob::fromJsonOrNull) }
}