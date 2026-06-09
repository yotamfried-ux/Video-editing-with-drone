import { useState } from 'react';
import { apiFetch } from '@/shared/lib/api';

interface StripeCheckout {
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

export function useCheckout(reelId: string) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createStripeCheckout = async (): Promise<StripeCheckout | null> => {
    setLoading(true);
    setError(null);
    try {
      return await apiFetch<StripeCheckout>('/api/checkout/stripe', {
        method: 'POST',
        body: JSON.stringify({ reel_id: reelId }),
      });
    } catch (e: any) {
      setError(e.message);
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
    } catch (e: any) {
      setError(e.message);
      return null;
    } finally {
      setLoading(false);
    }
  };

  return { createStripeCheckout, createMeshulamCheckout, loading, error };
}
