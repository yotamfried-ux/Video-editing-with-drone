package expo.modules.sportreelsourcereader

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.io.FileInputStream
import java.io.FileNotFoundException
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SharedPrefsKeyValueStorage(context: Context) : KeyValueStorage {
  private val prefs = context.applicationContext.getSharedPreferences("sportreel_background_uploads", Context.MODE_PRIVATE)
  override fun get(key: String): String? = prefs.getString(key, null)
  override fun put(key: String, value: String) { prefs.edit().putString(key, value).commit() }
  override fun all(): Map<String, String> = prefs.all.mapNotNull { (k, v) -> (v as? String)?.let { k to it } }.toMap()
  override fun remove(key: String) { prefs.edit().remove(key).commit() }
}

/** One store instance per process so the worker and the Expo module share the same mutation lock. */
object BackgroundUploadStores {
  @Volatile private var instance: BackgroundUploadStore? = null
  fun get(context: Context): BackgroundUploadStore = instance ?: synchronized(this) {
    instance ?: BackgroundUploadStore(SharedPrefsKeyValueStorage(context)).also { instance = it }
  }
}

/**
 * Keeps the operator secret the worker needs to call the authenticated API while the JS runtime is
 * dead. It is encrypted with a non-exportable Android Keystore key; it is the same operator secret
 * already held in the device keychain, never an R2 or Supabase service credential.
 */
class OperatorSecretVault(context: Context) {
  private val prefs = context.applicationContext.getSharedPreferences("sportreel_background_vault", Context.MODE_PRIVATE)

  fun put(secret: String) {
    val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
    val sealed = cipher.iv + cipher.doFinal(secret.toByteArray())
    prefs.edit().putString("operator_secret", Base64.encodeToString(sealed, Base64.NO_WRAP)).commit()
  }

  fun get(): String? = try {
    val raw = Base64.decode(prefs.getString("operator_secret", null) ?: return null, Base64.NO_WRAP)
    val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
      init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, raw.copyOfRange(0, 12)))
    }
    String(cipher.doFinal(raw.copyOfRange(12, raw.size)))
  } catch (_: Exception) { null }

  private fun key(): SecretKey {
    val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
      init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
    }.generateKey()
  }

  private companion object { const val ALIAS = "sportreel_background_upload_secret" }
}

/** Random-access content:// reader that works without a React context (worker / cold process). */
class ContentSourceReader(context: Context) : SourceReader, AutoCloseable {
  private val resolver: ContentResolver = context.applicationContext.contentResolver
  private var openUri: String? = null
  private var stream: FileInputStream? = null
  private var channel: FileChannel? = null

  override fun size(uri: String): Long {
    val parsed = contentUri(uri)
    resolver.query(parsed, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c ->
      if (c.moveToFirst() && !c.isNull(0)) c.getLong(0).takeIf { it > 0 }?.let { return it }
    }
    val pfd = resolver.openFileDescriptor(parsed, "r") ?: throw FileNotFoundException("source_unavailable: provider returned no descriptor")
    return pfd.use { it.statSize.takeIf { s -> s > 0 } ?: throw IOException("source_size_unavailable") }
  }

  @Synchronized override fun readRange(uri: String, offset: Long, length: Int): ByteArray {
    val ch = channelFor(uri)
    ch.position(offset)
    val out = ByteArray(length)
    val buf = ByteBuffer.wrap(out)
    while (buf.hasRemaining()) {
      val n = ch.read(buf)
      if (n < 0) throw IOException("source_changed_or_truncated: expected $length bytes at offset $offset, read ${buf.position()}")
    }
    return out
  }

  private fun channelFor(uri: String): FileChannel {
    if (uri == openUri && channel?.isOpen == true) return channel!!
    close()
    val pfd = resolver.openFileDescriptor(contentUri(uri), "r") ?: throw FileNotFoundException("source_unavailable: provider returned no descriptor")
    val s = FileInputStream(pfd.fileDescriptor)
    stream = s; channel = s.channel; openUri = uri
    return s.channel
  }

  @Synchronized override fun close() {
    try { channel?.close() } catch (_: IOException) {}
    try { stream?.close() } catch (_: IOException) {}
    channel = null; stream = null; openUri = null
  }

  private fun contentUri(uri: String): Uri {
    val parsed = Uri.parse(uri)
    if (parsed.scheme != ContentResolver.SCHEME_CONTENT) throw SecurityException("source_uri_invalid: only content:// sources are supported")
    return parsed
  }
}
