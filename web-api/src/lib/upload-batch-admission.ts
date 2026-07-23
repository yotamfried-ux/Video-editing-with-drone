import { supabaseAdmin } from '@/lib/supabase-admin';

export type AdmittedUploadObject = {
  client_upload_id: string;
  r2_key: string;
  source_filename: string;
  source_size_bytes: number;
  verified_size_bytes: number;
  source_fingerprint: string;
};

export type AdmittedUploadBatch = {
  batch_id: string;
  expected_file_count: number;
  verified_file_count: number;
  grouping_type: string;
  session_id: string | null;
  athlete_id: string | null;
  input_objects: AdmittedUploadObject[];
};

type UploadBatchRow = {
  batch_id: string;
  state: string;
  expected_file_count: number;
  verified_file_count: number;
  grouping_type: string;
  session_id: string | null;
  athlete_id: string | null;
};

type UploadFileRow = {
  client_upload_id: string;
  r2_key: string;
  source_filename: string;
  source_size_bytes: number;
  verified_size_bytes: number | null;
  source_fingerprint: string;
  state: string;
};

export class UploadBatchAdmissionError extends Error {
  status: number;
  details: Record<string, unknown>;

  constructor(message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'UploadBatchAdmissionError';
    this.status = status;
    this.details = details;
  }
}

export async function claimVerifiedUploadBatch(batchId: string): Promise<AdmittedUploadBatch> {
  const [{ data: batch, error: batchError }, { data: files, error: filesError }] = await Promise.all([
    supabaseAdmin
      .from('upload_batches')
      .select('batch_id,state,expected_file_count,verified_file_count,grouping_type,session_id,athlete_id')
      .eq('batch_id', batchId)
      .maybeSingle(),
    supabaseAdmin
      .from('upload_files')
      .select('client_upload_id,r2_key,source_filename,source_size_bytes,verified_size_bytes,source_fingerprint,state')
      .eq('batch_id', batchId)
      .order('created_at', { ascending: true }),
  ]);

  if (batchError) throw new Error(`Could not read upload batch: ${batchError.message}`);
  if (filesError) throw new Error(`Could not read upload files: ${filesError.message}`);
  if (!batch) throw new UploadBatchAdmissionError('Upload batch not found', 404, { batch_id: batchId });

  const row = batch as UploadBatchRow;
  const uploadFiles = (files ?? []) as UploadFileRow[];
  if (row.state !== 'ready') {
    throw new UploadBatchAdmissionError(
      `Upload batch is not ready (state=${row.state})`,
      409,
      {
        batch_id: batchId,
        batch_state: row.state,
        expected_file_count: row.expected_file_count,
        verified_file_count: row.verified_file_count,
      },
    );
  }
  if (uploadFiles.length !== row.expected_file_count || row.verified_file_count !== row.expected_file_count) {
    throw new UploadBatchAdmissionError('Upload batch membership is incomplete', 409, {
      batch_id: batchId,
      expected_file_count: row.expected_file_count,
      durable_file_count: uploadFiles.length,
      verified_file_count: row.verified_file_count,
    });
  }

  const invalid = uploadFiles.find((file) =>
    file.state !== 'verified' ||
    file.verified_size_bytes === null ||
    file.verified_size_bytes !== file.source_size_bytes
  );
  if (invalid) {
    throw new UploadBatchAdmissionError('Upload batch contains an unverified or size-mismatched file', 409, {
      batch_id: batchId,
      client_upload_id: invalid.client_upload_id,
      upload_state: invalid.state,
      source_size_bytes: invalid.source_size_bytes,
      verified_size_bytes: invalid.verified_size_bytes,
    });
  }

  // This conditional update is the concurrency claim. Exactly one caller can
  // transition a ready batch to dispatching; a second request receives no row.
  const { data: claimed, error: claimError } = await supabaseAdmin
    .from('upload_batches')
    .update({ state: 'dispatching' })
    .eq('batch_id', batchId)
    .eq('state', 'ready')
    .eq('expected_file_count', row.expected_file_count)
    .eq('verified_file_count', row.expected_file_count)
    .select('batch_id')
    .maybeSingle();
  if (claimError) throw new Error(`Could not claim upload batch: ${claimError.message}`);
  if (!claimed) {
    throw new UploadBatchAdmissionError('Upload batch was already claimed by another dispatch', 409, { batch_id: batchId });
  }

  return {
    batch_id: batchId,
    expected_file_count: row.expected_file_count,
    verified_file_count: row.verified_file_count,
    grouping_type: row.grouping_type,
    session_id: row.session_id,
    athlete_id: row.athlete_id,
    input_objects: uploadFiles.map((file) => ({
      client_upload_id: file.client_upload_id,
      r2_key: file.r2_key,
      source_filename: file.source_filename,
      source_size_bytes: file.source_size_bytes,
      verified_size_bytes: file.verified_size_bytes as number,
      source_fingerprint: file.source_fingerprint,
    })),
  };
}

export async function releaseUploadBatchClaim(batchId: string): Promise<void> {
  const { error } = await supabaseAdmin
    .from('upload_batches')
    .update({ state: 'ready' })
    .eq('batch_id', batchId)
    .eq('state', 'dispatching');
  if (error) throw new Error(`Could not release upload batch claim: ${error.message}`);
}

export async function markUploadBatchDispatched(batchId: string): Promise<void> {
  const { data, error } = await supabaseAdmin
    .from('upload_batches')
    .update({ state: 'dispatched' })
    .eq('batch_id', batchId)
    .eq('state', 'dispatching')
    .select('batch_id')
    .maybeSingle();
  if (error) throw new Error(`Could not mark upload batch dispatched: ${error.message}`);
  if (!data) throw new Error('Upload batch dispatch claim was lost before acknowledgement');
}
