import { create } from 'zustand';
import { clearOperatorSecret } from '../lib/operatorSecret';

const UNLOCK_TTL_MS = 60 * 60 * 1000;
let lockTimer: ReturnType<typeof setTimeout> | null = null;

interface OperatorUnlockState {
  unlocked: boolean;
  unlock: () => Promise<boolean>;
  lock: () => void;
}

/**
 * WEB-04: Browser operator unlock state (session-memory only, auto-locks after 60m and clears
 * any in-memory operator secret). Server-side requireOperator remains authoritative on every API call.
 */
export const useOperatorUnlock = create<OperatorUnlockState>((set, get) => ({
  unlocked: false,
  unlock: async () => {
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
