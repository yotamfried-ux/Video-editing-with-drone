import { NextRequest } from 'next/server';
import { handlePaymentWebhook } from '@/lib/payments/webhook-handler';

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ provider: string }> },
) {
  const { provider } = await params;
  return handlePaymentWebhook(req, provider);
}
