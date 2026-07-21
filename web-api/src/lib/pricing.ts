import { supabaseAdmin } from './supabase-admin';

const DEFAULT_PRICE_ILS = 29;
export const PRICING_UNIT = 'major_ils_v1';

type PricingRow = {
  price_ils: number | string;
  price_unit: string | null;
};

export class CheckoutEligibilityError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'CheckoutEligibilityError';
    this.status = status;
  }
}

/**
 * Stripe and the persisted payment rows use integer minor units (agorot).
 * Operator pricing uses human-readable major ILS and carries an explicit unit
 * version so an old 7900-agorot row can never silently become a ₪7,900 charge.
 */
export function ilsToMinorUnits(value: unknown): number {
  const majorUnits = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(majorUnits) || majorUnits <= 0) {
    throw new Error('Configured reel price must be a positive ILS amount');
  }

  const minorUnits = Math.round(majorUnits * 100);
  if (!Number.isSafeInteger(minorUnits) || minorUnits < 50) {
    throw new Error('Configured reel price is outside the supported payment range');
  }
  return minorUnits;
}

export function minorUnitsToIls(value: unknown): number {
  const minorUnits = typeof value === 'number' ? value : Number(value);
  if (!Number.isSafeInteger(minorUnits) || minorUnits <= 0) {
    throw new Error('Payment amount must be a positive integer number of agorot');
  }
  return minorUnits / 100;
}

function pricingRowToMinorUnits(row: PricingRow): number {
  if (row.price_unit !== PRICING_UNIT) {
    throw new Error(
      `Pricing row has unsupported or missing unit ${String(row.price_unit)}; apply the pricing-unit migration before checkout`,
    );
  }
  return ilsToMinorUnits(row.price_ils);
}

export async function getPriceForReel(reelId: string): Promise<number> {
  const { data: reel, error: reelError } = await supabaseAdmin
    .from('reels')
    .select('sport, status, expires_at, storage_path')
    .eq('id', reelId)
    .single();

  if (reelError || !reel) throw new CheckoutEligibilityError('Reel not found', 404);
  if (reel.status === 'sold') {
    throw new CheckoutEligibilityError('This clip was already sold', 409);
  }
  if (reel.status === 'expired' || !reel.expires_at || new Date(reel.expires_at) < new Date()) {
    throw new CheckoutEligibilityError('This clip has expired', 410);
  }
  if (!reel.storage_path) {
    throw new CheckoutEligibilityError('File not available', 404);
  }

  const { data: price, error: priceError } = await supabaseAdmin
    .from('pricing')
    .select('price_ils, price_unit')
    .eq('sport', reel.sport)
    .maybeSingle();
  if (priceError) throw new Error(`Pricing lookup failed: ${priceError.message}`);
  if (price) return pricingRowToMinorUnits(price as PricingRow);

  const { data: defaultPrice, error: defaultError } = await supabaseAdmin
    .from('pricing')
    .select('price_ils, price_unit')
    .eq('sport', 'default')
    .maybeSingle();
  if (defaultError) throw new Error(`Default pricing lookup failed: ${defaultError.message}`);

  return defaultPrice
    ? pricingRowToMinorUnits(defaultPrice as PricingRow)
    : ilsToMinorUnits(DEFAULT_PRICE_ILS);
}
