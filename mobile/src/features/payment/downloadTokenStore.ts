import { create } from 'zustand';

/**
 * Holds the download token for an in-progress purchase, keyed by reel_id, in
 * memory only. Previously the token was passed through the navigation URL
 * (`/success/:id?dt=...`), where it could leak via screenshots, screen
 * recording, or logs. Keeping it in a transient store avoids that exposure.
 */
interface DownloadTokenState {
  tokens: Record<string, string>;
  set: (reelId: string, token: string) => void;
  get: (reelId: string) => string | undefined;
  clear: (reelId: string) => void;
}

export const useDownloadTokenStore = create<DownloadTokenState>((set, get) => ({
  tokens: {},
  set: (reelId, token) => set((s) => ({ tokens: { ...s.tokens, [reelId]: token } })),
  get: (reelId) => get().tokens[reelId],
  clear: (reelId) =>
    set((s) => {
      const next = { ...s.tokens };
      delete next[reelId];
      return { tokens: next };
    }),
}));
