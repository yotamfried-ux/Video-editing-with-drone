import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { createUploadSession } from '@/lib/google-drive';

// POST /api/operator/upload — initiates a resumable Google Drive upload.
// Returns { uploadUrl, filename } so the mobile app can stream the file
// directly to Drive without passing through Vercel (no body-size limit).
//
// Flow:
//   1. Mobile calls this endpoint to get an uploadUrl
//   2. Mobile PUTs the video bytes directly to uploadUrl (Drive API)
//   3. Mobile calls POST /api/operator/pipeline/run to start processing
//
// Body: { filename?: string, mimeType?: string }
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'operator-upload', 10, 3600);
  if (limited) return limited;

  const rawFolder = process.env.RAW_FOLDER_ID;
  if (!rawFolder) {
    return NextResponse.json({ error: 'RAW_FOLDER_ID not configured' }, { status: 503 });
  }

  let body: { filename?: string; mimeType?: string } = {};
  try {
    body = await req.json();
  } catch {
    // filename optional — we'll generate one
  }

  const now = new Date();
  const stamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const filename = (body.filename ?? '').trim() || `footage_${stamp}.mp4`;
  const mimeType = (body.mimeType ?? '').trim() || 'video/mp4';

  try {
    const uploadUrl = await createUploadSession(filename, rawFolder, mimeType);
    return NextResponse.json({ uploadUrl, filename });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Upload init failed' },
      { status: 502 },
    );
  }
}
