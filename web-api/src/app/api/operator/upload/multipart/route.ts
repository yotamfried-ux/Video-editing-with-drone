import { NextRequest, NextResponse } from 'next/server';

import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  MULTIPART_PROTOCOL_VERSION,
  abortR2MultipartUpload,
  chooseMultipartPartSize,
  completeR2MultipartUpload,
  createR2MultipartPartUrl,
  createR2MultipartUpload,
  expectedMultipartPartCount,
  expectedPartSize,
  listR2MultipartParts,
  newBatchId,
  newR2RawObjectKey,
  normalizeCompletedParts,
  safeBatchId,
  shouldUseR2Storage,
  verifyR2Object,
} from '@/lib/r2-storage';
import { supabaseAdmin } from '@/lib/supabase-admin';

export const runtime = 'nodejs';

const MAX_BATCH_FILES = 20;
const MAX_CLIENT_UPLOAD_ID_LENGTH = 200;
const ACTIVE_UPLOAD_STATES = new Set([
  'pending',
  'uploading',
  'paused',
  'source_unavailable',
  'failed',
]);
const TERMINAL_UPLOAD_STATES = new Set(['verified', 'aborted']);

type UploadBatchRow = {
  batch_id: string;
  session_id: string | null;
  athlete_id: string | null;
  grouping_type: 'session' | 'athlete' | 'mixed' | 'other';
  state: string;
  expected_file_count: number;
  verified_file_count: number;
  owner_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

type UploadFileRow = {
  id: string;
  client_upload_id: string;
  batch_id: string;
  r2_key: string;
  upload_id: string;
  source_uri: string | null;
  source_filename: string;
  source_size_bytes: number;
  source_fingerprint: string;
  mime_type: string;
  part_size_bytes: number;
  total_parts: number;
  uploaded_bytes: number;
  protocol_version: string;
  state: string;
  verified_size_bytes: number | null;
  retry_count: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  aborted_at: string | null;
};

type UploadPartRow = {
  upload_file_id: string;
  part_number: number;
  etag: string;
  size_bytes: number;
  retry_count: number;
  uploaded_at: string;
};

type MultipartAction =
  | 'create_batch'
  | 'create_upload'
  | 'part_url'
  | 'record_part'
  | 'complete';

type MultipartBody = {
  action?: MultipartAction;
  batch_id?: string;
  expected_file_count?: number;
  session_id?: string | null;
  athlete_id?: string | null;
  grouping_type?: UploadBatchRow['grouping_type'];
  owner_metadata?: Record<string, unknown>;
  client_upload_id?: string;
  filename?: string;
  mime_type?: string;
  source_uri?: string | null;
  source_size_bytes?: number;
  source_fingerprint?: string;
  requested_part_size_bytes?: number;
  part_number?: number;
  etag?: string;
  size_bytes?: number;
  retry_count?: number;
};

type AbortBody = {
  client_upload_id?: string;
  in_flight_part_numbers?: number[];
};

function errorResponse(error: string, status: number, details?: Record<string, unknown>) {
  return NextResponse.json({ error, ...(details ?? {}) }, { status });
}

function asPositiveSafeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) <= 0) {
    throw new Error(`${label} must be a positive safe integer`);
  }
  return Number(value);
}

function asOptionalText(value: unknown, maxLength: number): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  if (!text) return null;
  if (text.length > maxLength) throw new Error(`value exceeds ${maxLength} characters`);
  return text;
}

function clientUploadId(value: unknown): string {
  const id = asOptionalText(value, MAX_CLIENT_UPLOAD_ID_LENGTH);
  if (!id || !/^[A-Za-z0-9._:-]+$/.test(id)) {
    throw new Error('client_upload_id must contain only letters, numbers, dot, underscore, colon, or dash');
  }
  return id;
}

function requestedBatchId(value: unknown): string {
  const raw = asOptionalText(value, 80);
  if (!raw) return newBatchId();
  const normalized = safeBatchId(raw);
  if (!normalized || normalized !== raw) {
    throw new Error('batch_id contains unsupported characters');
  }
  return normalized;
}

