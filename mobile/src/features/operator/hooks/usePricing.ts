import { useState, useEffect, useCallback } from 'react';
import * as Haptics from 'expo-haptics';
import { apiFetch } from '@/shared/lib/api';
import { getOperatorSecret } from '../lib/operatorSecret';

interface PricingRow {
  sport: string;
  price_ils: number;
}

export function usePricing() {
  const [rows, setRows] = useState<PricingRow[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { pricing } = await apiFetch<{ pricing: PricingRow[] }>('/api/pricing');
      setRows(pricing);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load pricing');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const writePrice = async (sport: string, priceIls: number) => {
    const secret = await getOperatorSecret();
    if (!secret) {
      setError('Operator secret not set. Add it in Operator settings.');
      throw new Error('missing operator secret');
    }
    await apiFetch('/api/pricing', {
      method: 'POST',
      headers: { 'x-operator-secret': secret },
      body: JSON.stringify({ sport: sport.trim().toLowerCase(), price_ils: priceIls }),
    });
  };

  const updatePrice = async (sport: string, priceIls: number) => {
    setSaving(sport);
    setError(null);
    try {
      await writePrice(sport, priceIls);
      setRows((prev) =>
        prev.map((r) => (r.sport === sport ? { ...r, price_ils: priceIls } : r))
      );
      await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(null);
    }
  };

  const addSport = async (sport: string, priceIls: number) => {
    setSaving(sport);
    setError(null);
    try {
      await writePrice(sport, priceIls);
      setRows((prev) => [...prev, { sport, price_ils: priceIls }]);
      await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Add failed');
    } finally {
      setSaving(null);
    }
  };

  return { rows, saving, error, updatePrice, addSport };
}
