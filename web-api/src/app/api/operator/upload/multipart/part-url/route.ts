import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { createR2MultipartPartUploadUrl } from '@/lib/r2-storage';
import { getMultipartSession } from '@/lib/multipart-upload-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const limited = await enforceRateLimit(req, 'operator-multipart-part-url', 600, 3600);
  if (limited) return limited;

  let body: { upload_id?: string; part_number?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const uploadId = (body.upload_id ?? '').trim();
  const partNumber = Number(body.part_number);
  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });
  if (!Number.isInteger(partNumber)) {
    return NextResponse.json({ error: 'part_number must be an integer' }, { status: 400 });
  }

  try {
    const session = await getMultipartSession(uploadId);
    if (!['uploading', 'paused'].includes(session.status)) {
      return NextResponse.json({
        error: `Multipart part URL is unavailable while upload is ${session.status}`,
      }, { status: 409 });
    }
    if (partNumber < 1 || partNumber > session.expected_part_count) {
      return NextResponse.json({
        error: `part_number must be between 1 and ${session.expected_part_count}`,
      }, { status: 400 });
    }

    const sizeBytes = partNumber < session.expected_part_count
      ? session.part_size_bytes
      : session.source_size_bytes - (session.part_size_bytes * (session.expected_part_count - 1));
    const uploadUrl = createR2MultipartPartUploadUrl(
      session.storage_key,
      session.multipart_upload_id,
      partNumber,
    );

    return NextResponse.json({
      ok: true,
      upload_id: uploadId,
      part_number: partNumber,
      size_bytes: sizeBytes,
      upload_url: uploadUrl,
      expires_in_seconds: 900,
    });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Multipart part URL failed',
    }, { status });
  }
}