async function readUpload(clientId: string): Promise<UploadFileRow | null> {
  const { data, error } = await supabaseAdmin
    .from('upload_files')
    .select('*')
    .eq('client_upload_id', clientId)
    .maybeSingle();
  if (error) throw new Error(`Could not read upload state: ${error.message}`);
  return data as UploadFileRow | null;
}

async function readParts(uploadFileId: string): Promise<UploadPartRow[]> {
  const { data, error } = await supabaseAdmin
    .from('upload_parts')
    .select('*')
    .eq('upload_file_id', uploadFileId)
    .order('part_number', { ascending: true });
  if (error) throw new Error(`Could not read upload parts: ${error.message}`);
  return (data ?? []) as UploadPartRow[];
}

function publicUpload(upload: UploadFileRow, parts: UploadPartRow[] = []) {
  return {
    id: upload.id,
    client_upload_id: upload.client_upload_id,
    batch_id: upload.batch_id,
    r2_key: upload.r2_key,
    source_filename: upload.source_filename,
    source_size_bytes: upload.source_size_bytes,
    source_fingerprint: upload.source_fingerprint,
    mime_type: upload.mime_type,
    part_size_bytes: upload.part_size_bytes,
    total_parts: upload.total_parts,
    uploaded_bytes: upload.uploaded_bytes,
    protocol_version: upload.protocol_version,
    state: upload.state,
    verified_size_bytes: upload.verified_size_bytes,
    retry_count: upload.retry_count,
    last_error: upload.last_error,
    created_at: upload.created_at,
    updated_at: upload.updated_at,
    completed_at: upload.completed_at,
    aborted_at: upload.aborted_at,
    parts: parts.map((part) => ({
      part_number: part.part_number,
      etag: part.etag,
      size_bytes: part.size_bytes,
      retry_count: part.retry_count,
      uploaded_at: part.uploaded_at,
    })),
  };
}

async function createBatch(body: MultipartBody) {
  const batchId = requestedBatchId(body.batch_id);
  const expectedFileCount = asPositiveSafeInteger(body.expected_file_count, 'expected_file_count');
  if (expectedFileCount > MAX_BATCH_FILES) throw new Error(`expected_file_count cannot exceed ${MAX_BATCH_FILES}`);
  const groupingType = body.grouping_type ?? 'session';
  if (!['session', 'athlete', 'mixed', 'other'].includes(groupingType)) {
    throw new Error('unsupported grouping_type');
  }

  const sessionId = asOptionalText(body.session_id, 200);
  const athleteId = asOptionalText(body.athlete_id, 200);
  const ownerMetadata = body.owner_metadata && typeof body.owner_metadata === 'object' && !Array.isArray(body.owner_metadata)
    ? body.owner_metadata
    : {};

  const { data: existing, error: existingError } = await supabaseAdmin
    .from('upload_batches')
    .select('*')
    .eq('batch_id', batchId)
    .maybeSingle();
  if (existingError) throw new Error(`Could not inspect batch: ${existingError.message}`);

  if (existing) {
    const row = existing as UploadBatchRow;
    if (
      row.expected_file_count !== expectedFileCount ||
      row.session_id !== sessionId ||
      row.athlete_id !== athleteId ||
      row.grouping_type !== groupingType
    ) {
      return errorResponse('batch_id already exists with different immutable membership metadata', 409, { batch_id: batchId });
    }
    return NextResponse.json({ ok: true, created: false, batch: row });
  }

  const { data, error } = await supabaseAdmin
    .from('upload_batches')
    .insert({
      batch_id: batchId,
      expected_file_count: expectedFileCount,
      session_id: sessionId,
      athlete_id: athleteId,
      grouping_type: groupingType,
      owner_metadata: ownerMetadata,
    })
    .select('*')
    .single();
  if (error || !data) throw new Error(`Could not create upload batch: ${error?.message ?? 'missing row'}`);
  return NextResponse.json({ ok: true, created: true, batch: data as UploadBatchRow });
}

