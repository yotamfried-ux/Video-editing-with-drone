package expo.modules.sportreelsourcereader

import org.junit.Assert.*
import org.junit.Test

class BackgroundUploadStoreBehaviorTest {
  private fun job(id: String, batch: String = "b1", status: BackgroundUploadStatus = BackgroundUploadStatus.QUEUED) =
    BackgroundUploadJob.newQueued(id, batch, "content://v/$id", "$id.mp4", "video/mp4", 100, "https://x.invalid").copy(status = status)

  @Test fun `duplicate enqueue returns the existing job and does not reset progress`() {
    val store = BackgroundUploadStore(InMemoryStorage())
    store.enqueue(job("a"))
    store.update("a") { it.copy(uploadId = "u1", completedParts = listOf(BackgroundUploadPart(1, "e", 5))) }
    val again = store.enqueue(job("a"))
    assertEquals("u1", again.uploadId)
    assertEquals(1, store.list().size)
  }

  @Test fun `state survives store reconstruction over the same storage`() {
    val storage = InMemoryStorage()
    BackgroundUploadStore(storage).apply { enqueue(job("a")); update("a") { it.copy(status = BackgroundUploadStatus.RETRY_WAIT, attempt = 3) } }
    val restored = BackgroundUploadStore(storage).get("a")!!
    assertEquals(BackgroundUploadStatus.RETRY_WAIT, restored.status)
    assertEquals(3, restored.attempt)
  }

  @Test fun `corrupt record is isolated from valid ones`() {
    val storage = InMemoryStorage()
    val store = BackgroundUploadStore(storage)
    store.enqueue(job("a"))
    storage.put("bad", "{not-json")
    assertEquals(listOf("a"), store.list().map { it.localId })
    assertNull(store.get("bad"))
  }

  @Test fun `resume eligibility excludes verified and failed but includes in-flight states`() {
    val store = BackgroundUploadStore(InMemoryStorage())
    BackgroundUploadStatus.values().forEach { store.enqueue(job(it.name, status = it)) }
    assertEquals(
      setOf("QUEUED", "UPLOADING", "RETRY_WAIT", "COMPLETING"),
      store.eligibleForResume().map { it.localId }.toSet()
    )
  }

  @Test fun `explicit requeue of a failed job keeps multipart identity`() {
    val store = BackgroundUploadStore(InMemoryStorage())
    store.enqueue(job("a", status = BackgroundUploadStatus.FAILED).copy(uploadId = "u1", lastError = "x", attempt = 9))
    val re = store.requeueFailed("a")!!
    assertEquals(BackgroundUploadStatus.QUEUED, re.status)
    assertEquals("u1", re.uploadId)
    assertEquals(0, re.attempt)
    assertNull(re.lastError)
  }

  @Test fun `jobs in one batch are listed together`() {
    val store = BackgroundUploadStore(InMemoryStorage())
    store.enqueue(job("a", "b1")); store.enqueue(job("b", "b1")); store.enqueue(job("c", "b2"))
    assertEquals(setOf("a", "b"), store.listByBatch("b1").map { it.localId }.toSet())
  }

  @Test fun `forgetting a batch removes only its verified jobs`() {
    val store = BackgroundUploadStore(InMemoryStorage())
    store.enqueue(job("v", "b1", BackgroundUploadStatus.VERIFIED)); store.enqueue(job("u", "b1", BackgroundUploadStatus.UPLOADING)); store.enqueue(job("o", "b2", BackgroundUploadStatus.VERIFIED))
    assertEquals(1, store.removeVerifiedBatch("b1"))
    assertEquals(setOf("u", "o"), store.list().map { it.localId }.toSet())
  }
}

class BackgroundUploadIdentityTest {
  @Test fun `same batch source and size always map to the same valid client upload id`() {
    val a = BackgroundUploadIdentity.localId("batch-1", "content://v/1", 100)
    assertEquals(a, BackgroundUploadIdentity.localId("batch-1", "content://v/1", 100))
    assertTrue(Regex("^[A-Za-z0-9_-]{16,128}$").matches(a))
  }
  @Test fun `different source batch or size gives a different identity`() {
    val a = BackgroundUploadIdentity.localId("batch-1", "content://v/1", 100)
    assertNotEquals(a, BackgroundUploadIdentity.localId("batch-1", "content://v/2", 100))
    assertNotEquals(a, BackgroundUploadIdentity.localId("batch-2", "content://v/1", 100))
    assertNotEquals(a, BackgroundUploadIdentity.localId("batch-1", "content://v/1", 101))
  }
  @Test fun `bridge map exposes lowercase status and durable progress`() {
    val job = BackgroundUploadJob.newQueued("x", "b", "content://v", "a.mp4", "video/mp4", 10, "https://x.invalid")
      .copy(status = BackgroundUploadStatus.RETRY_WAIT, expectedPartCount = 4, completedParts = listOf(BackgroundUploadPart(1, "e", 1)))
    val m = job.toBridgeMap()
    assertEquals("retry_wait", m["status"]); assertEquals(0.25, m["progress"]); assertEquals(1, m["completedPartCount"])
  }
}
