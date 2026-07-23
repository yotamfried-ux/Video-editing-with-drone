import { supabaseAdmin } from '@/lib/supabase-admin';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

export type MultipartPartRecord = {
  part_number: number;
  etag: string;
  size_bytes: number;
};

export type MultipartSession = {
  upload_id: string;
  batch_id: string;
  storage_key: string;
  source_filename: string;
  mime_type: string | null;
  source_size_bytes: number;
  status: string;
  upload_protocol: 'r2_multipart_v1';
  multipart_upload_id: string;
  part_size_bytes: number;
  expected_part_count: number;
  completed_part_count: number;
  local_cleanup_required: boolean;
  local_cleanup_status: 'not_required' | 'pending' | 'confirmed' | 'failed';
  local_cleanup_confirmed_at: string | null;
  local_cleanup_error: string | null;
  last_error: string | null;
  parts: MultipartPartRecord[];
};

type RpcJson = Record<string, unknown>;

function oneRpcObject(data: unknown, operation: string): RpcJson {
  const raw = Array.isArray(data) && data.length === 1 ? data[0] : data;
  if (!raw || typeof raw !== 'object') {
    throw new SourceUploadManifestError(`${operation} returned an invalid result`, 503);
  }
  return raw as RpcJson;
}

function rpcErrorStatus(message: string): number {
  if (/not found/i.test(message)) return 404;
  if (/status|incomplete|mismatch|outside|already|requires|cannot|invalid/i.test(message)) return 409;
  return 503;
}

export async function attachMultipartSession(input: {
  uploadId: string;
  multipartUploadId: string;
  partSizeBytes: number;
  expectedPartCount: number;
  localCleanupRequired: boolean;
}): Promise<RpcJson> {
  const { data, error } = await supabaseAdmin.rpc('attach_source_multipart_session', {
    p_upload_id: input.uploadId,
    p_multipart_upload_id: input.multipartUploadId,
    p_part_size_bytes: input.partSizeBytes,
    p_expected_part_count: input.expectedPartCount,
    p_local_cleanup_required: input.localCleanupRequired,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Could not attach multipart session: ${error.message}`,
      rpcErrorStatus(error.message),
    );
  }
  return oneRpcObject(data, 'Multipart session attach');
}

export async function getMultipartSession(uploadId: string): Promise<MultipartSession> {
  const { data: upload, error: uploadError } = await supabaseAdmin
    .from('source_uploads')
    .select('id,batch_id,storage_key,source_filename,mime_type,source_size_bytes,status,upload_protocol,multipart_upload_id,part_size_bytes,expected_part_count,completed_part_count,local_cleanup_required,local_cleanup_status,local_cleanup_confirmed_at,local_cleanup_error,last_error')
    .eq('id', uploadId)
    .maybeSingle();

  if (uploadError) {
    throw new SourceUploadManifestError(`Could not read multipart upload: ${uploadError.message}`, 503);
  }
  if (!upload) throw new SourceUploadManifestError(`Source upload ${uploadId} not found`, 404);
  if (
    upload.upload_protocol !== 'r2_multipart_v1'
    || !upload.multipart_upload_id
    || upload.source_size_bytes == null
    || upload.part_size_bytes == null
    || upload.expected_part_count == null
  ) {
    throw new SourceUploadManifestError(`Source upload ${uploadId} has no complete multipart session`, 409);
  }

  const { data: parts, error: partsError } = await supabaseAdmin
    .from('source_upload_parts')
    .select('part_number,etag,size_bytes')
    .eq('source_upload_id', uploadId)
    .order('part_number', { ascending: true });
  if (partsError) {
    throw new SourceUploadManifestError(`Could not read multipart part ledger: ${partsError.message}`, 503);
  }

  return {
    upload_id: String(upload.id),
    batch_id: String(upload.batch_id),
    storage_key: String(upload.storage_key),
    source_filename: String(upload.source_filename),
    mime_type: upload.mime_type == null ? null : String(upload.mime_type),
    source_size_bytes: Number(upload.source_size_bytes),
    status: String(upload.status),
    upload_protocol: 'r2_multipart_v1',
    multipart_upload_id: String(upload.multipart_upload_id),
    part_size_bytes: Number(upload.part_size_bytes),
    expected_part_count: Number(upload.expected_part_count),
    completed_part_count: Number(upload.completed_part_count ?? 0),
    local_cleanup_required: Boolean(upload.local_cleanup_required),
    local_cleanup_status: upload.local_cleanup_status as MultipartSession['local_cleanup_status'],
    local_cleanup_confirmed_at: upload.local_cleanup_confirmed_at == null ? null : String(upload.local_cleanup_confirmed_at),
    local_cleanup_error: upload.local_cleanup_error == null ? null : String(upload.local_cleanup_error),
    last_error: upload.last_error == null ? null : String(upload.last_error),
    parts: (parts ?? []).map((part) => ({
      part_number: Number(part.part_number),
      etag: String(part.etag),
      size_bytes: Number(part.size_bytes),
    })),
  };
}

export async function recordMultipartPart(input: {
  uploadId: string;
  partNumber: number;
  etag: string;
  sizeBytes: number;
}): Promise<RpcJson> {
  const { data, error } = await supabaseAdmin.rpc('record_source_upload_part', {
    p_upload_id: input.uploadId,
    p_part_number: input.partNumber,
    p_etag: input.etag,
    p_size_bytes: input.sizeBytes,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Could not record multipart part: ${error.message}`,
      rpcErrorStatus(error.message),
    );
  }
  return oneRpcObject(data, 'Multipart part record');
}

