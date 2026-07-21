import { useState } from 'react';
import { apiFetch } from '@/shared/lib/api';
import { useAuthStore } from '@/shared/hooks/useAuth';
import { getOrCreateCheckoutSessionId } from '@/features/payment/downloadTokenStore';

export interface StripeCheckout {
  clientSecret: string;
  payment_intent_id: string;
  amount_ils: number;
  download_token: string;
}

interface MeshulamCheckout {
  paymentUrl: string;
  transaction_id: string;
  download_token: string;
  amount_ils: number;
}

export function useCheckout(reelId: string) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const payerEmail = useAuthStore((state) => state.user?.email?.trim().toLowerCase() ?? '');

  const createStripeCheckout = async (): Promise<StripeCheckout | null> => {
    setLoading(true);
    setError(null);
    try {
      if (!payerEmail) {
        throw new Error('Sign in with an email address before paying by card.');
      }
      const checkoutSessionId = await getOrCreateCheckoutSessionId(reelId, payerEmail);
      return await apiFetch<StripeCheckout>('/api/checkout/stripe', {
        method: 'POST',
        body: JSON.stringify({
          reel_id: reelId,
          email: payerEmail,
          checkout_session_id: checkoutSessionId,
        }),
      });
    } catch (checkoutError) {
      setError(checkoutError instanceof Error ? checkoutError.message : 'Checkout failed');
      return null;
    } finally {
      setLoading(false);
    }
  };

  const createMeshulamCheckout = async (): Promise<MeshulamCheckout | null> => {
    setLoading(true);
    setError(null);
    try {
      return await apiFetch<MeshulamCheckout>('/api/checkout/meshulam', {
        method: 'POST',
        body: JSON.stringify({ reel_id: reelId }),
      });
    } catch (checkoutError) {
      setError(checkoutError instanceof Error ? checkoutError.message : 'Checkout failed');
      return null;
    } finally {
      setLoading(false);
    }
  };

  return {
    createStripeCheckout,
    createMeshulamCheckout,
    payerEmail,
    loading,
    error,
  };
}
