'use client';

import { useEffect, useState } from 'react';

export default function CheckoutSuccessPage() {
  const [message, setMessage] = useState('Verifying payment…');
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const sessionId = query.get('session_id');
    if (!sessionId) { setMessage('Missing checkout session.'); return; }
    const provider = query.get('provider');
    const providerQuery = provider ? `&provider=${encodeURIComponent(provider)}` : '';
    fetch(`/api/checkout/session?session_id=${encodeURIComponent(sessionId)}${providerQuery}`)
      .then(async (res) => ({ ok: res.ok, body: await res.json() }))
      .then(({ ok, body }) => {
        if (!ok) throw new Error(body.error || 'Could not verify payment');
        if (body.delivery_ready && body.download_url) {
          setMessage('Payment confirmed. Your reel is ready.');
          setDownloadUrl(body.download_url);
        } else if (body.paid) setMessage('Payment confirmed. Preparing your reel…');
        else setMessage('Payment is still being confirmed. Refresh shortly.');
      })
      .catch((err) => setMessage(err instanceof Error ? err.message : 'Could not verify payment'));
  }, []);

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: 24, maxWidth: 560 }}>
      <h1>SportReel</h1><p>{message}</p>
      {downloadUrl && <p><a href={downloadUrl}>Download reel</a></p>}
      <p><a href="sportreel://">Back to the SportReel app</a></p>
    </main>
  );
}
