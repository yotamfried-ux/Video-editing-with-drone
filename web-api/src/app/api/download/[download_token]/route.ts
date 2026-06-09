import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ download_token: string }> }
) {
  const { download_token } = await params;

  const { data: payment } = await supabaseAdmin
    .from('payments')
    .select('id, reel_id, status, reels(storage_path)')
    .eq('download_token', download_token)
    .single();

  if (!payment) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  if (payment.status !== 'completed') {
    return NextResponse.json({ error: 'Payment not completed' }, { status: 403 });
  }

  const storagePath = (payment.reels as { storage_path: string } | null)?.storage_path;
  if (!storagePath) return NextResponse.json({ error: 'File not available' }, { status: 404 });

  const { data: signed } = await supabaseAdmin.storage
    .from('reels')
    .createSignedUrl(storagePath, 86400); // 24 hours

  if (!signed?.signedUrl) {
    return NextResponse.json({ error: 'Could not generate download URL' }, { status: 500 });
  }

  await supabaseAdmin.from('analytics_events').insert({
    event_type: 'download_completed',
    reel_id: payment.reel_id,
    payment_id: payment.id,
  });

  return NextResponse.json({ downloadUrl: signed.signedUrl });
}
