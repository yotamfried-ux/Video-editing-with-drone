import { create } from 'zustand';
import * as LocalAuthentication from 'expo-local-authentication';

interface OperatorUnlockState {
  unlocked: boolean;
  /** Runs biometric auth (no-op if already unlocked). Returns success. */
  unlock: () => Promise<boolean>;
  lock: () => void;
}

// Session-scoped operator unlock. Biometric runs once at the entry point
// (profile 5-tap); every (operator) screen just checks the flag. This avoids
// re-prompting on every internal navigation and the remount loops caused by
// wrapping the navigator in an auth gate.
export const useOperatorUnlock = create<OperatorUnlockState>((set, get) => ({
  unlocked: false,
  unlock: async () => {
    if (get().unlocked) return true;
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Operator access requires authentication',
      fallbackLabel: 'Use Passcode',
    });
    if (result.success) set({ unlocked: true });
    return result.success;
  },
  lock: () => set({ unlocked: false }),
}));