export async function beginMultipartCompletion(uploadId: string): Promise<{
  upload_id: string;
  storage_key: string;
  source_size_bytes: number;
  multipart_upload_id: string;
  local_cleanup_required: boolean;
  local_cleanup_status: string;
  parts: MultipartPartRecord[];
}> {
  const { data, error } = await supabaseAdmin.rpc('begin_source_upload_completion', {
    p_upload_id: uploadId,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Could not begin multipart completion: ${error.message}`,
      rpcErrorStatus(error.message),
    );
  }
  const raw = oneRpcObject(data, 'Multipart completion');
  if (
    !raw.upload_id
    || !raw.storage_key
    || !raw.multipart_upload_id
    || !Array.isArray(raw.parts)
    || !Number.isFinite(Number(raw.source_size_bytes))
  ) {
    throw new SourceUploadManifestError('Multipart completion returned incomplete durable state', 503);
  }
  return {
    upload_id: String(raw.upload_id),
    storage_key: String(raw.storage_key),
    source_size_bytes: Number(raw.source_size_bytes),
    multipart_upload_id: String(raw.multipart_upload_id),
    local_cleanup_required: Boolean(raw.local_cleanup_required),
    local_cleanup_status: String(raw.local_cleanup_status ?? 'pending'),
    parts: (raw.parts as RpcJson[]).map((part) => ({
      part_number: Number(part.part_number),
      etag: String(part.etag),
      size_bytes: Number(part.size_bytes),
    })),
  };
}

export async function setMultipartRecoverableError(uploadId: string, message: string): Promise<void> {
  const { error } = await supabaseAdmin.rpc('set_source_upload_recoverable_error', {
    p_upload_id: uploadId,
    p_error: message,
  });
  if (error) {
    throw new SourceUploadManifestError(`Could not persist multipart error: ${error.message}`, 503);
  }
}

export async function markMultipartAborted(uploadId: string, message?: string | null): Promise<void> {
  const { error } = await supabaseAdmin.rpc('mark_source_upload_aborted', {
    p_upload_id: uploadId,
    p_error: message ?? null,
  });
  if (error) {
    throw new SourceUploadManifestError(`Could not persist multipart abort: ${error.message}`, 503);
  }
}

export async function recordLocalCleanup(input: {
  uploadId: string;
  status: 'not_required' | 'confirmed' | 'failed';
  error?: string | null;
}): Promise<RpcJson> {
  const { data, error } = await supabaseAdmin.rpc('record_source_upload_local_cleanup', {
    p_upload_id: input.uploadId,
    p_status: input.status,
    p_error: input.error ?? null,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Could not record local cleanup: ${error.message}`,
      rpcErrorStatus(error.message),
    );
  }
  return oneRpcObject(data, 'Local cleanup record');
}
