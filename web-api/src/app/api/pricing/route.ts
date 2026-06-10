import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';

// GET /api/pricing — public list of sport prices (read-only, safe to expose)
export async function GET() {
  const { data, error } = await supabaseAdmin
    .from('pricing')
    .select('sport, price_ils')
    .order('sport');

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ pricing: data ?? [] });
}

// POST /api/pricing — operator-only upsert, protected by x-operator-secret header
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { sport, price_ils } = await req.json();
  if (typeof sport !== 'string' || !sport.trim()) {
    return NextResponse.json({ error: 'sport required' }, { status: 400 });
  }
  if (!Number.isInteger(price_ils) || price_ils < 0) {
    return NextResponse.json({ error: 'price_ils must be a non-negative integer (agorot)' }, { status: 400 });
  }

  const { error } = await supabaseAdmin
    .from('pricing')
    .upsert({ sport: sport.trim().toLowerCase(), price_ils, updated_at: new Date().toISOString() });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true });
}
