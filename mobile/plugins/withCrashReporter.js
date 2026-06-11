/**
 * Expo config plugin: installs a default uncaught-exception handler in
 * MainApplication.attachBaseContext that POSTs the full Java stack trace to
 * the web-api crash sink (/api/crash) before letting Android show the normal
 * crash dialog.
 *
 * attachBaseContext runs before ContentProvider initialization and
 * Application.onCreate, so this catches crashes from native module init —
 * the class of crash that JS-level guards can never see. Remove once the
 * startup crash is resolved (or keep; it is harmless in steady state).
 */
const { withMainApplication } = require('expo/config-plugins');

const CRASH_HANDLER = `
  override fun attachBaseContext(base: android.content.Context) {
    super.attachBaseContext(base)
    val previousHandler = Thread.getDefaultUncaughtExceptionHandler()
    Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
      try {
        val sw = java.io.StringWriter()
        throwable.printStackTrace(java.io.PrintWriter(sw))
        val report = "ANDROID NATIVE CRASH\\nthread=" + thread.name + "\\n" + sw.toString()
        val sender = Thread {
          try {
            val url = java.net.URL("https://video-editing-with-drone.vercel.app/api/crash")
            val conn = url.openConnection() as java.net.HttpURLConnection
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.connectTimeout = 3000
            conn.readTimeout = 3000
            conn.setRequestProperty("Content-Type", "text/plain")
            conn.outputStream.use { it.write(report.toByteArray()) }
            conn.responseCode
            conn.disconnect()
          } catch (_: Throwable) {}
        }
        sender.start()
        sender.join(4000)
      } catch (_: Throwable) {}
      previousHandler?.uncaughtException(thread, throwable)
    }
  }
`;

module.exports = function withCrashReporter(config) {
  return withMainApplication(config, (cfg) => {
    let src = cfg.modResults.contents;
    if (!src.includes('attachBaseContext')) {
      src = src.replace(
        /(\n\s*override fun onCreate\(\) \{)/,
        `\n${CRASH_HANDLER}$1`
      );
      cfg.modResults.contents = src;
    }
    return cfg;
  });
};
