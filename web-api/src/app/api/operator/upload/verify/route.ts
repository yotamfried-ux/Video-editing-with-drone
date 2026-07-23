import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { shouldUseR2Storage, verifyR2Object } from '@/lib/r2-storage';
import {
  markSourceUploadVerified,
  SourceUploadManifestError,
} from '@/lib/source-upload-manifest';
import type { UploadVerifyResponse } from '@/types/operator-contracts';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  let body: { storage_key?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const key = (body.storage_key ?? '').trim();
  if (!key) return NextResponse.json({ error: 'storage_key required' }, { status: 400 });
  if (!key.startsWith('raw/')) {
    return NextResponse.json({ error: 'Only raw/ upload keys can be verified' }, { status: 400 });
  }

  if (!shouldUseR2Storage()) {
    return NextResponse.json<UploadVerifyResponse>({ ok: true, exists: true, storage_backend: 'drive' });
  }

  try {
    const result = await verifyR2Object(key);
    if (!result.exists || result.size == null) {
      return NextResponse.json({
        ok: false,
        exists: false,
        storage_backend: 'r2',
        storage_key: key,
        size: result.size,
        r2_status: result.status,
      }, { status: 404 });
    }

    const manifest = await markSourceUploadVerified(key, result.size);
    return NextResponse.json({
      ok: true,
      exists: true,
      storage_backend: 'r2',
      storage_key: key,
      size: result.size,
      r2_status: result.status,
      upload_id: manifest.uploadId,
      upload_status: manifest.status,
      verified_at: manifest.verifiedAt,
    });
  } catch (e) {
    const status = e instanceof SourceUploadManifestError ? e.status : 502;
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'R2 verification failed', storage_key: key },
      { status },
    );
  }
}
