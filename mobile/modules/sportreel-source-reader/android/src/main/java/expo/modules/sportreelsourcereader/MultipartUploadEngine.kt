package expo.modules.sportreelsourcereader

import java.io.IOException

sealed class EngineOutcome {
  object Success : EngineOutcome()
  data class Retry(val reason: String) : EngineOutcome()
  data class Failed(val reason: String) : EngineOutcome()
}

private class PermanentFailure(message: String) : Exception(message)
private class StopRequested : Exception("stop requested")

/**
 * Durable multipart executor. Server state is the source of truth: every run starts by
 * reconciling with `/status`, uploads only parts the server has not acknowledged, and
 * persists each acknowledged transition before moving on. Pure Kotlin so the protocol and
 * resume semantics are unit-testable without Android.
 */
class MultipartUploadEngine(
  private val store: BackgroundUploadStore,
  private val api: UploadApi,
  private val transport: PartTransport,
  private val source: SourceReader,
  private val onProgress: (BackgroundUploadJob) -> Unit,
  private val shouldContinue: () -> Boolean,
  private val onEvent: (String) -> Unit = {}
) {
  companion object { const val MAX_ATTEMPTS = 20 }

  fun run(localId: String): EngineOutcome {
    val initial = store.get(localId) ?: return EngineOutcome.Failed("job_missing: $localId")
    if (initial.status == BackgroundUploadStatus.VERIFIED) return EngineOutcome.Success
    if (initial.attempt >= MAX_ATTEMPTS) return fail(localId, "attempt_budget_exhausted: ${initial.lastError ?: "retries exhausted"}")

    mutate(localId) { it.copy(status = BackgroundUploadStatus.UPLOADING, attempt = it.attempt + 1, lastError = null) }
    return try {
      execute(localId)
      EngineOutcome.Success
    } catch (e: StopRequested) {
      // Not a failed attempt: hand the durable job back to WorkManager untouched.
      mutate(localId) { it.copy(status = BackgroundUploadStatus.RETRY_WAIT, attempt = maxOf(0, it.attempt - 1)) }
      EngineOutcome.Retry("stopped")
    } catch (e: PermanentFailure) {
      fail(localId, e.message ?: "permanent_failure")
    } catch (e: UploadApiException) {
      if (e.retryable) retry(localId, e.message ?: "transient_error") else fail(localId, "api_${e.status ?: "error"}: ${e.message}")
    } catch (e: SecurityException) {
      fail(localId, "source_permission_lost: ${e.message}")
    } catch (e: IOException) {
      // Connectivity/DNS failures are environmental, not evidence that the upload is bad.
      // Do not let a temporary offline period consume the durable product retry budget.
      mutate(localId) { it.copy(attempt = maxOf(0, it.attempt - 1)) }
      retry(localId, e.message ?: "io_error")
    }
  }

  private fun execute(localId: String) {
    var job = require(localId)
    checkContinue()
    val currentSize = try { source.size(job.sourceUri) } catch (e: IOException) { throw e }
    if (currentSize != job.sourceSizeBytes) {
      throw PermanentFailure("source_changed: size ${job.sourceSizeBytes} -> $currentSize")
    }

    if (job.uploadId == null) {
      val started = api.start(job)
      if (started.sourceSizeBytes != job.sourceSizeBytes) throw PermanentFailure("start_size_mismatch")
      job = mutate(localId) {
        it.copy(uploadId = started.uploadId, storageKey = started.storageKey, partSizeBytes = started.partSizeBytes,
          expectedPartCount = started.expectedPartCount, batchId = started.batchId)
      }
    }
    val uploadId = job.uploadId!!

    checkContinue()
    val server = api.status(job)
    if (server.storageKey != job.storageKey || server.sourceSizeBytes != job.sourceSizeBytes ||
      server.partSizeBytes != job.partSizeBytes || server.expectedPartCount != job.expectedPartCount ||
      server.batchId != job.batchId
    ) throw PermanentFailure("server_state_mismatch: durable multipart state does not match the server")
    if (server.status in setOf("aborted", "superseded", "size_mismatch")) throw PermanentFailure("server_status_${server.status}")

    // Server truth wins over local belief.
    onEvent("reconcile ${job.localId} server_parts=${server.parts.map { it.partNumber }} status=${server.status}")
    job = mutate(localId) { it.copy(completedParts = server.parts.sortedBy { p -> p.partNumber }) }
    onProgress(job)

    if (server.status != "verified") {
      uploadMissingParts(localId, uploadId)
      checkContinue()
      mutate(localId) { it.copy(status = BackgroundUploadStatus.COMPLETING) }
      val done = api.complete(uploadId)
      if (done.status != "verified" || done.verifiedSizeBytes != job.sourceSizeBytes) {
        throw PermanentFailure("completion_not_verified: ${done.status} ${done.verifiedSizeBytes}/${job.sourceSizeBytes}")
      }
      confirmCleanup(localId, uploadId)
    } else if (server.cleanupStatus != "confirmed") {
      mutate(localId) { it.copy(status = BackgroundUploadStatus.COMPLETING) }
      confirmCleanup(localId, uploadId)
    }
    val finished = mutate(localId) { it.copy(status = BackgroundUploadStatus.VERIFIED, lastError = null) }
    onProgress(finished)
  }

  private fun uploadMissingParts(localId: String, uploadId: String) {
    val job = require(localId)
    val partSize = job.partSizeBytes!!
    val count = job.expectedPartCount!!
    for (partNumber in 1..count) {
      if (require(localId).completedParts.any { it.partNumber == partNumber }) continue
      checkContinue()
      val offset = (partNumber - 1) * partSize
      val expected = if (partNumber < count) partSize else job.sourceSizeBytes - partSize * (count - 1)
      val target = api.partUrl(uploadId, partNumber)
      if (target.sizeBytes != expected) throw PermanentFailure("part_size_mismatch: part $partNumber expected $expected, server ${target.sizeBytes}")
      onEvent("part_put ${job.localId} ${partNumber}/${count}")
      val etag = transport.put(target.uploadUrl, source, job.sourceUri, offset, expected.toInt())
      val part = BackgroundUploadPart(partNumber, etag, expected)
      api.recordPart(uploadId, part)
      onEvent("part_ack ${job.localId} ${partNumber}/${count}")
      val updated = mutate(localId) { cur ->
        cur.copy(completedParts = (cur.completedParts.filter { it.partNumber != partNumber } + part).sortedBy { it.partNumber })
      }
      onProgress(updated)
    }
  }

  private fun confirmCleanup(localId: String, uploadId: String) {
    val job = require(localId)
    // The worker streams straight from the source and creates no temp artifacts; prove the original is untouched.
    val preserved = source.size(job.sourceUri) == job.sourceSizeBytes
    if (!preserved) throw PermanentFailure("source_not_preserved")
    api.cleanup(uploadId, 0, 0L, true)
  }

  private fun checkContinue() { if (!shouldContinue()) throw StopRequested() }
  private fun require(localId: String) = store.get(localId) ?: throw PermanentFailure("job_missing: $localId")
  private fun mutate(localId: String, f: (BackgroundUploadJob) -> BackgroundUploadJob) =
    store.update(localId, f) ?: throw PermanentFailure("job_missing: $localId")

  private fun retry(localId: String, reason: String): EngineOutcome {
    mutate(localId) { it.copy(status = BackgroundUploadStatus.RETRY_WAIT, lastError = reason) }
    return EngineOutcome.Retry(reason)
  }

  private fun fail(localId: String, reason: String): EngineOutcome {
    store.update(localId) { it.copy(status = BackgroundUploadStatus.FAILED, lastError = reason) }
    return EngineOutcome.Failed(reason)
  }
}
