package expo.modules.sportreelsourcereader

import org.junit.Assert.assertEquals
import org.junit.Test

class UploadProgressSummaryTest {
  private fun job(id: String, status: BackgroundUploadStatus, parts: Int = 0, total: Int = 4) =
    BackgroundUploadJob.newQueued(id, "b1", "content://$id", "$id.mp4", "video/mp4", 400, "https://x.invalid").copy(
      status = status, partSizeBytes = 100, expectedPartCount = total,
      completedParts = (1..parts).map { BackgroundUploadPart(it, "e", 100) })

  @Test fun `title counts verified over total videos in the batch`() {
    val jobs = (1..53).map { job("v$it", if (it <= 17) BackgroundUploadStatus.VERIFIED else BackgroundUploadStatus.UPLOADING, if (it <= 17) 4 else 0) }
    val s = UploadProgressSummary.forBatch(jobs, "b1")
    assertEquals("SportReel — Uploading 17/53 videos", s.title)
    assertEquals(17, s.verified); assertEquals(53, s.total)
  }

  @Test fun `percent derives from durable acknowledged parts`() {
    val jobs = listOf(job("a", BackgroundUploadStatus.VERIFIED, 4), job("b", BackgroundUploadStatus.UPLOADING, 2))
    assertEquals(75, UploadProgressSummary.forBatch(jobs, "b1").percent)
  }

  @Test fun `failed jobs surface in the text`() {
    val jobs = listOf(job("a", BackgroundUploadStatus.FAILED), job("b", BackgroundUploadStatus.UPLOADING))
    assertEquals(1, UploadProgressSummary.forBatch(jobs, "b1").failed)
  }

  @Test fun `other batches are ignored`() {
    val other = job("z", BackgroundUploadStatus.UPLOADING).copy(batchId = "b2")
    assertEquals(1, UploadProgressSummary.forBatch(listOf(job("a", BackgroundUploadStatus.UPLOADING), other), "b1").total)
  }
}
