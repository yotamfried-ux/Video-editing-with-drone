import { AccountDeletionForm } from './AccountDeletionForm';

export const metadata = {
  title: 'SportReel — Delete your account',
  description: 'Request deletion of your SportReel account and associated personal data.',
};

// These are public Supabase client credentials, never the service-role secret.
// Values should match the Expo client and may be overridden at deploy time.
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL
  || 'https://bcndgmymnismbxvdeetc.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  || 'sb_publishable_mwAM5lvgulv3sCtrHm-OkA_4wMCpNZJ';

export default function AccountDeletionPage() {
  return (
    <main style={{
      fontFamily: 'system-ui, sans-serif', maxWidth: 600, padding: 24,
      margin: '32px auto', lineHeight: 1.6, color: '#e7eaf2',
      backgroundColor: '#0a0e1a', borderRadius: 16,
    }}>
      <h1>Delete your SportReel account</h1>
      <p>
        You can delete your SportReel account in the mobile app under
        Profile &gt; Delete Account, or use this secure web form.
      </p>
      <p>
        Deletion removes your account and associated profile and notification
        settings. Certain purchase and transaction records may be retained
        where necessary to comply with accounting and legal requirements.
        Deleting an account does not necessarily remove footage in which a
        person appears. For other privacy requests, use the support options
        in the app.
      </p>
      <p>
        Sign in below to verify that this is your own account. We never request
        an administrator or operator password.
      </p>
      <AccountDeletionForm
        supabaseUrl={SUPABASE_URL}
        publishableKey={SUPABASE_PUBLISHABLE_KEY}
      />
      <p>
        <a href="/legal/privacy" style={{ color: '#99a7ff' }}>Privacy Policy</a>
      </p>
    </main>
  );
}
