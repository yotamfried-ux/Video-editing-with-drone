import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';

/**
 * Delete the caller's own account (App Store guideline 5.1.1(v), Google Play account-deletion policy).
 *
 * The caller proves who they are with their own Supabase access token; the id to delete is read from the
 * verified token, never from the request. Deleting the auth user cascades to athlete_profiles and
 * push_tokens and detaches support tickets and suggestions (ON DELETE SET NULL). Purchase records carry no
 * user id and are kept as financial records.
 */
export async function DELETE(req: NextRequest) {
  const limited = await enforceRateLimit(req, 'account-delete', 5, 60);
  if (limited) return limited;

  const header = req.headers.get('authorization') ?? '';
  const token = header.toLowerCase().startsWith('bearer ') ? header.slice(7).trim() : '';
  if (!token) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { data, error } = await supabaseAdmin.auth.getUser(token);
  const userId = data?.user?.id;
  if (error || !userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { error: deleteError } = await supabaseAdmin.auth.admin.deleteUser(userId);
  if (deleteError) {
    return NextResponse.json({ error: 'Could not delete account' }, { status: 500 });
  }
  return NextResponse.json({ deleted: true });
}
