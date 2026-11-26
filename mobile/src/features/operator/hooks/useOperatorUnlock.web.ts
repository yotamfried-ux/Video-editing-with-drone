import { create } from 'zustand';
import { verifyRegisteredBrowserBiometric } from '../lib/browserBiometric';

const UNLOCK_TTL_MS = 60 * 60 * 1000;
let lockTimer: ReturnType<typeof setTimeout> | null = null;

interface OperatorUnlockState {
  unlocked: boolean;
  unlock: () => Promise<boolean>;
  lock: () => void;
}

/**
 * WEB-04: Browser operator unlock state (auto-locks after 60m or Exit without wiping
 * the encrypted WebCrypto IndexedDB device vault; explicit Remove in Settings clears it).
 */
export const useOperatorUnlock = create<OperatorUnlockState>((set, get) => ({
  unlocked: false,
  unlock: async () => {
    const ok = await verifyRegisteredBrowserBiometric();
    if (!ok) return false;
    if (lockTimer) clearTimeout(lockTimer);
    lockTimer = setTimeout(() => {
      get().lock();
    }, UNLOCK_TTL_MS);
    set({ unlocked: true });
    return true;
  },
  lock: () => {
    if (lockTimer) {
      clearTimeout(lockTimer);
      lockTimer = null;
    }
    set({ unlocked: false });
  },
}));
