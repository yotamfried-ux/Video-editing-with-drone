package expo.modules.sportreelsourcereader

import android.content.ContentResolver
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import expo.modules.kotlin.functions.Coroutine
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.FileNotFoundException
import java.io.IOException
import java.nio.ByteBuffer

class SportReelSourceReaderModule : Module() {
  companion object {
    private const val MAX_RANGE_BYTES = 64 * 1024 * 1024
  }

  override fun definition() = ModuleDefinition {
    Name("SportReelSourceReader")

    AsyncFunction("inspectSource") Coroutine { uriString: String ->
      withContext(Dispatchers.IO) {
        val resolver = requireResolver()
        val uri = requireContentUri(uriString)
        val metadata = queryMetadata(resolver, uri)
        val descriptorSize = readDescriptorSize(resolver, uri)
        val sourceSize = metadata.sizeBytes ?: descriptorSize
          ?: throw IOException("source_size_unavailable: provider did not expose a stable source size")

        if (sourceSize <= 0L) {
          throw IOException("source_size_unavailable: source size must be positive")
        }

        mapOf(
          "uri" to uri.toString(),
          "displayName" to metadata.displayName,
          "sizeBytes" to sourceSize,
          "seekable" to isSeekable(resolver, uri),
          "maxRangeBytes" to MAX_RANGE_BYTES
        )
      }
    }

    AsyncFunction("readRange") Coroutine { uriString: String, offset: Long, length: Int ->
      withContext(Dispatchers.IO) {
        require(offset >= 0L) { "range_invalid: offset must be non-negative" }
        require(length > 0) { "range_invalid: length must be positive" }
        require(length <= MAX_RANGE_BYTES) {
          "range_too_large: length must not exceed $MAX_RANGE_BYTES bytes"
        }

        val resolver = requireResolver()
        val uri = requireContentUri(uriString)
        readExactRange(resolver, uri, offset, length)
      }
    }
  }

  private fun requireResolver(): ContentResolver {
    val context = appContext.reactContext
      ?: throw IllegalStateException("source_reader_unavailable: React context is unavailable")
    return context.contentResolver
  }

  private fun requireContentUri(uriString: String): Uri {
    val uri = Uri.parse(uriString)
    if (uri.scheme != ContentResolver.SCHEME_CONTENT) {
      throw IllegalArgumentException("source_uri_invalid: only content:// SD/USB sources are supported")
    }
    return uri
  }

  private data class SourceMetadata(
    val displayName: String?,
    val sizeBytes: Long?
  )

  private fun queryMetadata(resolver: ContentResolver, uri: Uri): SourceMetadata {
    var cursor: Cursor? = null
    return try {
      cursor = resolver.query(
        uri,
        arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
        null,
        null,
        null
      )
      if (cursor == null || !cursor.moveToFirst()) {
        SourceMetadata(null, null)
      } else {
        val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
        val name = if (nameIndex >= 0 && !cursor.isNull(nameIndex)) cursor.getString(nameIndex) else null
        val size = if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) cursor.getLong(sizeIndex) else null
        SourceMetadata(name, size?.takeIf { it >= 0L })
      }
    } finally {
      cursor?.close()
    }
  }

  private fun readDescriptorSize(resolver: ContentResolver, uri: Uri): Long? {
    val descriptor = resolver.openFileDescriptor(uri, "r")
      ?: throw FileNotFoundException("source_unavailable: provider returned no descriptor")
    return descriptor.use {
      it.statSize.takeIf { size -> size >= 0L }
    }
  }

  private fun isSeekable(resolver: ContentResolver, uri: Uri): Boolean {
    val descriptor = resolver.openFileDescriptor(uri, "r") ?: return false
    return descriptor.use {
      try {
        Os.lseek(it.fileDescriptor, 0L, OsConstants.SEEK_CUR)
        true
      } catch (_: ErrnoException) {
        false
      } catch (_: IOException) {
        false
      }
    }
  }

  private fun readExactRange(
    resolver: ContentResolver,
    uri: Uri,
    offset: Long,
    length: Int
  ): ByteArray {
    val descriptor = resolver.openFileDescriptor(uri, "r")
      ?: throw FileNotFoundException("source_unavailable: provider returned no descriptor")

    ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { input ->
      val channel = input.channel
      try {
        channel.position(offset)
      } catch (error: Exception) {
        throw IOException("source_not_seekable: provider cannot seek to byte offset $offset", error)
      }

      val result = ByteArray(length)
      val buffer = ByteBuffer.wrap(result)
      var totalRead = 0
      while (buffer.hasRemaining()) {
        val read = channel.read(buffer)
        if (read < 0) break
        if (read == 0) continue
        totalRead += read
      }

      if (totalRead != length) {
        throw IOException(
          "source_changed_or_truncated: expected $length bytes at offset $offset, read $totalRead"
        )
      }
      return result
    }
  }
}
