package expo.modules.sportreelsourcereader

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BackgroundUploadStoreTest {
  @Test
  fun `stable local identity survives serialization with completed parts`() {
    val job = BackgroundUploadJob(
      localId = "job-1",
      batchId = "batch-1",
      sourceUri = "content://media/video/1",
      sourceFilename = "ride.mp4",
      mimeType = "video/mp4",
      sourceSizeBytes = 12_000_000,
      apiBaseUrl = "https://example.invalid",
      uploadId = "upload-1",
      storageKey = "raw/batch-1/ride.mp4",
      partSizeBytes = 5_000_000,
      expectedPartCount = 3,
      completedParts = listOf(BackgroundUploadPart(1, "etag-1", 5_000_000)),
      status = BackgroundUploadStatus.RETRY_WAIT,
      attempt = 2,
      lastError = "network unavailable",
      createdAt = "2026-10-01T00:00:00Z",
      updatedAt = "2026-10-01T00:01:00Z"
    )

    val restored = BackgroundUploadJob.fromJson(job.toJson())
    assertEquals(job, restored)
    assertEquals(1, restored.completedParts.size)
    assertEquals(BackgroundUploadStatus.RETRY_WAIT, restored.status)
  }

  @Test
  fun `two sources in one batch retain separate logical upload identities`() {
    val first = BackgroundUploadJob.newQueued(
      localId = "job-a", batchId = "batch-shared", sourceUri = "content://video/a",
      sourceFilename = "a.mp4", mimeType = "video/mp4", sourceSizeBytes = 100,
      apiBaseUrl = "https://example.invalid"
    )
    val second = BackgroundUploadJob.newQueued(
      localId = "job-b", batchId = "batch-shared", sourceUri = "content://video/b",
      sourceFilename = "b.mp4", mimeType = "video/mp4", sourceSizeBytes = 100,
      apiBaseUrl = "https://example.invalid"
    )

    assertEquals(first.batchId, second.batchId)
    assertNotEquals(first.localId, second.localId)
  }

  @Test
  fun `corrupt record is isolated instead of inventing upload state`() {
    assertNull(BackgroundUploadJob.fromJsonOrNull("{not-json"))
  }
}