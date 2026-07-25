import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';

function normalizeMajorIls(value: unknown): number | null {
  const amount = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(amount) || amount <= 0 || amount > 100_000) return null;
  const rounded = Math.round(amount * 100) / 100;
  return Number.isFinite(rounded) ? rounded : null;
}

// GET /api/pricing — public list of human-readable ILS prices.
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

// POST /api/pricing — operator-only major-unit ILS upsert.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'pricing-write', 20, 60);
  if (limited) return limited;

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 });
  }

  const sport = typeof body.sport === 'string' ? body.sport.trim().toLowerCase() : '';
  const priceIls = normalizeMajorIls(body.price_ils);
  if (!sport) {
    return NextResponse.json({ error: 'sport required' }, { status: 400 });
  }
  if (priceIls === null) {
    return NextResponse.json(
      { error: 'price_ils must be a positive ILS amount, for example 79 or 79.90' },
      { status: 400 },
    );
  }

  const { error } = await supabaseAdmin
    .from('pricing')
    .upsert({ sport, price_ils: priceIls, updated_at: new Date().toISOString() });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
  return NextResponse.json({ ok: true, sport, price_ils: priceIls });
}
