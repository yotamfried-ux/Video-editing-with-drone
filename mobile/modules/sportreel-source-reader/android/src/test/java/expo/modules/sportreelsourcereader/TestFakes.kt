package expo.modules.sportreelsourcereader

import java.io.IOException

class InMemoryStorage : KeyValueStorage {
  private val map = LinkedHashMap<String, String>()
  override fun get(key: String) = map[key]
  override fun put(key: String, value: String) { map[key] = value }
  override fun all(): Map<String, String> = LinkedHashMap(map)
  override fun remove(key: String) { map.remove(key) }
}

class FakeSource(val size: Long, var bytes: ByteArray = ByteArray(size.toInt()) { (it % 251).toByte() }) : SourceReader {
  val reads = mutableListOf<Pair<Long, Int>>()
  override fun size(uri: String): Long = size
  override fun readRange(uri: String, offset: Long, length: Int): ByteArray {
    reads.add(offset to length)
    return bytes.copyOfRange(offset.toInt(), offset.toInt() + length)
  }
}

/** Behaves like the server: tracks R2-ish multipart state, never creates a second upload per client id. */
class FakeServer(
  val sourceSize: Long, val partSize: Long, val batchId: String = "batch-1", val storageKey: String = "raw/batch-1/a.mp4"
) {
  val expectedParts = ((sourceSize + partSize - 1) / partSize).toInt()
  var startCalls = 0
  val clientIds = mutableSetOf<String>()
  var uploadId: String? = null
  val recorded = sortedMapOf<Int, BackgroundUploadPart>()
  var status = "uploading"
  var cleanupStatus = "pending"
  var completeCalls = 0
  var cleanupCalls = 0
  val objectsCreated = mutableSetOf<String>()
  val partPuts = mutableListOf<Int>()
  var failNextCalls: MutableList<(String) -> UploadApiException?> = mutableListOf()
  fun intercept(op: String) { if (failNextCalls.isNotEmpty()) failNextCalls.removeAt(0)(op)?.let { throw it } }
}

class FakeApi(val server: FakeServer) : UploadApi {
  override fun start(job: BackgroundUploadJob): StartResult {
    server.intercept("start")
    server.startCalls++
    server.clientIds.add(job.localId)
    if (server.uploadId == null) server.uploadId = "upload-1"
    return StartResult(server.uploadId!!, server.batchId, server.storageKey, server.partSize, server.expectedParts, server.sourceSize)
  }
  override fun status(job: BackgroundUploadJob): ServerStatus {
    server.intercept("status")
    return ServerStatus(server.uploadId!!, server.batchId, server.storageKey, server.sourceSize, server.status,
      server.partSize, server.expectedParts, server.recorded.values.toList(), server.cleanupStatus)
  }
  override fun partUrl(uploadId: String, partNumber: Int): PartTarget {
    server.intercept("part-url")
    val size = if (partNumber < server.expectedParts) server.partSize else server.sourceSize - server.partSize * (server.expectedParts - 1)
    return PartTarget("https://r2.invalid/$uploadId/$partNumber", size)
  }
  override fun recordPart(uploadId: String, part: BackgroundUploadPart) {
    server.intercept("record-part")
    server.recorded[part.partNumber] = part
  }
  override fun complete(uploadId: String): CompleteResult {
    server.intercept("complete")
    server.completeCalls++
    check(server.recorded.size == server.expectedParts) { "complete before all parts recorded" }
    server.status = "verified"
    server.objectsCreated.add(server.storageKey)
    return CompleteResult("verified", server.sourceSize)
  }
  override fun cleanup(uploadId: String, artifactCount: Int, reclaimedBytes: Long, sourcePreserved: Boolean) {
    server.intercept("cleanup")
    require(sourcePreserved)
    server.cleanupCalls++
    server.cleanupStatus = "confirmed"
  }
}

class FakeTransport(val server: FakeServer, val source: FakeSource) : PartTransport {
  var failNext: MutableList<() -> Exception?> = mutableListOf()
  override fun put(url: String, source: SourceReader, sourceUri: String, offset: Long, length: Int): String {
    if (failNext.isNotEmpty()) failNext.removeAt(0)()?.let { throw it }
    val n = url.substringAfterLast('/').toInt()
    val bytes = source.readRange(sourceUri, offset, length)
    check(bytes.size == length)
    server.partPuts.add(n)
    return "etag-$n"
  }
}

fun ioFailure() = IOException("network unavailable")
