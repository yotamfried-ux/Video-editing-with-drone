import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

const tokenKey = (reelId: string) => `sportreel.payment.download-token.${reelId}`;

function payerScope(payerEmail: string): string {
  const normalized = payerEmail.trim().toLowerCase();
  if (!normalized) throw new Error('Payer email is required for checkout persistence');

  // FNV-1a is used only to avoid putting the email address in the SecureStore
  // key. It is not a security boundary; the checkout session itself is random.
  let hash = 0x811c9dc5;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

const checkoutSessionKey = (reelId: string, payerEmail: string) => (
  `sportreel.payment.checkout-session.${reelId}.${payerScope(payerEmail)}`
);

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
 * checkout. Persist it across repeated taps and restarts, but scope it to both
 * reel and payer so a shared device never reuses another user's Stripe key.
 */
export async function getOrCreateCheckoutSessionId(reelId: string, payerEmail: string): Promise<string> {
  const key = checkoutSessionKey(reelId, payerEmail);
  const existing = await SecureStore.getItemAsync(key);
  if (existing) return existing;

  const created = newCheckoutSessionId();
  await SecureStore.setItemAsync(key, created);
  return created;
}

export async function clearCheckoutSessionId(reelId: string, payerEmail: string): Promise<void> {
  await SecureStore.deleteItemAsync(checkoutSessionKey(reelId, payerEmail));
}
