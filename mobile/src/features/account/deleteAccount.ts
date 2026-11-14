import { apiFetch } from '@/shared/lib/api';
import { supabase } from '@/shared/lib/supabase';

/**
 * Permanently delete the signed-in account (App Store 5.1.1(v), Google Play account deletion).
 * The server identifies the account from the caller's own access token.
 */
export async function deleteAccount(): Promise<void> {
  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token;
  if (!accessToken) throw new Error('Please sign in again to delete your account.');
  await apiFetch<{ deleted: boolean }>('/api/account', {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  // The account no longer exists server-side; drop the local session without calling the server again.
  await supabase.auth.signOut({ scope: 'local' }).catch(() => {});
}
