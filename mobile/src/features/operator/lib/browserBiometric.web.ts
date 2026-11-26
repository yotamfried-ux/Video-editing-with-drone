const WEBAUTHN_CRED_KEY = 'sportreel_operator_webauthn_cred_id';

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

export async function isBrowserBiometricAvailable(): Promise<boolean> {
  if (
    typeof window === 'undefined' ||
    typeof navigator === 'undefined' ||
    !navigator.credentials ||
    typeof PublicKeyCredential === 'undefined' ||
    typeof PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable !== 'function'
  ) {
    return false;
  }
  return PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable().catch(() => false);
}

export function isBrowserBiometricEnabled(): boolean {
  if (typeof window === 'undefined' || !window.localStorage) return false;
  return Boolean(window.localStorage.getItem(WEBAUTHN_CRED_KEY));
}

/**
 * Only prompts for device biometrics when explicitly enrolled on this browser (e.g. phone).
 * PCs without biometrics skip the WebAuthn prompt and rely on server-verified OPERATOR_SECRET.
 */
export async function verifyRegisteredBrowserBiometric(): Promise<boolean> {
  if (typeof window === 'undefined' || !window.localStorage) return true;
  const storedCredId = window.localStorage.getItem(WEBAUTHN_CRED_KEY);
  if (!storedCredId) return true;
  if (!(await isBrowserBiometricAvailable())) return true;

  const challenge = new Uint8Array(new ArrayBuffer(32));
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(challenge);
  }
  try {
    const assertion = await navigator.credentials.get({
      publicKey: {
        challenge,
        allowCredentials: [{ id: fromBase64Url(storedCredId), type: 'public-key', transports: ['internal'] }],
        userVerification: 'required',
        timeout: 60000,
      },
    });
    return Boolean(assertion);
  } catch {
    return false;
  }
}

export async function enableBrowserBiometric(): Promise<boolean> {
  if (!(await isBrowserBiometricAvailable())) return false;
  const challenge = new Uint8Array(new ArrayBuffer(32));
  const userId = new Uint8Array(new ArrayBuffer(16));
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(challenge);
    crypto.getRandomValues(userId);
  }
  try {
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

export function disableBrowserBiometric(): void {
  if (typeof window !== 'undefined' && window.localStorage) {
    window.localStorage.removeItem(WEBAUTHN_CRED_KEY);
  }
}
