import * as Updates from 'expo-updates';

export async function applyPendingUpdate(): Promise<void> {
  if (__DEV__ || !Updates.isEnabled) return;
  try {
    const check = await Updates.checkForUpdateAsync();
    if (check.isAvailable) {
      await Updates.fetchUpdateAsync();
      await Updates.reloadAsync();
    }
  } catch {
    // Offline or update server unreachable — continue with the current bundle.
  }
}
