import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

const keyForReel = (reelId: string) => `sportreel_download_token_${reelId}`;

interface DownloadTokenState {
  tokens: Record<string, string>;
  set: (reelId: string, token: string) => Promise<void>;
  get: (reelId: string) => string | undefined;
  hydrate: (reelId: string) => Promise<string | undefined>;
  clear: (reelId: string) => Promise<void>;
}

/**
 * Download tokens are bearer credentials. Keep them out of routes, logs, and
 * screenshots, while persisting them in the OS-backed secure store so a payment
 * can still finish after a redirect, process death, or app restart.
 */
export const useDownloadTokenStore = create<DownloadTokenState>((set, get) => ({
  tokens: {},
  set: async (reelId, token) => {
    set((state) => ({ tokens: { ...state.tokens, [reelId]: token } }));
    await SecureStore.setItemAsync(keyForReel(reelId), token);
  },
  get: (reelId) => get().tokens[reelId],
  hydrate: async (reelId) => {
    const cached = get().tokens[reelId];
    if (cached) return cached;
    const stored = await SecureStore.getItemAsync(keyForReel(reelId));
    if (!stored) return undefined;
    set((state) => ({ tokens: { ...state.tokens, [reelId]: stored } }));
    return stored;
  },
  clear: async (reelId) => {
    set((state) => {
      const next = { ...state.tokens };
      delete next[reelId];
      return { tokens: next };
    });
    await SecureStore.deleteItemAsync(keyForReel(reelId));
  },
}));
