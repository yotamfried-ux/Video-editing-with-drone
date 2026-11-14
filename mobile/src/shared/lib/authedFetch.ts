import { apiFetch, type ApiFetchOptions } from './api';
import { supabase } from './supabase';

/** The signed-in user's access token, or null when signed out. */
export async function accessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** apiFetch with the user's own token. Throws when nobody is signed in. */
export async function authedFetch<T>(path: string, options?: ApiFetchOptions): Promise<T> {
  const token = await accessToken();
  if (!token) throw new Error('Please sign in first.');
  return apiFetch<T>(path, { ...options, headers: { ...options?.headers, Authorization: `Bearer ${token}` } });
}
