import { useCallback, useState } from 'react';
import { Linking } from 'react-native';
import { type CheckoutSession, createCheckout, isSafeCheckoutUrl } from '../lib/checkout';

/**
 * One purchase attempt for one reel. The first call creates the checkout on the server; later calls reopen
 * the same hosted page instead of creating another purchase row.
 */
export function useCheckout(reelToken: string | undefined) {
  const [checkout, setCheckout] = useState<CheckoutSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async () => {
    if (!reelToken || loading) return;
    setLoading(true);
    setError(null);
    try {
      const session = checkout ?? (await createCheckout(reelToken));
      setCheckout(session);
      if (!isSafeCheckoutUrl(session.checkout_url)) {
        throw new Error('The payment page is not available. Please try again.');
      }
      await Linking.openURL(session.checkout_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start checkout');
    } finally {
      setLoading(false);
    }
  }, [reelToken, loading, checkout]);

  return { checkout, loading, error, start };
}
