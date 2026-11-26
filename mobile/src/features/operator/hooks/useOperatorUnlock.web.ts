import { create } from 'zustand';
import { clearOperatorSecret } from '../lib/operatorSecret';

const UNLOCK_TTL_MS = 60 * 60 * 1000;
const WEBAUTHN_CRED_KEY = 'sportreel_operator_webauthn_cred_id';
let lockTimer: ReturnType<typeof setTimeout> | null = null;

function toBase64Url(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((value.length + 3) % 4);
  const bin = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out;
}

async function verifyBrowserBiometric(): Promise<boolean> {
  if (
    typeof window === 'undefined' ||
    typeof navigator === 'undefined' ||
    !navigator.credentials ||
    typeof PublicKeyCredential === 'undefined' ||
    typeof PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable !== 'function'
  ) {
    return true;
  }
  const available = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable().catch(() => false);
  if (!available) return true;

  const challenge = new Uint8Array(new ArrayBuffer(32));
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(challenge);
  }
  const storedCredId = window.localStorage?.getItem(WEBAUTHN_CRED_KEY);

  try {
    if (storedCredId) {
      const assertion = await navigator.credentials.get({
        publicKey: {
          challenge,
          allowCredentials: [{ id: fromBase64Url(storedCredId), type: 'public-key', transports: ['internal'] }],
          userVerification: 'required',
          timeout: 60000,
        },
      });
      return Boolean(assertion);
    }

    const userId = new Uint8Array(new ArrayBuffer(16));
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      crypto.getRandomValues(userId);
    }
    const created = (await navigator.credentials.create({
      publicKey: {
        rp: { name: 'SportReel Operator', id: window.location.hostname },
        user: { id: userId, name: 'operator@sportreel', displayName: 'SportReel Operator' },
        challenge,
        pubKeyCredParams: [
          { alg: -7, type: 'public-key' },
          { alg: -257, type: 'public-key' },
        ],
        authenticatorSelection: {
          authenticatorAttachment: 'platform',
          userVerification: 'required',
          residentKey: 'preferred',
        },
        timeout: 60000,
      },
    })) as PublicKeyCredential | null;
    if (!created) return false;
    window.localStorage?.setItem(WEBAUTHN_CRED_KEY, toBase64Url(created.rawId));
    return true;
  } catch {
    return false;
  }
}

interface OperatorUnlockState {
  unlocked: boolean;
  unlock: () => Promise<boolean>;
  lock: () => void;
}

/**
 * WEB-04: Browser operator unlock state (session-memory only, auto-locks after 60m and clears
 * any in-memory operator secret). Uses WebAuthn platform biometrics (Windows Hello / phone
 * fingerprint) when available; server-side requireOperator remains authoritative on every API call.
 */
export const useOperatorUnlock = create<OperatorUnlockState>((set, get) => ({
  unlocked: false,
  unlock: async () => {
    const ok = await verifyBrowserBiometric();
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
