import { NextRequest } from 'next/server';
import { timingSafeEqual } from 'crypto';

/**
 * Validates the `x-operator-secret` header against OPERATOR_SECRET using a
 * constant-time comparison (prevents timing attacks on the secret).
 *
 * Returns false when the header is missing, the secret is unset, lengths
 * differ, or the bytes don't match. Centralizes operator auth so every
 * privileged route (pricing, support, analytics) shares one implementation.
 */
export function requireOperator(req: NextRequest): boolean {
  const provided = req.headers.get('x-operator-secret') ?? '';
  const expected = process.env.OPERATOR_SECRET ?? '';

  // A missing/empty expected secret must never authorize a request.
  if (!expected) return false;

  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;

  try {
    return timingSafeEqual(a, b);
  } catch {
    return false;
  }
}