async function createUpload(body: MultipartBody) {
  const clientId = clientUploadId(body.client_upload_id);
  const batchId = requestedBatchId(body.batch_id);
  const filename = asOptionalText(body.filename, 300);
  const mimeType = asOptionalText(body.mime_type, 200) ?? 'video/mp4';
  const sourceUri = asOptionalText(body.source_uri, 4000);
  const sourceSizeBytes = asPositiveSafeInteger(body.source_size_bytes, 'source_size_bytes');
  const sourceFingerprint = asOptionalText(body.source_fingerprint, 500);
  if (!filename) throw new Error('filename required');
  if (!sourceFingerprint) throw new Error('source_fingerprint required');

  const existing = await readUpload(clientId);
  if (existing) {
    if (
      existing.batch_id !== batchId ||
      existing.source_size_bytes !== sourceSizeBytes ||
      existing.source_fingerprint !== sourceFingerprint ||
      existing.source_filename !== filename
    ) {
      return errorResponse('client_upload_id already belongs to a different source', 409, { client_upload_id: clientId });
    }
    return NextResponse.json({ ok: true, created: false, upload: publicUpload(existing, await readParts(existing.id)) });
  }

  const { data: batch, error: batchError } = await supabaseAdmin
    .from('upload_batches')
    .select('*')
    .eq('batch_id', batchId)
    .maybeSingle();
  if (batchError) throw new Error(`Could not read batch: ${batchError.message}`);
  if (!batch) return errorResponse('upload batch does not exist', 404, { batch_id: batchId });
  const batchRow = batch as UploadBatchRow;
  if (!['collecting', 'uploading', 'blocked'].includes(batchRow.state)) {
    return errorResponse(`batch is not accepting files while state=${batchRow.state}`, 409, { batch_id: batchId });
  }

  const { count, error: countError } = await supabaseAdmin
    .from('upload_files')
    .select('id', { count: 'exact', head: true })
    .eq('batch_id', batchId);
  if (countError) throw new Error(`Could not count batch uploads: ${countError.message}`);
  if ((count ?? 0) >= batchRow.expected_file_count) {
    return errorResponse('batch already contains its expected number of files', 409, { batch_id: batchId });
  }

  const partSizeBytes = chooseMultipartPartSize(sourceSizeBytes, body.requested_part_size_bytes);
  const totalParts = expectedMultipartPartCount(sourceSizeBytes, partSizeBytes);
  const object = newR2RawObjectKey(filename, batchId);
  const multipart = await createR2MultipartUpload(object.key, mimeType);

  const { data, error } = await supabaseAdmin
    .from('upload_files')
    .insert({
      client_upload_id: clientId,
      batch_id: batchId,
      r2_key: object.key,
      upload_id: multipart.uploadId,
      source_uri: sourceUri,
      source_filename: filename,
      source_size_bytes: sourceSizeBytes,
      source_fingerprint: sourceFingerprint,
      mime_type: mimeType,
      part_size_bytes: partSizeBytes,
      total_parts: totalParts,
      protocol_version: MULTIPART_PROTOCOL_VERSION,
      state: 'pending',
    })
    .select('*')
    .single();

  if (error || !data) {
    try {
      await abortR2MultipartUpload(object.key, multipart.uploadId);
    } catch {
      // The original database failure remains the actionable error. The cleanup
      // failure is handled by the R2 incomplete-upload lifecycle and cleanup job.
    }
    throw new Error(`Could not persist multipart upload: ${error?.message ?? 'missing row'}`);
  }

  return NextResponse.json({ ok: true, created: true, upload: publicUpload(data as UploadFileRow) });
}

