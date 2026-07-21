import { useEffect, useState } from 'react';
import { supabase } from '@/shared/lib/supabase';

type Step = 'credentials' | 'profile' | 'done';

export function useRegistration(initialStep: Step = 'credentials') {
  const [step, setStep] = useState<Step>(initialStep);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  }, [initialStep]);

  const submitCredentials = async () => {
    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }
    setLoading(true);
    setError(null);
    const { data, error: signUpError } = await supabase.auth.signUp({ email, password });
    if (signUpError) {
      setError(signUpError.message);
      setLoading(false);
      return;
    }
    if (!data.session) {
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
    const { error: profileError } = await supabase
      .from('athlete_profiles')
      .update({ name: name.trim() })
      .eq('user_id', userId);
    if (profileError) {
      setError(profileError.message);
      setLoading(false);
      return;
    }
    setLoading(false);
    setStep('done');
  };

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
  };
}
