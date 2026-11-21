'use client';

import { useState, type FormEvent } from 'react';
import { createClient } from '@supabase/supabase-js';

export function AccountDeletionForm({
  supabaseUrl,
  publishableKey,
}: {
  supabaseUrl: string;
  publishableKey: string;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !acknowledged) return;
    setBusy(true);
    setError(null);
    // Ephemeral browser client: do not persist tokens or refresh sessions.
    const supabase = createClient(supabaseUrl, publishableKey, {
      auth: {
        persistSession: false,
        autoRefreshToken: false,
        detectSessionInUrl: false,
      },
    });
    try {
      const { data, error: authError } = await supabase.auth.signInWithPassword({
        email: email.trim().toLowerCase(),
        password,
      });
      if (authError || !data.session?.access_token) {
        throw new Error('Could not verify your credentials.');
      }
      // Account id is derived by the API from the verified access token,
      // never accepted from an untrusted web form.
      const response = await fetch('/api/account', {
        method: 'DELETE',
        cache: 'no-store',
        headers: { Authorization: `Bearer ${data.session.access_token}` },
      });
      if (!response.ok) {
        throw new Error('Could not delete your account. Please try again later.');
      }
      const result: { deleted?: boolean } = await response.json();
      if (!result.deleted) throw new Error('Account deletion could not be confirmed.');
      setDeleted(true);
      setPassword('');
      setEmail('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Deletion failed.');
    } finally {
      await supabase.auth.signOut({ scope: 'local' }).catch(() => {});
      setBusy(false);
    }
  }

  if (deleted) {
    return <p role="status">Your SportReel account has been deleted.</p>;
  }

  const inputStyle = {
    width: '100%', boxSizing: 'border-box' as const, padding: '12px',
    borderRadius: 8, border: '1px solid #8590b4', background: '#fff',
    color: '#101828', fontSize: '1rem',
  };

  return (
    <form onSubmit={submit} style={{ display: 'grid', gap: 16 }}>
      <label htmlFor="delete-email">
        Account email
        <input id="delete-email" type="email" name="email"
          autoComplete="email" required maxLength={254}
          value={email} onChange={(e) => setEmail(e.target.value)}
          style={inputStyle} />
      </label>
      <label htmlFor="delete-password">
        Password
        <input id="delete-password" type="password" name="password"
          autoComplete="current-password" required
          value={password} onChange={(e) => setPassword(e.target.value)}
          style={inputStyle} />
      </label>
      <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <input type="checkbox" required checked={acknowledged}
          onChange={(e) => setAcknowledged(e.target.checked)} />
        I understand this account deletion is permanent.
      </label>
      {error ? <p role="alert" style={{ color: '#ffb8b8' }}>{error}</p> : null}
      <button type="submit" disabled={busy || !acknowledged}
        style={{
          padding: '14px', borderRadius: 8,
          background: '#b42318', color: 'white',
          border: 0, cursor: 'pointer', fontWeight: 700,
        }}>
        {busy ? 'Deleting account…' : 'Permanently delete my account'}
      </button>
    </form>
  );
}
