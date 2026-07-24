import { supabaseAdmin } from './supabase-admin';

const DEFAULT_PRICE_ILS = 29;

/**
 * Stripe requires integer amounts in the currency's smallest unit. The pricing
 * table is operator-facing and stores human-readable ILS values (for example
 * 79 means ₪79), so conversion to agorot happens exactly once at this server
 * boundary.
 */
export function ilsToMinorUnits(value: unknown): number {
  const majorUnits = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(majorUnits) || majorUnits <= 0) {
    throw new Error('Configured reel price must be a positive ILS amount');
  }

  const minorUnits = Math.round(majorUnits * 100);
  if (!Number.isSafeInteger(minorUnits) || minorUnits < 50) {
    throw new Error('Configured reel price is outside the supported Stripe range');
  }
  return minorUnits;
}

export async function getPriceForReel(reelId: string): Promise<number> {
  const { data: reel, error: reelError } = await supabaseAdmin
    .from('reels')
    .select('sport')
    .eq('id', reelId)
    .single();

  if (reelError || !reel) throw new Error('Reel not found');

  const { data: price, error: priceError } = await supabaseAdmin
    .from('pricing')
    .select('price_ils')
    .eq('sport', reel.sport)
    .maybeSingle();
  if (priceError) throw new Error(`Pricing lookup failed: ${priceError.message}`);
  if (price) return ilsToMinorUnits(price.price_ils);

  const { data: defaultPrice, error: defaultError } = await supabaseAdmin
    .from('pricing')
    .select('price_ils')
    .eq('sport', 'default')
    .maybeSingle();
  if (defaultError) throw new Error(`Default pricing lookup failed: ${defaultError.message}`);

  return ilsToMinorUnits(defaultPrice?.price_ils ?? DEFAULT_PRICE_ILS);
}
