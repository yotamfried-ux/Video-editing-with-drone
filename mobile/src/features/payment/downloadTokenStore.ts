import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

const tokenKey = (reelId: string) => `sportreel.payment.download-token.${reelId}`;
const checkoutSessionKey = (reelId: string) => `sportreel.payment.checkout-session.${reelId}`;

function newCheckoutSessionId(): string {
  const stamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 14);
  return `checkout_${stamp}_${random}`;
}

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
    await SecureStore.setItemAsync(tokenKey(reelId), token);
  },
  get: (reelId) => get().tokens[reelId],
  hydrate: async (reelId) => {
    const cached = get().tokens[reelId];
    if (cached) return cached;
    const stored = await SecureStore.getItemAsync(tokenKey(reelId));
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
    await SecureStore.deleteItemAsync(tokenKey(reelId));
  },
}));

/**
 * Stripe idempotency requires reusing the same key for the same logical
 * checkout. Persist the client checkout session until the purchase is complete,
 * including across repeated taps and app restarts.
 */
export async function getOrCreateCheckoutSessionId(reelId: string): Promise<string> {
  const key = checkoutSessionKey(reelId);
  const existing = await SecureStore.getItemAsync(key);
  if (existing) return existing;

  const created = newCheckoutSessionId();
  await SecureStore.setItemAsync(key, created);
  return created;
}

export async function clearCheckoutSessionId(reelId: string): Promise<void> {
  await SecureStore.deleteItemAsync(checkoutSessionKey(reelId));
}
