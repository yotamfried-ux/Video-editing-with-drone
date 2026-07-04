import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { createUploadSession } from '@/lib/google-drive';
import { createR2UploadUrl, shouldUseR2Storage } from '@/lib/r2-storage';

// POST /api/operator/upload — initiates a direct-to-storage upload.
// R2 is used when STORAGE_BACKEND=r2 or R2 credentials are configured.
// Drive remains available as a backwards-compatible fallback.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'operator-upload', 10, 3600);
  if (limited) return limited;

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
    if (shouldUseR2Storage()) {
      const upload = createR2UploadUrl(filename, mimeType);
      return NextResponse.json({
        uploadUrl: upload.uploadUrl,
        filename: upload.filename,
        storage_backend: 'r2',
        storage_key: upload.key,
      });
    }

    const rawFolder = process.env.RAW_FOLDER_ID;
    if (!rawFolder) {
      return NextResponse.json({ error: 'RAW_FOLDER_ID not configured' }, { status: 503 });
    }
    const uploadUrl = await createUploadSession(filename, rawFolder, mimeType);
    return NextResponse.json({ uploadUrl, filename, storage_backend: 'drive' });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Upload init failed' },
      { status: 502 },
    );
  }
}
