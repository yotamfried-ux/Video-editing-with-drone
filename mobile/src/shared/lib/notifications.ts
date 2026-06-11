/**
 * Push notifications — temporarily disabled.
 *
 * expo-notifications requires Firebase (google-services.json) on Android.
 * Without it the native module can crash a release build at startup
 * ("SportReel keeps stopping"), and remote push cannot work anyway, so the
 * package is removed from the build entirely until Firebase is configured.
 *
 * To re-enable:
 *   1. Create a Firebase project and download google-services.json into mobile/
 *   2. app.json → android: { "googleServicesFile": "./google-services.json" }
 *   3. npx expo install expo-notifications and restore the plugin in app.json
 *   4. Restore the registration logic from this file's git history
 */
export async function registerPushToken(): Promise<void> {
  // no-op until Firebase is configured
}
