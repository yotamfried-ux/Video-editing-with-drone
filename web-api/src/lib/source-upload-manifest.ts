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

type SinglePutSourceManifestInput = {
  clientUploadId: string;
  batchId: string;
  storageKey: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes: number;
};

export type SourceUploadSession = {
  uploadId: string;
  clientUploadId: string | null;
  batchId: string;
  storageKey: string;
  sourceFilename: string;
  mimeType: string | null;
  sourceSizeBytes: number | null;
  status: string;
  uploadProtocol: string;
};

type VerifySourceUploadResult = {
  upload_id: string;
  status: 'verified' | 'size_mismatch';
  source_size_bytes: number | null;
  verified_size_bytes: number;
  verified_at: string | null;
};

type SourceUploadRow = {
  id: unknown;
  client_upload_id: unknown;
  batch_id: unknown;
  storage_key: unknown;
  source_filename: unknown;
  mime_type: unknown;
  source_size_bytes: unknown;
  status: unknown;
  upload_protocol: unknown;
};

const SOURCE_SESSION_COLUMNS = 'id,client_upload_id,batch_id,storage_key,source_filename,mime_type,source_size_bytes,status,upload_protocol';

function sourceUploadSession(row: SourceUploadRow): SourceUploadSession {
  return {
    uploadId: String(row.id),
    clientUploadId: row.client_upload_id == null ? null : String(row.client_upload_id),
    batchId: String(row.batch_id),
    storageKey: String(row.storage_key),
    sourceFilename: String(row.source_filename),
    mimeType: row.mime_type == null ? null : String(row.mime_type),
    sourceSizeBytes: row.source_size_bytes == null ? null : Number(row.source_size_bytes),
    status: String(row.status),
    uploadProtocol: String(row.upload_protocol),
  };
}

export async function findSourceUploadByClientUploadId(
  clientUploadId: string,
): Promise<SourceUploadSession | null> {
  const { data, error } = await supabaseAdmin
    .from('source_uploads')
    .select(SOURCE_SESSION_COLUMNS)
    .eq('client_upload_id', clientUploadId)
    .maybeSingle();
  if (error) {
    throw new SourceUploadManifestError(`Could not recover source upload: ${error.message}`, 503);
  }
  return data ? sourceUploadSession(data as unknown as SourceUploadRow) : null;
}

export async function createSinglePutSourceManifest(
  input: SinglePutSourceManifestInput,
): Promise<{ session: SourceUploadSession; created: boolean }> {
  if (!Number.isSafeInteger(input.sourceSizeBytes) || input.sourceSizeBytes <= 0) {
    throw new SourceUploadManifestError('Single-PUT source size must be a positive integer', 400);
  }
  const now = new Date().toISOString();
  const { data, error } = await supabaseAdmin
    .from('source_uploads')
    .insert({
      client_upload_id: input.clientUploadId,
      batch_id: input.batchId,
      storage_key: input.storageKey,
      source_filename: input.sourceFilename,
      mime_type: input.mimeType,
      source_size_bytes: input.sourceSizeBytes,
      source_size_evidence: 'client_declared',
      status: 'uploading',
      upload_protocol: 'single_put',
      local_cleanup_required: false,
      local_cleanup_status: 'not_required',
      updated_at: now,
    })
    .select(SOURCE_SESSION_COLUMNS)
    .single();

  if (!error && data) {
    return { session: sourceUploadSession(data as unknown as SourceUploadRow), created: true };
  }
  if (error?.code === '23505') {
    const existing = await findSourceUploadByClientUploadId(input.clientUploadId);
    if (existing) return { session: existing, created: false };
  }
  throw new SourceUploadManifestError(
    `Could not persist single-PUT upload manifest: ${error?.message ?? 'missing source upload row'}`,
    503,
  );
}

export async function registerSourceUploadBatchMembership(
  uploadId: string,
  sourceKind: 'operator' | 'android_external' | 'gallery' | 'api',
  groupingKind: 'unassigned' | 'one_athlete' | 'session_multiple_athletes' | 'other',
): Promise<void> {
  const { error } = await supabaseAdmin.rpc('register_source_upload_batch_membership', {
    p_upload_id: uploadId,
    p_source_kind: sourceKind,
    p_grouping_kind: groupingKind,
  });
  if (error) {
    const status = /not found|cannot accept|invalid|mismatch/i.test(error.message) ? 409 : 503;
    throw new SourceUploadManifestError(`Could not register source upload batch membership: ${error.message}`, status);
  }
}

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
