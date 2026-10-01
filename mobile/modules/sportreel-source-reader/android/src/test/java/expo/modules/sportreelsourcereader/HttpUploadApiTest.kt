package expo.modules.sportreelsourcereader

import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class HttpUploadApiTest {
  private lateinit var http: MiniHttpServer
  private val seen = mutableListOf<Triple<String, String?, String>>() // path, secret header, body
  private var respond: (String, String) -> Pair<Int, String> = { _, _ -> 200 to "{}" }
  private lateinit var api: HttpUploadApi
  private val job = BackgroundUploadJob.newQueued("job_aaaaaaaaaaaaaaaa", "batch-1", "content://v/1", "a b.mp4", "video/mp4", 12_000_000, "http://127.0.0.1:0")

  @Before fun up() {
    http = MiniHttpServer { req ->
      val body = req.body.toString(Charsets.UTF_8)
      seen.add(Triple(req.path, req.headers["x-operator-secret"], body))
      val (code, resp) = respond(req.path, body)
      MiniHttpServer.Response(code, resp)
    }
    api = HttpUploadApi("http://127.0.0.1:${http.port}", { "s3cret" })
  }
  @After fun down() { http.close() }

  @Test fun `start sends stable client_upload_id batch size and operator secret header`() {
    respond = { _, _ -> 200 to """{"ok":true,"upload_id":"u1","batch_id":"batch-1","storage_key":"raw/x.mp4","part_size_bytes":5000000,"expected_part_count":3,"source_size_bytes":12000000,"upload_status":"uploading"}""" }
    val r = api.start(job)
    assertEquals("u1", r.uploadId); assertEquals(3, r.expectedPartCount)
    val (path, secret, body) = seen.single()
    assertEquals("/api/operator/upload/multipart/start", path); assertEquals("s3cret", secret)
    val json = JSONObject(body)
    assertEquals("job_aaaaaaaaaaaaaaaa", json.getString("client_upload_id"))
    assertEquals("batch-1", json.getString("batch_id")); assertEquals(12_000_000L, json.getLong("size"))
    assertTrue(json.getBoolean("local_cleanup_required"))
  }

  @Test fun `status parses completed parts and cleanup status`() {
    respond = { _, _ -> 200 to """{"ok":true,"upload_id":"u1","batch_id":"batch-1","storage_key":"raw/x.mp4","source_size_bytes":12000000,"status":"uploading","part_size_bytes":5000000,"expected_part_count":3,"completed_parts":[{"part_number":1,"etag":"\"abc\"","size_bytes":5000000}],"local_cleanup_status":"pending"}""" }
    val s = api.status(job.copy(uploadId = "u1"))
    assertEquals(listOf(BackgroundUploadPart(1, "\"abc\"", 5_000_000)), s.parts)
    assertEquals("pending", s.cleanupStatus)
  }

  @Test fun `error statuses map to retryable or permanent exceptions`() {
    for ((code, retry) in listOf(401 to false, 403 to false, 409 to false, 408 to true, 429 to true, 500 to true, 503 to true)) {
      respond = { _, _ -> code to """{"error":"nope"}""" }
      val e = try { api.status(job.copy(uploadId = "u1")); null } catch (e: UploadApiException) { e }
      assertNotNull(e); assertEquals(code, e!!.status); assertEquals("status $code", retry, e.retryable)
    }
  }

  @Test fun `connection failure is retryable`() {
    val dead = HttpUploadApi("http://127.0.0.1:1", { "s" })
    val e = try { dead.status(job.copy(uploadId = "u1")); null } catch (e: UploadApiException) { e }
    assertNotNull(e); assertTrue(e!!.retryable); assertNull(e.status)
  }

  @Test fun `missing operator secret fails closed without a request`() {
    val noSecret = HttpUploadApi("http://127.0.0.1:${http.port}", { null })
    val e = try { noSecret.status(job.copy(uploadId = "u1")); null } catch (e: UploadApiException) { e }
    assertNotNull(e); assertFalse(e!!.retryable); assertTrue(seen.isEmpty())
  }

  @Test fun `record part complete and cleanup use the existing contract bodies`() {
    respond = { p, _ -> 200 to (if (p.endsWith("complete")) """{"ok":true,"upload_status":"verified","verified_size_bytes":12000000}""" else """{"ok":true}""") }
    api.recordPart("u1", BackgroundUploadPart(2, "\"e\"", 5_000_000))
    val c = api.complete("u1")
    api.cleanup("u1", 0, 0, true)
    assertEquals("verified", c.status); assertEquals(12_000_000L, c.verifiedSizeBytes)
    val rec = JSONObject(seen[0].third)
    assertEquals(2, rec.getInt("part_number")); assertEquals("\"e\"", rec.getString("etag")); assertEquals(5_000_000L, rec.getLong("size_bytes"))
    val cl = JSONObject(seen[2].third)
    assertEquals("confirmed", cl.getString("cleanup_status")); assertTrue(cl.getBoolean("source_preserved"))
  }

  @Test fun `part transport returns the exact etag header and classifies failures`() {
    var status = 200; var received = 0
    MiniHttpServer { req -> received = req.body.size; MiniHttpServer.Response(status, "", mapOf("ETag" to "\"deadbeef\"")) }.use { put ->
      val src = FakeSource(100)
      val t = HttpPartTransport()
      val url = "http://127.0.0.1:${put.port}/p"
      assertEquals("\"deadbeef\"", t.put(url, src, "content://x", 10, 50))
      assertEquals(50, received)
      status = 503
      val e = try { t.put(url, src, "content://x", 0, 10); null } catch (e: UploadApiException) { e }
      assertTrue(e!!.retryable)
      status = 403
      val e2 = try { t.put(url, src, "content://x", 0, 10); null } catch (e: UploadApiException) { e }
      assertFalse(e2!!.retryable)
    }
  }
}
