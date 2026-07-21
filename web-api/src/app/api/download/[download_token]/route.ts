import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { enforceRateLimit } from '@/lib/ratelimit';
import { isUuid } from '@/lib/validate';

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ download_token: string }> },
) {
  const limited = await enforceRateLimit(req, 'download', 30, 60);
  if (limited) return limited;

  const { download_token: downloadToken } = await params;
  if (!isUuid(downloadToken)) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  const { data: payment, error: paymentError } = await supabaseAdmin
    .from('payments')
    .select('id, reel_id, status, reels(storage_path)')
    .eq('download_token', downloadToken)
    .maybeSingle();

  if (paymentError) {
    return NextResponse.json({ error: 'Download authorization unavailable' }, { status: 503 });
  }
  if (!payment) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (payment.status !== 'completed') {
    return NextResponse.json({ error: 'Payment not completed' }, { status: 403 });
  }

  const reel = (payment.reels as unknown) as
    | { storage_path: string | null }
    | { storage_path: string | null }[]
    | null;
  const storagePath = Array.isArray(reel) ? reel[0]?.storage_path : reel?.storage_path;
  if (!storagePath) return NextResponse.json({ error: 'File not available' }, { status: 404 });

  const { data: signed, error: signedError } = await supabaseAdmin.storage
    .from('reels')
    .createSignedUrl(storagePath, 900);

  if (signedError || !signed?.signedUrl) {
    return NextResponse.json({ error: 'Could not generate download URL' }, { status: 500 });
  }

  const { error: analyticsError } = await supabaseAdmin
    .from('analytics_events')
    .upsert({
      event_type: 'download_completed',
      reel_id: payment.reel_id,
      payment_id: payment.id,
    }, {
      onConflict: 'payment_id,event_type',
      ignoreDuplicates: true,
    });
  if (analyticsError) {
    console.warn('download_completed analytics upsert failed', analyticsError.message);
  }

  return NextResponse.json({ downloadUrl: signed.signedUrl, expires_in_seconds: 900 });
}
