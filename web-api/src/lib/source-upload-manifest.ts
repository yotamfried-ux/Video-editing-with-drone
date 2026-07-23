import { supabaseAdmin } from '@/lib/supabase-admin';

export class SourceUploadManifestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'SourceUploadManifestError';
  }
}

type SourceUploadManifestInput = {
  batchId: string;
  storageKey: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes?: number | null;
};

type VerifySourceUploadResult = {
  upload_id: string;
  status: 'verified' | 'size_mismatch';
  source_size_bytes: number | null;
  verified_size_bytes: number;
  verified_at: string | null;
};

export async function createSourceUploadManifests(
  inputs: SourceUploadManifestInput[],
): Promise<Map<string, string>> {
  if (!inputs.length) return new Map();
  const now = new Date().toISOString();
  const rows = inputs.map((input) => ({
    batch_id: input.batchId,
    storage_key: input.storageKey,
    source_filename: input.sourceFilename,
    mime_type: input.mimeType,
    source_size_bytes:
      Number.isFinite(input.sourceSizeBytes) && (input.sourceSizeBytes ?? 0) >= 0
        ? Math.trunc(input.sourceSizeBytes as number)
        : null,
    status: 'uploading',
    updated_at: now,
  }));
  const { data, error } = await supabaseAdmin
    .from('source_uploads')
    .insert(rows)
    .select('id,storage_key');

  if (error || !data || data.length !== rows.length) {
    throw new SourceUploadManifestError(
      `Could not persist upload manifest: ${error?.message ?? 'incomplete source upload rows'}`,
      503,
    );
  }
  return new Map(data.map((row) => [String(row.storage_key), String(row.id)]));
}

export async function markSourceUploadVerified(storageKey: string, verifiedSizeBytes: number): Promise<{
  uploadId: string;
  verifiedAt: string;
  status: 'verified';
}> {
  const { data, error } = await supabaseAdmin.rpc('verify_source_upload', {
    p_storage_key: storageKey,
    p_verified_size_bytes: verifiedSizeBytes,
  });

  if (error) {
    const status = /not found|superseded/i.test(error.message) ? 409 : 503;
    throw new SourceUploadManifestError(`Could not verify upload manifest: ${error.message}`, status);
  }

  const raw = Array.isArray(data) && data.length === 1 ? data[0] : data;
  const result = raw as VerifySourceUploadResult | null;
  if (!result?.upload_id || !result.status) {
    throw new SourceUploadManifestError('Upload verification returned an invalid manifest result', 503);
  }
  if (result.status === 'size_mismatch') {
    throw new SourceUploadManifestError(
      `Uploaded object size mismatch: expected ${result.source_size_bytes}, got ${result.verified_size_bytes}`,
      409,
    );
  }
  if (result.status !== 'verified' || !result.verified_at) {
    throw new SourceUploadManifestError(`Upload manifest did not reach verified state for ${storageKey}`, 503);
  }

  return {
    uploadId: String(result.upload_id),
    verifiedAt: result.verified_at,
    status: 'verified',
  };
}
