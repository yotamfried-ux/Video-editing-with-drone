import { useState, useEffect } from 'react';
import { supabase } from '@/shared/lib/supabase';
import * as Haptics from 'expo-haptics';

interface PricingRow {
  sport: string;
  price_ils: number;
}

export function usePricing() {
  const [rows, setRows] = useState<PricingRow[]>([]);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    supabase
      .from('pricing')
      .select('sport, price_ils')
      .then(({ data }) => {
        if (data) setRows(data);
      });
  }, []);

  const updatePrice = async (sport: string, priceIls: number) => {
    setSaving(sport);
    await supabase
      .from('pricing')
      .upsert({ sport, price_ils: priceIls });
    setRows((prev) =>
      prev.map((r) =>
        r.sport === sport ? { ...r, price_ils: priceIls } : r
      )
    );
    await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setSaving(null);
  };

  const addSport = async (sport: string, priceIls: number) => {
    await supabase.from('pricing').insert({ sport, price_ils: priceIls });
    setRows((prev) => [...prev, { sport, price_ils: priceIls }]);
  };

  return { rows, saving, updatePrice, addSport };
}
