export async function registerPushToken(): Promise<string | null> {
  // Documented web parity boundary (§17.4 #4): native Expo push tokens are disabled on web.
  return null;
}
