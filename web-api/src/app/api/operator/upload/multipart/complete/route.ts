import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  completeR2MultipartUpload,
  verifyR2Object,
} from '@/lib/r2-storage';
import {
  beginMultipartCompletion,
  setMultipartRecoverableError,
} from '@/lib/multipart-upload-manifest';
import {
  markSourceUploadVerified,
  SourceUploadManifestError,
} from '@/lib/source-upload-manifest';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-multipart-complete', 30, 3600);
  if (limited) return limited;

  let body: { upload_id?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const uploadId = (body.upload_id ?? '').trim();
  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });

  try {
    const completion = await beginMultipartCompletion(uploadId);

    // Reconcile an earlier successful R2 completion whose HTTP response or database
    // verification was interrupted. HEAD is authoritative for object existence/size.
    let object = await verifyR2Object(completion.storage_key);
    let recoveredExistingObject = object.exists;
    let multipartEtag: string | null = null;

    if (!object.exists) {
      const completed = await completeR2MultipartUpload(
        completion.storage_key,
        completion.multipart_upload_id,
        completion.parts.map((part) => ({
          partNumber: part.part_number,
          etag: part.etag,
        })),
      );
      multipartEtag = completed.etag;
      recoveredExistingObject = false;
      object = await verifyR2Object(completion.storage_key);
    }

    if (!object.exists || object.size == null) {
      throw new Error(`Completed R2 object is not visible for ${completion.storage_key}`);
    }

    const manifest = await markSourceUploadVerified(completion.storage_key, object.size);

    return NextResponse.json({
      ok: true,
      protocol: 'r2_multipart_v1',
      upload_id: manifest.uploadId,
      upload_status: manifest.status,
      storage_key: completion.storage_key,
      source_size_bytes: completion.source_size_bytes,
      verified_size_bytes: object.size,
      verified_at: manifest.verifiedAt,
      recovered_existing_object: recoveredExistingObject,
      multipart_etag: multipartEtag,
      multipart_etag_is_source_md5: false,
      local_cleanup_required: completion.local_cleanup_required,
      local_cleanup_status: completion.local_cleanup_status,
      cleanup_confirmation_endpoint: '/api/operator/upload/multipart/cleanup',
    });
  } catch (error) {
    try {
      await setMultipartRecoverableError(
        uploadId,
        error instanceof Error ? error.message : 'Multipart completion failed',
      );
    } catch {
      // Preserve the original completion error. The follow-up status call will reveal
      // whether the durable error update itself failed.
    }
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Multipart completion failed',
    }, { status });
  }
}
