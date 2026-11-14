import { NextRequest } from 'next/server';
import { handlePaymentWebhook } from '@/lib/payments/webhook-handler';

// Historical URL registered in the Stripe dashboard. Other providers use /api/payments/webhook/<provider>.
export async function POST(req: NextRequest) {
  return handlePaymentWebhook(req, 'stripe');
}
