import { useState } from 'react';
import { apiFetch } from '@/shared/lib/api';
import { useAuthStore } from '@/shared/hooks/useAuth';

interface StripeCheckout {
  clientSecret: string;
  amount_ils: number;
  download_token: string;
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
      return await apiFetch<StripeCheckout>('/api/checkout/stripe', {
        method: 'POST',
        body: JSON.stringify({ reel_id: reelId, email: payerEmail }),
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
