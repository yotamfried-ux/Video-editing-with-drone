import { create } from 'zustand';
import { clearOperatorSecret } from '../lib/operatorSecret';
import { verifyRegisteredBrowserBiometric } from '../lib/browserBiometric';

const UNLOCK_TTL_MS = 60 * 60 * 1000;
let lockTimer: ReturnType<typeof setTimeout> | null = null;

interface OperatorUnlockState {
  unlocked: boolean;
  unlock: () => Promise<boolean>;
  lock: () => void;
}

/**
 * WEB-04: Browser operator unlock state (session-memory only, auto-locks after 60m and clears
 * any in-memory operator secret). Uses enrolled WebAuthn biometrics on phones/capable devices;
 * on PCs without biometrics, unlocks to settings where server-verified OPERATOR_SECRET is required.
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
    void clearOperatorSecret();
    set({ unlocked: false });
  },
}));
