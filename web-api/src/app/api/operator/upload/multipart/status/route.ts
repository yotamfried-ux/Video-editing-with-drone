import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { getMultipartSession } from '@/lib/multipart-upload-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  let body: { upload_id?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const uploadId = (body.upload_id ?? '').trim();
  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });

  try {
    const session = await getMultipartSession(uploadId);
    return NextResponse.json({
      ok: true,
      protocol: session.upload_protocol,
      upload_id: session.upload_id,
      batch_id: session.batch_id,
      storage_key: session.storage_key,
      source_filename: session.source_filename,
      mimeType: session.mime_type,
      source_size_bytes: session.source_size_bytes,
      status: session.status,
      part_size_bytes: session.part_size_bytes,
      expected_part_count: session.expected_part_count,
      completed_part_count: session.completed_part_count,
      completed_parts: session.parts,
      local_cleanup_required: session.local_cleanup_required,
      local_cleanup_status: session.local_cleanup_status,
      local_cleanup_confirmed_at: session.local_cleanup_confirmed_at,
      local_cleanup_error: session.local_cleanup_error,
      local_cleanup_artifact_count: session.local_cleanup_artifact_count,
      local_cleanup_reclaimed_bytes: session.local_cleanup_reclaimed_bytes,
      local_cleanup_source_preserved: session.local_cleanup_source_preserved,
      local_cleanup_checked_at: session.local_cleanup_checked_at,
      last_error: session.last_error,
    });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Multipart status failed',
    }, { status });
  }
}
