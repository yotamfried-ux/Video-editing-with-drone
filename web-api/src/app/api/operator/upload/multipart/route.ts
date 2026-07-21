import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  abortR2MultipartUpload,
  completeR2MultipartUpload,
  createR2MultipartPartUrl,
  getR2MultipartStatus,
  isSafeRawR2Key,
  shouldUseR2Storage,
} from '@/lib/r2-storage';

type MultipartAction = 'status' | 'part_url' | 'complete' | 'abort';

type MultipartBody = {
  action?: MultipartAction;
  storage_key?: string;
  upload_id?: string;
  part_number?: number;
  expected_size_bytes?: number;
};

function positiveInteger(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  if (!shouldUseR2Storage()) {
    return NextResponse.json({ error: 'Multipart upload is available only with R2 storage' }, { status: 409 });
  }

  // One 5 TiB object can require up to 10,000 part URLs. Keep the budget
  // above the official part ceiling while still rate-limiting the operator API.
  const limited = await enforceRateLimit(req, 'operator-upload-multipart-lifecycle', 25_000, 3600);
  if (limited) return limited;

  let body: MultipartBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const action = body.action;
  const key = (body.storage_key ?? '').trim();
  const uploadId = (body.upload_id ?? '').trim();
  if (!action || !['status', 'part_url', 'complete', 'abort'].includes(action)) {
    return NextResponse.json({ error: 'Unsupported multipart action' }, { status: 400 });
  }
  if (!isSafeRawR2Key(key)) return NextResponse.json({ error: 'Invalid storage_key' }, { status: 400 });
  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });

  try {
    if (action === 'status') {
      const status = await getR2MultipartStatus(key, uploadId);
      return NextResponse.json({
        ok: status.state !== 'missing',
        storage_key: key,
        upload_id: uploadId,
        ...status,
      });
    }

    if (action === 'part_url') {
      const partNumber = positiveInteger(body.part_number);
      if (!partNumber || partNumber > 10_000) {
        return NextResponse.json({ error: 'part_number must be between 1 and 10000' }, { status: 400 });
      }

      // Do not ListParts here. Doing so before every part makes an N-part
      // upload O(N²). A mismatched/expired upload id is rejected by R2 itself;
      // the client reconciles with the explicit status endpoint on retry.
      return NextResponse.json({
        ok: true,
        already_complete: false,
        storage_key: key,
        upload_id: uploadId,
        part_number: partNumber,
        upload_url: createR2MultipartPartUrl(key, uploadId, partNumber),
        expires_in_seconds: 3600,
      });
    }

    if (action === 'complete') {
      const expectedSize = positiveInteger(body.expected_size_bytes);
      if (!expectedSize) {
        return NextResponse.json({ error: 'expected_size_bytes must be a positive integer' }, { status: 400 });
      }
      const result = await completeR2MultipartUpload(key, uploadId, expectedSize);
      return NextResponse.json({
        ok: true,
        verified: true,
        storage_key: result.key,
        size: result.size,
        etag: result.etag,
        parts_count: result.parts.length,
      });
    }

    await abortR2MultipartUpload(key, uploadId);
    return NextResponse.json({ ok: true, aborted: true, storage_key: key, upload_id: uploadId });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Multipart upload action failed';
    const isClientConflict = /missing part|byte total mismatch|no longer exists|smaller than|same byte size|cannot be larger|empty multipart|size mismatch/i.test(message);
    return NextResponse.json({ error: message, storage_key: key, upload_id: uploadId }, { status: isClientConflict ? 409 : 502 });
  }
}
