package expo.modules.sportreelsourcereader

import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class MultipartUploadEngineTest {
  private val partSize = 5_000_000L
  private val size = 12_000_000L // 3 parts: 5M, 5M, 2M
  private lateinit var store: BackgroundUploadStore
  private lateinit var server: FakeServer
  private lateinit var source: FakeSource
  private lateinit var transport: FakeTransport
  private val progress = mutableListOf<BackgroundUploadJob>()
  private var stopped = false

  @Before fun setUp() {
    store = BackgroundUploadStore(InMemoryStorage())
    server = FakeServer(size, partSize)
    source = FakeSource(size)
    transport = FakeTransport(server, source)
    store.enqueue(BackgroundUploadJob.newQueued("job-1", "batch-1", "content://v/1", "a.mp4", "video/mp4", size, "https://api.invalid"))
  }

  private fun engine() = MultipartUploadEngine(store, FakeApi(server), transport, source,
    onProgress = { progress.add(it) }, shouldContinue = { !stopped })

  @Test fun `uploads every part once, completes, confirms cleanup and ends verified`() {
    val outcome = engine().run("job-1")
    assertEquals(EngineOutcome.Success, outcome)
    assertEquals(listOf(1, 2, 3), server.partPuts)
    assertEquals(1, server.completeCalls)
    assertEquals(1, server.cleanupCalls)
    assertEquals(BackgroundUploadStatus.VERIFIED, store.get("job-1")!!.status)
    assertEquals(setOf(1, 2, 3), store.get("job-1")!!.completedParts.map { it.partNumber }.toSet())
  }

  @Test fun `start uses the stable local id as the idempotent client upload id and persists server identity`() {
    engine().run("job-1")
    assertEquals(setOf("job-1"), server.clientIds)
    val job = store.get("job-1")!!
    assertEquals("upload-1", job.uploadId)
    assertEquals("raw/batch-1/a.mp4", job.storageKey)
    assertEquals(3, job.expectedPartCount)
  }

  @Test fun `server acknowledged parts are skipped and never resent`() {
    server.uploadId = "upload-1"
    server.recorded[1] = BackgroundUploadPart(1, "etag-1", partSize)
    server.recorded[2] = BackgroundUploadPart(2, "etag-2", partSize)
    store.update("job-1") { it.copy(uploadId = "upload-1", storageKey = server.storageKey, partSizeBytes = partSize, expectedPartCount = 3) }
    assertEquals(EngineOutcome.Success, engine().run("job-1"))
    assertEquals(listOf(3), server.partPuts)
    assertEquals(listOf(10_000_000L to 2_000_000), source.reads)
  }

  @Test fun `network failure mid-upload keeps acknowledged parts and a restart resumes without resending`() {
    transport.failNext = mutableListOf({ null }, { ioFailure() }) // part 1 ok, part 2 network error
    val first = engine().run("job-1")
    assertTrue(first is EngineOutcome.Retry)
    assertEquals(listOf(1), server.partPuts)
    val mid = store.get("job-1")!!
    assertEquals(BackgroundUploadStatus.RETRY_WAIT, mid.status)
    assertEquals(listOf(1), mid.completedParts.map { it.partNumber })
    assertEquals(1, server.startCalls)

    // A brand-new engine (process death / worker restart) over the same durable state.
    val second = MultipartUploadEngine(BackgroundUploadStore(storageOf(store)), FakeApi(server), transport, source, {}, { true })
    assertEquals(EngineOutcome.Success, second.run("job-1"))
    assertEquals(listOf(1, 2, 3), server.partPuts) // part 1 exactly once
    assertEquals(1, server.completeCalls)
    assertEquals(1, server.objectsCreated.size)
  }

  @Test fun `retry after start loses nothing and never creates a second server upload`() {
    server.failNextCalls = mutableListOf({ op -> if (op == "start") UploadApiException(503, "down", true) else null })
    assertTrue(engine().run("job-1") is EngineOutcome.Retry)
    assertNull(store.get("job-1")!!.uploadId)
    assertEquals(EngineOutcome.Success, engine().run("job-1"))
    assertEquals(setOf("job-1"), server.clientIds)
    assertEquals(1, server.objectsCreated.size)
  }

  @Test fun `retryable statuses return retry and permanent 4xx fail closed`() {
    for (status in listOf(408, 429, 500, 503)) {
      setUp()
      server.failNextCalls = mutableListOf({ UploadApiException(status, "x", UploadApiException.isRetryableStatus(status)) })
      assertTrue("status $status", engine().run("job-1") is EngineOutcome.Retry)
    }
    for (status in listOf(400, 401, 403, 404, 409)) {
      setUp()
      server.failNextCalls = mutableListOf({ UploadApiException(status, "x", UploadApiException.isRetryableStatus(status)) })
      val out = engine().run("job-1")
      assertTrue("status $status", out is EngineOutcome.Failed)
      assertEquals(BackgroundUploadStatus.FAILED, store.get("job-1")!!.status)
    }
  }

  @Test fun `completion only happens when every part is recorded`() {
    server.failNextCalls = mutableListOf() // none
    engine().run("job-1")
    assertEquals(3, server.recorded.size)
    assertEquals(1, server.completeCalls)
  }

  @Test fun `server verified status is idempotent success without re-upload`() {
    server.uploadId = "upload-1"; server.status = "verified"; server.cleanupStatus = "confirmed"
    (1..3).forEach { server.recorded[it] = BackgroundUploadPart(it, "e$it", if (it < 3) partSize else 2_000_000) }
    store.update("job-1") { it.copy(uploadId = "upload-1", storageKey = server.storageKey, partSizeBytes = partSize, expectedPartCount = 3) }
    assertEquals(EngineOutcome.Success, engine().run("job-1"))
    assertTrue(server.partPuts.isEmpty())
    assertEquals(0, server.completeCalls)
    assertEquals(0, server.cleanupCalls)
    assertEquals(BackgroundUploadStatus.VERIFIED, store.get("job-1")!!.status)
  }

  @Test fun `server verified but cleanup not confirmed re-sends only the cleanup evidence`() {
    server.uploadId = "upload-1"; server.status = "verified"; server.cleanupStatus = "pending"
    (1..3).forEach { server.recorded[it] = BackgroundUploadPart(it, "e$it", partSize) }
    store.update("job-1") { it.copy(uploadId = "upload-1", storageKey = server.storageKey, partSizeBytes = partSize, expectedPartCount = 3) }
    assertEquals(EngineOutcome.Success, engine().run("job-1"))
    assertTrue(server.partPuts.isEmpty())
    assertEquals(1, server.cleanupCalls)
  }

  @Test fun `source size change fails closed before any byte is sent`() {
    val changed = FakeSource(size + 1)
    val out = MultipartUploadEngine(store, FakeApi(server), transport, changed, {}, { true }).run("job-1")
    assertTrue(out is EngineOutcome.Failed)
    assertTrue(server.partPuts.isEmpty())
  }

  @Test fun `server state that disagrees with the job fails closed`() {
    store.update("job-1") { it.copy(uploadId = "upload-1", storageKey = "raw/other.mp4", partSizeBytes = partSize, expectedPartCount = 3) }
    server.uploadId = "upload-1"
    assertTrue(engine().run("job-1") is EngineOutcome.Failed)
    assertTrue(server.partPuts.isEmpty())
  }

  @Test fun `aborted server upload fails closed`() {
    server.uploadId = "upload-1"; server.status = "aborted"
    store.update("job-1") { it.copy(uploadId = "upload-1", storageKey = server.storageKey, partSizeBytes = partSize, expectedPartCount = 3) }
    assertTrue(engine().run("job-1") is EngineOutcome.Failed)
  }

  @Test fun `part size mismatch from server fails closed`() {
    val api = object : UploadApi by FakeApi(server) {
      override fun partUrl(uploadId: String, partNumber: Int) = PartTarget("https://r2.invalid/u/$partNumber", 1)
    }
    val out = MultipartUploadEngine(store, api, transport, source, {}, { true }).run("job-1")
    assertTrue(out is EngineOutcome.Failed)
    assertTrue(server.partPuts.isEmpty())
  }

  @Test fun `stop request between parts returns retry without losing progress or burning an attempt`() {
    val api = FakeApi(server)
    val e = MultipartUploadEngine(store, api, transport, source, { if (it.completedParts.size == 1) stopped = true }, { !stopped })
    val out = e.run("job-1")
    assertTrue(out is EngineOutcome.Retry)
    assertEquals(listOf(1), store.get("job-1")!!.completedParts.map { it.partNumber })
    assertEquals(1, server.partPuts.size)
  }

  @Test fun `attempt budget exhaustion becomes a durable failure`() {
    store.update("job-1") { it.copy(attempt = MultipartUploadEngine.MAX_ATTEMPTS) }
    assertTrue(engine().run("job-1") is EngineOutcome.Failed)
    assertEquals(BackgroundUploadStatus.FAILED, store.get("job-1")!!.status)
  }

  @Test fun `progress callback reflects durable completed parts after every acknowledged part`() {
    engine().run("job-1")
    val counts = progress.map { it.completedParts.size }
    assertTrue(counts.containsAll(listOf(1, 2, 3)))
  }

  @Test fun `missing or already verified job is a no-op`() {
    assertTrue(engine().run("nope") is EngineOutcome.Failed)
    engine().run("job-1")
    val puts = server.partPuts.size
    assertEquals(EngineOutcome.Success, engine().run("job-1"))
    assertEquals(puts, server.partPuts.size)
  }

  @Test fun `emits one put and one ack event per uploaded part and none for acknowledged parts`() {
    server.uploadId = "upload-1"
    server.recorded[1] = BackgroundUploadPart(1, "etag-1", partSize)
    store.update("job-1") { it.copy(uploadId = "upload-1", storageKey = server.storageKey, partSizeBytes = partSize, expectedPartCount = 3) }
    val events = mutableListOf<String>()
    MultipartUploadEngine(store, FakeApi(server), transport, source, {}, { true }, { events.add(it) }).run("job-1")
    assertEquals(listOf("part_put job-1 2/3", "part_put job-1 3/3"), events.filter { it.startsWith("part_put") })
    assertEquals(listOf("part_ack job-1 2/3", "part_ack job-1 3/3"), events.filter { it.startsWith("part_ack") })
    assertTrue(events.any { it.startsWith("reconcile job-1 server_parts=[1]") })
  }

  private fun storageOf(s: BackgroundUploadStore): KeyValueStorage = InMemoryStorage().also { st -> s.list().forEach { st.put(it.localId, it.toJson()) } }
}
