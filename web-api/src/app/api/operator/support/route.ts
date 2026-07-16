import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';
import type { OperatorSuggestion, OperatorSupportResponse, OperatorSupportTicket } from '@/types/operator-contracts';

// GET /api/operator/support — operator-only list of all support tickets +
// suggestions. RLS restricts these tables to each user's own rows (and
// service_role), so the operator dashboard must read them server-side.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const [tickets, suggestions] = await Promise.all([
    supabaseAdmin
      .from('support_tickets')
      .select('id, message, status, operator_reply, created_at')
      .order('created_at', { ascending: false }),
    supabaseAdmin
      .from('suggestions')
      .select('id, message, created_at')
      .order('created_at', { ascending: false }),
  ]);

  return NextResponse.json<OperatorSupportResponse>({
    tickets: (tickets.data ?? []) as OperatorSupportTicket[],
    suggestions: (suggestions.data ?? []) as OperatorSuggestion[],
  });
}
