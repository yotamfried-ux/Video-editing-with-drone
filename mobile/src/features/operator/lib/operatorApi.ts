import { apiFetch } from '@/shared/lib/api';
import { getOperatorSecret } from './operatorSecret';

/**
 * Calls a web-api route that requires operator authorization, attaching the
 * `x-operator-secret` header from the device keychain. Throws if no secret has
 * been set yet (the operator must enter it once in the Pricing screen).
 */
export async function operatorFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const secret = await getOperatorSecret();
  if (!secret) throw new Error('Operator secret not set. Add it in Operator settings.');
  return apiFetch<T>(path, {
    ...options,
    headers: { 'x-operator-secret': secret, ...options?.headers },
  });
}
