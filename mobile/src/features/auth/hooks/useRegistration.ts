import { useState } from 'react';
import { supabase } from '@/shared/lib/supabase';
import * as ImagePicker from 'expo-image-picker';

type Step = 'credentials' | 'profile' | 'face';

export function useRegistration() {
  const [step, setStep] = useState<Step>('credentials');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    setUserId(data.user?.id ?? null);
    setLoading(false);
    setStep('profile');
  };

  const submitProfile = async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    const { error: e } = await supabase.from('athlete_profiles').upsert({
      user_id: userId,
      email,
      name,
    });
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
