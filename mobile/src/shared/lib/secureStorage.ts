import * as SecureStore from 'expo-secure-store';

/**
 * SecureStore-backed storage adapter for the Supabase auth client.
 *
 * On Android, AsyncStorage is unencrypted — a rooted/compromised device can
 * read the persisted session and refresh token. SecureStore uses the OS
 * keychain/keystore. SecureStore values are capped at ~2KB, but Supabase
 * sessions exceed that, so values are transparently chunked:
 *   - `<key>`        → number of chunks (a manifest)
 *   - `<key>.0..N-1` → the chunk slices
 */
const CHUNK_SIZE = 1800; // headroom under SecureStore's ~2KB limit

function chunkKey(key: string, i: number): string {
  return `${key}.${i}`;
}

async function clearChunks(key: string): Promise<void> {
  const manifest = await SecureStore.getItemAsync(key);
  if (manifest && /^\d+$/.test(manifest)) {
    const count = parseInt(manifest, 10);
    for (let i = 0; i < count; i++) {
      await SecureStore.deleteItemAsync(chunkKey(key, i));
    }
  }
}

export const secureStorage = {
  async getItem(key: string): Promise<string | null> {
    const manifest = await SecureStore.getItemAsync(key);
    if (manifest === null) return null;
    if (!/^\d+$/.test(manifest)) {
      // Legacy/plain value stored directly under the key.
      return manifest;
    }
    const count = parseInt(manifest, 10);
    let out = '';
    for (let i = 0; i < count; i++) {
      const part = await SecureStore.getItemAsync(chunkKey(key, i));
      if (part === null) return null; // corrupt/partial — treat as missing
      out += part;
    }
    return out;
  },

  async setItem(key: string, value: string): Promise<void> {
    await clearChunks(key); // drop any previous chunks first
    const count = Math.max(1, Math.ceil(value.length / CHUNK_SIZE));
    for (let i = 0; i < count; i++) {
      await SecureStore.setItemAsync(
        chunkKey(key, i),
        value.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE)
      );
    }
    await SecureStore.setItemAsync(key, String(count));
  },

  async removeItem(key: string): Promise<void> {
    await clearChunks(key);
    await SecureStore.deleteItemAsync(key);
  },
};
