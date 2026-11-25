const SESSION_TTL_MS = 60 * 60 * 1000; // 60 minutes session-memory TTL (WEB-04)

let memorySecret: string | null = null;
let expiresAt = 0;

/**
 * WEB-04: Browser operator secret lives strictly in JS session memory (never localStorage,
 * sessionStorage, cookies, or URLs) and expires automatically on tab close, refresh, or TTL.
 */
export async function getOperatorSecret(): Promise<string | null> {
  if (!memorySecret) return null;
  if (Date.now() > expiresAt) {
    memorySecret = null;
    expiresAt = 0;
    return null;
  }
  expiresAt = Date.now() + SESSION_TTL_MS;
  return memorySecret;
}

export async function setOperatorSecret(secret: string): Promise<void> {
  const trimmed = secret.trim();
  if (!trimmed) {
    await clearOperatorSecret();
    return;
  }
  memorySecret = trimmed;
  expiresAt = Date.now() + SESSION_TTL_MS;
}

export async function clearOperatorSecret(): Promise<void> {
  memorySecret = null;
  expiresAt = 0;
}
