import { NextRequest } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';

/**
 * The signed-in app user behind a request, from their own Supabase access token
 * (`Authorization: Bearer <token>`). Returns null for a missing or invalid token.
 */
export async function userIdFromRequest(req: NextRequest): Promise<string | null> {
  const header = req.headers.get('authorization') ?? '';
  const token = header.toLowerCase().startsWith('bearer ') ? header.slice(7).trim() : '';
  if (!token) return null;
  try {
    const { data, error } = await supabaseAdmin.auth.getUser(token);
    return error ? null : data?.user?.id ?? null;
  } catch {
    return null;
  }
}
