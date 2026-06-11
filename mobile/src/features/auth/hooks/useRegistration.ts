import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';
import * as ImagePicker from 'expo-image-picker';

type Step = 'credentials' | 'profile' | 'face';

export function useRegistration(initialStep: Step = 'credentials') {
  const [step, setStep] = useState<Step>(initialStep);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Resuming mid-flow (e.g. login routed here because the profile has no
  // name yet) — hydrate userId from the stored session instead of signUp.
  useEffect(() => {
    if (initialStep === 'credentials') return;
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        setUserId(session.user.id);
        setEmail(session.user.email ?? '');
      } else {
        setStep('credentials');
      }
    });
  }, []);

  const submitCredentials = async () => {
    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }
    setLoading(true);
    setError(null);
    const { data, error: e } = await supabase.auth.signUp({ email, password });
    if (e) {
      setError(e.message);
      setLoading(false);
      return;
    }
    if (!data.session) {
      // Supabase has email confirmation enabled — user must confirm before continuing.
      setError('Check your email and click the confirmation link, then open the app again.');
      setLoading(false);
      return;
    }
    setUserId(data.user?.id ?? null);
    setLoading(false);
    setStep('profile');
  };

  const submitProfile = async () => {
    if (!userId) return;
    if (!name.trim()) {
      setError('Please enter your name');
      return;
    }
    setLoading(true);
    setError(null);
    // The DB trigger already inserted the row on signup; we only need to set name.
    const { error: e } = await supabase
      .from('athlete_profiles')
      .update({ name: name.trim() })
      .eq('user_id', userId);
    if (e) {
      setError(e.message);
      setLoading(false);
      return;
    }
    setLoading(false);
    setStep('face');
  };

  const uploadFacePhoto = async (uri: string) => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(uri);
      const blob = await response.arrayBuffer();
      const path = `${userId}/photo.jpg`;
      const { error: upErr } = await supabase.storage
        .from('athlete_photos')
        .upload(path, blob, { contentType: 'image/jpeg', upsert: true });
      if (upErr) throw upErr;
      await supabase
        .from('athlete_profiles')
        .update({ photo_path: path })
        .eq('user_id', userId);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const skipFace = () => {};

  return {
    step,
    email,
    setEmail,
    password,
    setPassword,
    name,
    setName,
    loading,
    error,
    submitCredentials,
    submitProfile,
    uploadFacePhoto,
    skipFace,
  };
}