async function issuePartUrl(body: MultipartBody) {
  const clientId = clientUploadId(body.client_upload_id);
  const partNumber = asPositiveSafeInteger(body.part_number, 'part_number');
  const upload = await readUpload(clientId);
  if (!upload) return errorResponse('upload not found', 404, { client_upload_id: clientId });
  if (!ACTIVE_UPLOAD_STATES.has(upload.state)) {
    return errorResponse(`part URL cannot be issued while state=${upload.state}`, 409);
  }

  const sizeBytes = expectedPartSize(upload.source_size_bytes, upload.part_size_bytes, partNumber);
  const uploadUrl = createR2MultipartPartUrl(upload.r2_key, upload.upload_id, partNumber);
  const { error } = await supabaseAdmin
    .from('upload_files')
    .update({ state: 'uploading', last_error: null })
    .eq('id', upload.id);
  if (error) throw new Error(`Could not mark upload active: ${error.message}`);

  return NextResponse.json({
    ok: true,
    client_upload_id: clientId,
    upload_url: uploadUrl,
    part_number: partNumber,
    expected_size_bytes: sizeBytes,
    expires_in_seconds: 15 * 60,
  });
}

async function recordPart(body: MultipartBody) {
  const clientId = clientUploadId(body.client_upload_id);
  const partNumber = asPositiveSafeInteger(body.part_number, 'part_number');
  const etag = asOptionalText(body.etag, 500);
  const sizeBytes = asPositiveSafeInteger(body.size_bytes, 'size_bytes');
  if (!etag) throw new Error('etag required');

  const upload = await readUpload(clientId);
  if (!upload) return errorResponse('upload not found', 404, { client_upload_id: clientId });
  if (!ACTIVE_UPLOAD_STATES.has(upload.state)) {
    return errorResponse(`part cannot be recorded while state=${upload.state}`, 409);
  }
  const requiredSize = expectedPartSize(upload.source_size_bytes, upload.part_size_bytes, partNumber);
  if (sizeBytes !== requiredSize) {
    return errorResponse('part size does not match the durable upload contract', 409, {
      part_number: partNumber,
      expected_size_bytes: requiredSize,
      received_size_bytes: sizeBytes,
    });
  }

  const { data: previous, error: previousError } = await supabaseAdmin
    .from('upload_parts')
    .select('*')
    .eq('upload_file_id', upload.id)
    .eq('part_number', partNumber)
    .maybeSingle();
  if (previousError) throw new Error(`Could not inspect existing part: ${previousError.message}`);

  const retryCount = previous
    ? Math.max(Number((previous as UploadPartRow).retry_count ?? 0), Number(body.retry_count ?? 0)) + (previous.etag === etag ? 0 : 1)
    : Math.max(0, Number(body.retry_count ?? 0));

  const { error } = await supabaseAdmin
    .from('upload_parts')
    .upsert({
      upload_file_id: upload.id,
      part_number: partNumber,
      etag,
      size_bytes: sizeBytes,
      retry_count: retryCount,
      uploaded_at: new Date().toISOString(),
    }, { onConflict: 'upload_file_id,part_number' });
  if (error) throw new Error(`Could not persist completed part: ${error.message}`);

  const refreshed = await readUpload(clientId);
  return NextResponse.json({
    ok: true,
    part: { part_number: partNumber, etag, size_bytes: sizeBytes, retry_count: retryCount },
    uploaded_bytes: refreshed?.uploaded_bytes ?? upload.uploaded_bytes,
  });
}

