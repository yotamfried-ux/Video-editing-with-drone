import { supabaseAdmin } from '@/lib/supabase-admin';

export type SourceUploadManifestRow = {
  id: string;
  storage_key: string;
  status: string;
  source_size_bytes: number | null;
  verified_size_bytes: number | null;
  verified_at: string | null;
  canonical_upload_id: string | null;
};

export class SourceUploadManifestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'SourceUploadManifestError';
  }
}

export async function createSourceUploadManifest(input: {
  batchId: string;
  storageKey: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes?: number | null;
}): Promise<string> {
  const sourceSize = Number.isFinite(input.sourceSizeBytes) && (input.sourceSizeBytes ?? 0) >= 0
    ? Math.trunc(input.sourceSizeBytes as number)
    : null;
  const { data, error } = await supabaseAdmin
    .from('source_uploads')
    .insert({
      batch_id: input.batchId,
      storage_key: input.storageKey,
      source_filename: input.sourceFilename,
      mime_type: input.mimeType,
      source_size_bytes: sourceSize,
      status: 'uploading',
      updated_at: new Date().toISOString(),
    })
    .select('id')
    .single();

  if (error || !data?.id) {
    throw new SourceUploadManifestError(
      `Could not persist upload manifest: ${error?.message ?? 'missing source upload id'}`,
      503,
    );
  }
  return String(data.id);
}

export async function markSourceUploadVerified(storageKey: string, verifiedSizeBytes: number): Promise<{
  uploadId: string;
  verifiedAt: string;
  status: 'verified';
}> {
  const { data: existing, error: readError } = await supabaseAdmin
    .from('source_uploads')
    .select('id,storage_key,status,source_size_bytes,verified_size_bytes,verified_at,canonical_upload_id')
    .eq('storage_key', storageKey)
    .limit(1)
    .maybeSingle<SourceUploadManifestRow>();

  if (readError) {
    throw new SourceUploadManifestError(`Could not read upload manifest: ${readError.message}`, 503);
  }
  if (!existing) {
    throw new SourceUploadManifestError(`No upload manifest exists for ${storageKey}`, 409);
  }
  if (existing.status === 'superseded') {
    throw new SourceUploadManifestError(
      `Upload is already superseded by ${existing.canonical_upload_id ?? 'a newer verified source'}`,
      409,
    );
  }

  if (existing.source_size_bytes != null && existing.source_size_bytes !== verifiedSizeBytes) {
    await supabaseAdmin
      .from('source_uploads')
      .update({
        status: 'size_mismatch',
        verified_size_bytes: verifiedSizeBytes,
        updated_at: new Date().toISOString(),
      })
      .eq('id', existing.id);
    throw new SourceUploadManifestError(
      `Uploaded object size mismatch: expected ${existing.source_size_bytes}, got ${verifiedSizeBytes}`,
      409,
    );
  }

  // Preserve the first successful verification time. Repeating HEAD verification
  // must never make an older upload appear newer for canonical duplicate selection.
  const verifiedAt = existing.verified_at ?? new Date().toISOString();
  const { error: updateError } = await supabaseAdmin
    .from('source_uploads')
    .update({
      status: 'verified',
      verified_size_bytes: verifiedSizeBytes,
      verified_at: verifiedAt,
      updated_at: new Date().toISOString(),
    })
    .eq('id', existing.id);

  if (updateError) {
    throw new SourceUploadManifestError(`Could not verify upload manifest: ${updateError.message}`, 503);
  }
  return { uploadId: existing.id, verifiedAt, status: 'verified' };
}
