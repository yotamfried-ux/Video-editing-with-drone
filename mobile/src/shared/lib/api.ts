const BASE = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'https://api.sportreel.app';

async function readFailureMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => '');
  if (!text) return res.statusText || 'Request failed';

  try {
    const parsed = JSON.parse(text) as Record<string, unknown>;
    const value = parsed.error ?? parsed.message;
    if (typeof value === 'string' && value.trim()) return value;
  } catch {
    // Non-JSON response body — fall back to the text below.
  }

  return text.slice(0, 500);
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const message = await readFailureMessage(res);
    throw new Error(`API ${res.status}: ${message}`);
  }
  return res.json() as Promise<T>;
}
