import * as SecureStore from 'expo-secure-store';

const KEY = 'sportreel.operator_secret';

// The operator secret authorizes privileged writes (e.g. pricing) against the
// web-api. It is entered once on this device and stored in the OS keychain —
// never bundled in the app, so it cannot be extracted from the binary.
export async function getOperatorSecret(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(KEY);
  } catch {
    return null;
  }
}

export async function setOperatorSecret(secret: string): Promise<void> {
  await SecureStore.setItemAsync(KEY, secret.trim());
}

export async function clearOperatorSecret(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY);
}
