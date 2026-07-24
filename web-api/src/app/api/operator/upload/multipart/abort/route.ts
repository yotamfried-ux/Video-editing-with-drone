import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { abortR2MultipartUpload } from '@/lib/r2-storage';
import {
  getMultipartSession,
  markMultipartAborted,
} from '@/lib/multipart-upload-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-multipart-abort', 30, 3600);
  if (limited) return limited;

  let body: { upload_id?: string; reason?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const uploadId = (body.upload_id ?? '').trim();
  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });

  try {
    const session = await getMultipartSession(uploadId);
    if (['verified', 'superseded'].includes(session.status)) {
      return NextResponse.json({
        error: `A ${session.status} source cannot be aborted`,
      }, { status: 409 });
    }

    await abortR2MultipartUpload(session.storage_key, session.multipart_upload_id);
    await markMultipartAborted(uploadId, (body.reason ?? '').trim() || 'operator_abort');

    return NextResponse.json({
      ok: true,
      upload_id: uploadId,
      upload_status: 'aborted',
      storage_key: session.storage_key,
      local_cleanup_required: session.local_cleanup_required,
      local_cleanup_status: session.local_cleanup_status,
      cleanup_confirmation_endpoint: '/api/operator/upload/multipart/cleanup',
    });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Multipart abort failed',
    }, { status });
  }
}
