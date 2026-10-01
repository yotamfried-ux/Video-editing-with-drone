package expo.modules.sportreelsourcereader

data class UploadProgressSummary(val title: String, val verified: Int, val total: Int, val failed: Int, val percent: Int) {
  companion object {
    /** Derived only from durable job state, never from in-memory UI state. */
    fun forBatch(jobs: List<BackgroundUploadJob>, batchId: String): UploadProgressSummary {
      val batch = jobs.filter { it.batchId == batchId }
      val verified = batch.count { it.status == BackgroundUploadStatus.VERIFIED }
      val failed = batch.count { it.status == BackgroundUploadStatus.FAILED }
      val doneUnits = batch.sumOf { if (it.status == BackgroundUploadStatus.VERIFIED) 1.0 else partFraction(it) }
      val percent = if (batch.isEmpty()) 0 else Math.round(doneUnits / batch.size * 100).toInt()
      return UploadProgressSummary("SportReel — Uploading $verified/${batch.size} videos", verified, batch.size, failed, percent)
    }

    private fun partFraction(job: BackgroundUploadJob): Double {
      val total = job.expectedPartCount ?: return 0.0
      return if (total <= 0) 0.0 else minOf(1.0, job.completedParts.size.toDouble() / total)
    }
  }
}