async function completeUpload(body: MultipartBody) {
  const clientId = clientUploadId(body.client_upload_id);
  const upload = await readUpload(clientId);
  if (!upload) return errorResponse('upload not found', 404, { client_upload_id: clientId });
  if (upload.state === 'verified') {
    return NextResponse.json({ ok: true, already_completed: true, upload: publicUpload(upload, await readParts(upload.id)) });
  }
  if (!ACTIVE_UPLOAD_STATES.has(upload.state)) {
    return errorResponse(`upload cannot complete while state=${upload.state}`, 409);
  }

  const parts = await readParts(upload.id);
  let durableParts;
  try {
    durableParts = normalizeCompletedParts(
      parts.map((part) => ({ partNumber: part.part_number, etag: part.etag, sizeBytes: part.size_bytes })),
      upload.source_size_bytes,
      upload.part_size_bytes,
    );
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'multipart ledger is incomplete', 409);
  }

  const r2Parts = await listR2MultipartParts(upload.r2_key, upload.upload_id);
  let normalizedR2Parts;
  try {
    normalizedR2Parts = normalizeCompletedParts(r2Parts, upload.source_size_bytes, upload.part_size_bytes);
  } catch (error) {
    return errorResponse(`R2 part reconciliation failed: ${error instanceof Error ? error.message : 'invalid parts'}`, 409);
  }

  const mismatch = durableParts.find((part, index) =>
    normalizedR2Parts[index]?.PartNumber !== part.PartNumber ||
    normalizedR2Parts[index]?.ETag !== part.ETag ||
    normalizedR2Parts[index]?.sizeBytes !== part.sizeBytes
  );
  if (mismatch) {
    return errorResponse('R2 parts do not match the durable ETag/size ledger', 409, { part_number: mismatch.PartNumber });
  }

  const { error: completingError } = await supabaseAdmin
    .from('upload_files')
    .update({ state: 'completing', last_error: null })
    .eq('id', upload.id);
  if (completingError) throw new Error(`Could not mark upload completing: ${completingError.message}`);

  try {
    const completed = await completeR2MultipartUpload(
      upload.r2_key,
      upload.upload_id,
      durableParts,
      upload.source_size_bytes,
      upload.part_size_bytes,
    );
    const verified = await verifyR2Object(upload.r2_key);
    if (!verified.exists || verified.size !== upload.source_size_bytes) {
      const message = `R2 size verification failed: expected ${upload.source_size_bytes}, received ${verified.size}`;
      await supabaseAdmin
        .from('upload_files')
        .update({ state: 'failed', last_error: message, verified_size_bytes: verified.size })
        .eq('id', upload.id);
      return errorResponse(message, 409, { r2_status: verified.status });
    }

    const completedAt = new Date().toISOString();
    const { data, error } = await supabaseAdmin
      .from('upload_files')
      .update({
        state: 'verified',
        verified_size_bytes: verified.size,
        uploaded_bytes: upload.source_size_bytes,
        completed_at: completedAt,
        last_error: null,
      })
      .eq('id', upload.id)
      .select('*')
      .single();
    if (error || !data) throw new Error(`R2 completed but durable verification update failed: ${error?.message ?? 'missing row'}`);

    return NextResponse.json({
      ok: true,
      already_completed: false,
      final_etag: completed.etag,
      upload: publicUpload(data as UploadFileRow, parts),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'multipart completion failed';
    await supabaseAdmin
      .from('upload_files')
      .update({ state: 'failed', last_error: message, retry_count: upload.retry_count + 1 })
      .eq('id', upload.id);
    throw new Error(message);
  }
}

export async function GET(req: NextRequest) {
  if (!requireOperator(req)) return errorResponse('Unauthorized', 401);
  const limited = await enforceRateLimit(req, 'operator-upload-multipart-read', 120, 3600);
  if (limited) return limited;

  const clientId = req.nextUrl.searchParams.get('client_upload_id');
  const batchId = req.nextUrl.searchParams.get('batch_id');
  try {
    if (clientId) {
      const upload = await readUpload(clientUploadId(clientId));
      if (!upload) return errorResponse('upload not found', 404);
      return NextResponse.json({ ok: true, upload: publicUpload(upload, await readParts(upload.id)) });
    }
    if (batchId) {
      const normalizedBatchId = requestedBatchId(batchId);
      const [{ data: batch, error: batchError }, { data: uploads, error: uploadsError }] = await Promise.all([
        supabaseAdmin.from('upload_batches').select('*').eq('batch_id', normalizedBatchId).maybeSingle(),
        supabaseAdmin.from('upload_files').select('*').eq('batch_id', normalizedBatchId).order('created_at', { ascending: true }),
      ]);
      if (batchError) throw new Error(`Could not read batch: ${batchError.message}`);
      if (uploadsError) throw new Error(`Could not read batch uploads: ${uploadsError.message}`);
      if (!batch) return errorResponse('batch not found', 404);
      return NextResponse.json({
        ok: true,
        batch: batch as UploadBatchRow,
        uploads: (uploads ?? []).map((upload) => publicUpload(upload as UploadFileRow)),
      });
    }
    return errorResponse('client_upload_id or batch_id required', 400);
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'multipart state read failed', 502);
  }
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return errorResponse('Unauthorized', 401);
  if (!shouldUseR2Storage()) return errorResponse('Multipart upload requires STORAGE_BACKEND=r2', 503);

  let body: MultipartBody;
  try {
    body = await req.json();
  } catch {
    return errorResponse('Invalid JSON', 400);
  }
  if (!body.action) return errorResponse('action required', 400);

  const limited = await enforceRateLimit(req, `operator-upload-multipart-${body.action}`, 120, 3600);
  if (limited) return limited;

  try {
    switch (body.action) {
      case 'create_batch':
        return await createBatch(body);
      case 'create_upload':
        return await createUpload(body);
      case 'part_url':
        return await issuePartUrl(body);
      case 'record_part':
        return await recordPart(body);
      case 'complete':
        return await completeUpload(body);
      default:
        return errorResponse('unsupported multipart action', 400);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'multipart upload action failed';
    const status = /required|must|unsupported|exceed|characters/.test(message) ? 400 : 502;
    return errorResponse(message, status);
  }
}

export async function DELETE(req: NextRequest) {
  if (!requireOperator(req)) return errorResponse('Unauthorized', 401);
  if (!shouldUseR2Storage()) return errorResponse('Multipart upload requires STORAGE_BACKEND=r2', 503);
  const limited = await enforceRateLimit(req, 'operator-upload-multipart-abort', 30, 3600);
  if (limited) return limited;

  let body: AbortBody;
  try {
    body = await req.json();
  } catch {
    return errorResponse('Invalid JSON', 400);
  }

  try {
    const clientId = clientUploadId(body.client_upload_id);
    const inFlight = Array.isArray(body.in_flight_part_numbers)
      ? body.in_flight_part_numbers.filter((part) => Number.isSafeInteger(part) && part > 0)
      : [];
    if (inFlight.length) {
      return errorResponse('wait for all in-flight part requests before abort', 409, { in_flight_part_numbers: inFlight });
    }

    const upload = await readUpload(clientId);
    if (!upload) return errorResponse('upload not found', 404);
    if (upload.state === 'verified') return errorResponse('verified upload cannot be aborted', 409);
    if (upload.state === 'aborted') {
      return NextResponse.json({ ok: true, already_aborted: true, upload: publicUpload(upload, await readParts(upload.id)) });
    }
    if (TERMINAL_UPLOAD_STATES.has(upload.state)) return errorResponse(`upload cannot abort while state=${upload.state}`, 409);

    const beforeParts = await listR2MultipartParts(upload.r2_key, upload.upload_id);
    const { error: abortingError } = await supabaseAdmin
      .from('upload_files')
      .update({ state: 'aborting', last_error: null })
      .eq('id', upload.id);
    if (abortingError) throw new Error(`Could not mark upload aborting: ${abortingError.message}`);

    await abortR2MultipartUpload(upload.r2_key, upload.upload_id);
    const afterParts = await listR2MultipartParts(upload.r2_key, upload.upload_id);
    if (afterParts.length) {
      const message = 'R2 multipart upload still reports active parts after abort';
      await supabaseAdmin.from('upload_files').update({ state: 'failed', last_error: message }).eq('id', upload.id);
      return errorResponse(message, 502, { active_part_count: afterParts.length });
    }

    const abortedAt = new Date().toISOString();
    const { data, error } = await supabaseAdmin
      .from('upload_files')
      .update({ state: 'aborted', aborted_at: abortedAt, last_error: null })
      .eq('id', upload.id)
      .select('*')
      .single();
    if (error || !data) throw new Error(`R2 aborted but durable state update failed: ${error?.message ?? 'missing row'}`);

    return NextResponse.json({
      ok: true,
      already_aborted: false,
      reconciled_part_count: beforeParts.length,
      upload: publicUpload(data as UploadFileRow, await readParts(upload.id)),
    });
  } catch (error) {
    return errorResponse(error instanceof Error ? error.message : 'multipart abort failed', 502);
  }
}
