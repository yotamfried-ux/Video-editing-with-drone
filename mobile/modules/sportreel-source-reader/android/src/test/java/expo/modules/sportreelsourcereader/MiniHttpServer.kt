package expo.modules.sportreelsourcereader

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket

/** Dependency-free HTTP/1.1 test server (plain sockets) so tests run on both the JVM and Gradle's Android test classpath. */
class MiniHttpServer(private val handler: (Request) -> Response) : AutoCloseable {
  class Request(val method: String, val path: String, val headers: Map<String, String>, val body: ByteArray)
  class Response(val status: Int, val body: String = "", val headers: Map<String, String> = emptyMap())

  private val socket = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
  val port: Int get() = socket.localPort
  @Volatile private var running = true
  private val thread = Thread {
    while (running) {
      val client = try { socket.accept() } catch (_: Exception) { break }
      Thread { serve(client) }.apply { isDaemon = true }.start()
    }
  }.apply { isDaemon = true; start() }

  private fun readLine(input: InputStream): String? {
    val sb = ByteArrayOutputStream()
    while (true) {
      val b = input.read()
      if (b < 0) return if (sb.size() == 0) null else sb.toString("ISO-8859-1")
      if (b == '\n'.code) return sb.toString("ISO-8859-1").trimEnd('\r')
      sb.write(b)
    }
  }

  private fun serve(client: Socket) { client.use { c ->
    try {
      val input = c.getInputStream()
      val requestLine = readLine(input) ?: return@use
      val (method, path) = requestLine.split(" ").let { it[0] to it[1] }
      val headers = LinkedHashMap<String, String>()
      while (true) {
        val line = readLine(input) ?: break
        if (line.isEmpty()) break
        val i = line.indexOf(':')
        if (i > 0) headers[line.substring(0, i).trim().lowercase()] = line.substring(i + 1).trim()
      }
      val length = headers["content-length"]?.toIntOrNull() ?: 0
      val body = ByteArray(length)
      var read = 0
      while (read < length) { val n = input.read(body, read, length - read); if (n < 0) break; read += n }
      val response = handler(Request(method, path, headers, body))
      val bytes = response.body.toByteArray()
      val head = StringBuilder("HTTP/1.1 ${response.status} X\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n")
      response.headers.forEach { (k, v) -> head.append("$k: $v\r\n") }
      head.append("\r\n")
      c.getOutputStream().apply { write(head.toString().toByteArray()); write(bytes); flush() }
    } catch (_: Exception) {}
  } }

  override fun close() { running = false; try { socket.close() } catch (_: Exception) {}; thread.interrupt() }
}
