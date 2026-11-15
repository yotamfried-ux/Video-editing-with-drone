import { notFound } from 'next/navigation';
import { PRIVACY_POLICY, TERMS_OF_SERVICE } from '@/content/legal.generated';

const DOCS: Record<string, { title: string; text: string }> = {
  privacy: { title: 'Privacy Policy', text: PRIVACY_POLICY },
  terms: { title: 'Terms of Service', text: TERMS_OF_SERVICE },
};

export function generateStaticParams() {
  return Object.keys(DOCS).map((doc) => ({ doc }));
}

export const dynamicParams = false;

export async function generateMetadata({ params }: { params: Promise<{ doc: string }> }) {
  const { doc } = await params;
  return { title: `SportReel — ${DOCS[doc]?.title ?? 'Legal'}` };
}

// Public URLs the App Store and Google Play listings link to. Same text as the in-app screens.
export default async function LegalPage({ params }: { params: Promise<{ doc: string }> }) {
  const { doc } = await params;
  const entry = DOCS[doc];
  if (!entry) notFound();
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 760, margin: '0 auto' }}>
      <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', lineHeight: 1.5 }}>{entry.text}</pre>
    </main>
  );
}
