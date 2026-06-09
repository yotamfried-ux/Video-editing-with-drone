import { supabaseAdmin } from './supabase-admin';

export async function getPriceForReel(reelId: string): Promise<number> {
  // Get reel sport
  const { data: reel } = await supabaseAdmin
    .from('reels')
    .select('sport')
    .eq('id', reelId)
    .single();

  if (!reel) throw new Error('Reel not found');

  // Try sport-specific price, fall back to 'default'
  const { data: price } = await supabaseAdmin
    .from('pricing')
    .select('price_ils')
    .eq('sport', reel.sport)
    .maybeSingle();

  if (price) return price.price_ils;

  const { data: defaultPrice } = await supabaseAdmin
    .from('pricing')
    .select('price_ils')
    .eq('sport', 'default')
    .single();

  return defaultPrice?.price_ils ?? 2900;
}
