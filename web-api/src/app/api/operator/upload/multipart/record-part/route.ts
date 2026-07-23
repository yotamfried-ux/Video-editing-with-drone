import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { recordMultipartPart } from '@/lib/multipart-upload-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-multipart-record-part', 600, 3600);
  if (limited) return limited;

  let body: {
    upload_id?: string;
    part_number?: number;
    etag?: string;
    size_bytes?: number;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const uploadId = (body.upload_id ?? '').trim();
  const partNumber = Number(body.part_number);
  const sizeBytes = Number(body.size_bytes);
  const etag = (body.etag ?? '').trim();

  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });
  if (!Number.isInteger(partNumber)) {
    return NextResponse.json({ error: 'part_number must be an integer' }, { status: 400 });
  }
  if (!Number.isSafeInteger(sizeBytes) || sizeBytes <= 0) {
    return NextResponse.json({ error: 'size_bytes must be a positive safe integer' }, { status: 400 });
  }
  if (!etag || etag.length > 1024) {
    return NextResponse.json({ error: 'The exact R2 ETag is required' }, { status: 400 });
  }

  try {
    const result = await recordMultipartPart({ uploadId, partNumber, etag, sizeBytes });
    return NextResponse.json({ ok: true, ...result });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Multipart part record failed',
    }, { status });
  }
}
