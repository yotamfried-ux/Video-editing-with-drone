package expo.modules.sportreelsourcereader

import org.json.JSONObject
import java.io.IOException
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL

private const val API_TIMEOUT_MS = 30_000
private const val PART_TIMEOUT_MS = 120_000
private const val STREAM_CHUNK = 256 * 1024

/**
 * HttpURLConnection implementation of the existing operator multipart contract. The operator
 * secret is read from the keychain-backed vault per request; nothing else is persisted and no
 * R2 or Supabase service credential exists on the device.
 */
class HttpUploadApi(private val baseUrl: String, private val secretProvider: () -> String?) : UploadApi {
  private fun post(path: String, body: JSONObject): JSONObject {
    val secret = secretProvider()?.takeIf { it.isNotBlank() }
      ?: throw UploadApiException(401, "operator_secret_missing: open SportReel to restore operator access", false)
    val conn = try {
      (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
        requestMethod = "POST"; connectTimeout = API_TIMEOUT_MS; readTimeout = API_TIMEOUT_MS; doOutput = true
        setRequestProperty("Content-Type", "application/json"); setRequestProperty("x-operator-secret", secret)
      }
    } catch (e: IOException) { throw UploadApiException(null, e.message ?: "connection_failed", true, e) }
    try {
      conn.outputStream.use { it.write(body.toString().toByteArray()) }
      val code = conn.responseCode
      val text = (if (code in 200..299) conn.inputStream else conn.errorStream)?.use { it.readBytes().toString(Charsets.UTF_8) } ?: ""
      if (code !in 200..299) {
        val message = try { JSONObject(text).optString("error").ifBlank { text.take(300) } } catch (_: Exception) { text.take(300) }
        throw UploadApiException(code, message.ifBlank { "HTTP $code" }, UploadApiException.isRetryableStatus(code))
      }
      return if (text.isBlank()) JSONObject() else JSONObject(text)
    } catch (e: UploadApiException) { throw e
    } catch (e: IOException) { throw UploadApiException(null, e.message ?: "network_error", true, e)
    } finally { conn.disconnect() }
  }

  override fun start(job: BackgroundUploadJob): StartResult {
    val r = post("/api/operator/upload/multipart/start", JSONObject()
      .put("client_upload_id", job.localId).put("filename", job.sourceFilename).put("mimeType", job.mimeType)
      .put("size", job.sourceSizeBytes).put("batch_id", job.batchId).put("local_cleanup_required", true))
    return StartResult(r.getString("upload_id"), r.getString("batch_id"), r.getString("storage_key"),
      r.getLong("part_size_bytes"), r.getInt("expected_part_count"), r.getLong("source_size_bytes"))
  }

  override fun status(job: BackgroundUploadJob): ServerStatus {
    val r = post("/api/operator/upload/multipart/status", JSONObject().put("upload_id", job.uploadId))
    val arr = r.optJSONArray("completed_parts")
    val parts = (0 until (arr?.length() ?: 0)).map {
      val p = arr!!.getJSONObject(it)
      BackgroundUploadPart(p.getInt("part_number"), p.getString("etag"), p.getLong("size_bytes"))
    }
    return ServerStatus(r.getString("upload_id"), r.getString("batch_id"), r.getString("storage_key"), r.getLong("source_size_bytes"),
      r.getString("status"), r.getLong("part_size_bytes"), r.getInt("expected_part_count"), parts, r.optString("local_cleanup_status", ""))
  }

  override fun partUrl(uploadId: String, partNumber: Int): PartTarget {
    val r = post("/api/operator/upload/multipart/part-url", JSONObject().put("upload_id", uploadId).put("part_number", partNumber))
    return PartTarget(r.getString("upload_url"), r.getLong("size_bytes"))
  }

  override fun recordPart(uploadId: String, part: BackgroundUploadPart) {
    post("/api/operator/upload/multipart/record-part", JSONObject().put("upload_id", uploadId)
      .put("part_number", part.partNumber).put("etag", part.etag).put("size_bytes", part.sizeBytes))
  }

  override fun complete(uploadId: String): CompleteResult {
    val r = post("/api/operator/upload/multipart/complete", JSONObject().put("upload_id", uploadId))
    return CompleteResult(r.optString("upload_status"), r.optLong("verified_size_bytes", -1))
  }

  override fun cleanup(uploadId: String, artifactCount: Int, reclaimedBytes: Long, sourcePreserved: Boolean) {
    post("/api/operator/upload/multipart/cleanup", JSONObject().put("upload_id", uploadId).put("cleanup_status", "confirmed")
      .put("artifact_count", artifactCount).put("reclaimed_bytes", reclaimedBytes).put("source_preserved", sourcePreserved))
  }
}

/** Streams one part from the source straight to the signed URL in bounded chunks (no part-sized heap buffer). */
class HttpPartTransport : PartTransport {
  override fun put(url: String, source: SourceReader, sourceUri: String, offset: Long, length: Int): String {
    val conn = try {
      (URL(url).openConnection() as HttpURLConnection).apply {
        requestMethod = "PUT"; doOutput = true; connectTimeout = API_TIMEOUT_MS; readTimeout = PART_TIMEOUT_MS
        setFixedLengthStreamingMode(length.toLong()); setRequestProperty("Content-Type", "application/octet-stream")
      }
    } catch (e: IOException) { throw UploadApiException(null, e.message ?: "connection_failed", true, e) }
    try {
      conn.outputStream.use { out -> copyRange(source, sourceUri, offset, length, out) }
      val code = conn.responseCode
      if (code !in 200..299) throw UploadApiException(code, "R2 part upload failed with status $code", UploadApiException.isRetryableStatus(code))
      return conn.getHeaderField("ETag")?.trim()?.takeIf { it.isNotEmpty() }
        ?: throw UploadApiException(code, "R2 part response did not expose the exact ETag", true)
    } catch (e: UploadApiException) { throw e
    } catch (e: SecurityException) { throw e
    } catch (e: IOException) {
      if (e.message?.startsWith("source_") == true) throw e
      throw UploadApiException(null, e.message ?: "network_error", true, e)
    } finally { conn.disconnect() }
  }

  private fun copyRange(source: SourceReader, uri: String, offset: Long, length: Int, out: OutputStream) {
    var done = 0
    while (done < length) {
      val n = minOf(STREAM_CHUNK, length - done)
      out.write(source.readRange(uri, offset + done, n))
      done += n
    }
  }
}
