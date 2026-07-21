import { useRef, useState } from 'react';
import { apiFetch } from '@/shared/lib/api';
import { useAuthStore } from '@/shared/hooks/useAuth';

export interface StripeCheckout {
  clientSecret: string;
  amount_ils: number;
  download_token: string;
}

interface MeshulamCheckout {
  paymentUrl: string;
  transaction_id: string;
  download_token: string;
  amount_ils: number;
}

function newCheckoutSessionId(reelId: string): string {
  const reelPrefix = reelId.replace(/[^A-Za-z0-9]/g, '').slice(0, 12);
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 14);
  return `checkout_${reelPrefix}_${timestamp}_${random}`;
}

export function useCheckout(reelId: string) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const payerEmail = useAuthStore((state) => state.user?.email?.trim().toLowerCase() ?? '');
  const checkoutSessionId = useRef(newCheckoutSessionId(reelId));

  const createStripeCheckout = async (): Promise<StripeCheckout | null> => {
    setLoading(true);
    setError(null);
    try {
      if (!payerEmail) {
        throw new Error('Sign in with an email address before paying by card.');
      }
      return await apiFetch<StripeCheckout>('/api/checkout/stripe', {
        method: 'POST',
        body: JSON.stringify({
          reel_id: reelId,
          email: payerEmail,
          checkout_session_id: checkoutSessionId.current,
        }),
      });
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Checkout failed');
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
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Checkout failed');
      return null;
    } finally {
      setLoading(false);
    }
  };

  return { createStripeCheckout, createMeshulamCheckout, loading, error };
}
