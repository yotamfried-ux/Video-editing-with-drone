import crypto from 'crypto';

const API_BASE = 'https://sandbox.meshulam.co.il/api/v1'; // change to production URL when ready

export interface MeshulamPaymentLink {
  paymentUrl: string;
  transactionId: string;
}

export async function createMeshulamPayment(
  amountIls: number,
  reelId: string,
  successUrl: string,
  failUrl: string,
): Promise<MeshulamPaymentLink> {
  const params = {
    apiKey: process.env.MESHULAM_API_KEY!,
    amount: (amountIls / 100).toFixed(2), // agorot → ILS
    description: `SportReel clip purchase`,
    successUrl,
    failUrl,
    userId: reelId,
  };

  const resp = await fetch(`${API_BASE}/pay/createPayLink`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  if (!resp.ok) throw new Error(`Meshulam API error: ${resp.status}`);
  const data = await resp.json();
  return {
    paymentUrl: data.data?.payLink ?? '',
    transactionId: data.data?.transactionId ?? '',
  };
}

export function verifyMeshulamWebhook(body: Record<string, string>, secret: string): boolean {
  const { signature, ...rest } = body;
  const sorted = Object.keys(rest)
    .sort()
    .map((k) => `${k}=${rest[k]}`)
    .join('&');
  const expected = crypto
    .createHmac('sha256', secret)
    .update(sorted)
    .digest('hex');
  return signature === expected;
}
