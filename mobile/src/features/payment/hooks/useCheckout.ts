import { useState } from 'react';
import { apiFetch } from '@/shared/lib/api';

interface StripeCheckout {
  checkout_url: string;
  session_id: string;
  purchase_id: string;
  amount_ils: number;
  currency: string;
}

export function useCheckout(reelToken: string) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createStripeCheckout = async (): Promise<StripeCheckout | null> => {
    setLoading(true);
    setError(null);
    try {
      return await apiFetch<StripeCheckout>(`/api/checkout/${reelToken}`, {
        method: 'POST',
      });
    } catch (e: any) {
      setError(e.message);
      return null;
    } finally {
      setLoading(false);
    }
  };

  return { createStripeCheckout, loading, error };
}
