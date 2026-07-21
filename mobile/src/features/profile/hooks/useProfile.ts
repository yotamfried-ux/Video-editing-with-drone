import { useState, useEffect } from 'react';
import { supabase } from '@/shared/lib/supabase';

interface Profile {
  id: string;
  name: string | null;
  email: string;
  push_token: string | null;
}

export function useProfile() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setLoading(false);
        return;
      }
      const { data } = await supabase
        .from('athlete_profiles')
        .select('id, name, email, push_token')
        .eq('user_id', user.id)
        .single();
      setProfile(data);
      setLoading(false);
    };
    load();
  }, []);

  const updateName = async (name: string) => {
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return;
    await supabase
      .from('athlete_profiles')
      .update({ name })
      .eq('user_id', user.id);
    setProfile((prev) => (prev ? { ...prev, name } : prev));
  };

  return { profile, loading, updateName };
}
