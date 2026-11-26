const SESSION_TTL_MS = 60 * 60 * 1000; // 60 minutes active-session cache
const DB_NAME = 'sportreel_operator_vault';
const STORE_NAME = 'vault';
const RECORD_KEY = 'operator_secret_v1';

interface VaultRecord {
  key: CryptoKey;
  iv: Uint8Array;
  ciphertext: ArrayBuffer;
}

let memorySecret: string | null = null;
let expiresAt = 0;

function hasWebCryptoVault(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof indexedDB !== 'undefined' &&
    typeof crypto !== 'undefined' &&
    typeof crypto.subtle !== 'undefined'
  );
}

function openVaultDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error('Failed to open vault DB'));
  });
}

async function readVaultSecret(): Promise<string | null> {
  if (!hasWebCryptoVault()) return null;
  try {
    const db = await openVaultDb();
    const record = await new Promise<VaultRecord | undefined>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const req = tx.objectStore(STORE_NAME).get(RECORD_KEY);
      req.onsuccess = () => resolve(req.result as VaultRecord | undefined);
      req.onerror = () => reject(req.error);
    });
    db.close();
    if (!record?.key || !record?.iv || !record?.ciphertext) return null;
    const iv = new Uint8Array(record.iv);
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, record.key, record.ciphertext);
    return new TextDecoder().decode(plain) || null;
  } catch {
    return null;
  }
}

async function writeVaultSecret(secret: string): Promise<void> {
  if (!hasWebCryptoVault()) return;
  try {
    const key = await crypto.subtle.generateKey(
      { name: 'AES-GCM', length: 256 },
      false, // non-extractable CryptoKey — raw key bytes cannot be exported by JS
      ['encrypt', 'decrypt']
    );
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encoded = new TextEncoder().encode(secret);
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
    const db = await openVaultDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const req = tx.objectStore(STORE_NAME).put({ key, iv, ciphertext } satisfies VaultRecord, RECORD_KEY);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
    db.close();
  } catch {
    // Keep in-memory secret even if IndexedDB is blocked (e.g. private browsing)
  }
}

async function deleteVaultSecret(): Promise<void> {
  if (!hasWebCryptoVault()) return;
  try {
    const db = await openVaultDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const req = tx.objectStore(STORE_NAME).delete(RECORD_KEY);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
    db.close();
  } catch {
    // Ignore storage cleanup errors
  }
}

/**
 * WEB-04: Stores the operator secret in JS session memory and persists it encrypted on the device
 * using a non-extractable WebCrypto AES-GCM key in IndexedDB (never localStorage, sessionStorage,
 * cookies, or URLs).
 */
export async function getOperatorSecret(): Promise<string | null> {
  if (memorySecret && Date.now() <= expiresAt) {
    expiresAt = Date.now() + SESSION_TTL_MS;
    return memorySecret;
  }
  const restored = await readVaultSecret();
  if (restored) {
    memorySecret = restored;
    expiresAt = Date.now() + SESSION_TTL_MS;
    return restored;
  }
  memorySecret = null;
  expiresAt = 0;
  return null;
}

export async function setOperatorSecret(secret: string): Promise<void> {
  const trimmed = secret.trim();
  if (!trimmed) {
    await clearOperatorSecret();
    return;
  }
  memorySecret = trimmed;
  expiresAt = Date.now() + SESSION_TTL_MS;
  await writeVaultSecret(trimmed);
}

export async function clearOperatorSecret(): Promise<void> {
  memorySecret = null;
  expiresAt = 0;
  await deleteVaultSecret();
}
