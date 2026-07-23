import { supabaseAdmin } from '@/lib/supabase-admin';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

type JsonObject = Record<string, unknown>;

function rpcObject(data: unknown, operation: string): JsonObject {
  const value = Array.isArray(data) && data.length === 1 ? data[0] : data;
  if (!value || typeof value !== 'object') {
    throw new SourceUploadManifestError(`${operation} returned invalid state`, 503);
  }
  return value as JsonObject;
}

function statusForRpcError(message: string): number {
  if (/not found/i.test(message)) return 404;
  if (/not ready|cannot accept|cannot run|invalid|exceed|mismatch|between|multiple/i.test(message)) return 409;
  return 503;
}

async function uniqueBatchIdForStates(states: string[]): Promise<string | null> {
  const { data, error } = await supabaseAdmin
    .from('upload_batches')
    .select('batch_id,state')
    .in('state', states)
    .is('pipeline_run_id', null)
    .order('updated_at', { ascending: false })
    .limit(2);
  if (error) {
    throw new SourceUploadManifestError(`Could not resolve durable upload batch: ${error.message}`, 503);
  }
  if (!data?.length) return null;
  if (data.length > 1) {
    throw new SourceUploadManifestError(
      `Multiple durable upload batches are active (${data.map((row) => row.batch_id).join(', ')}); choose an explicit batch before continuing`,
      409,
    );
  }
  return String(data[0].batch_id);
}

export async function resolveUploadBatchId(
  requestedBatchId?: string | null,
): Promise<string | null> {
  const requested = (requestedBatchId ?? '').trim();
  if (requested) return requested;
  return uniqueBatchIdForStates(['collecting', 'uploading', 'ready']);
}

export async function resolveReadyUploadBatchId(
  requestedBatchId?: string | null,
): Promise<string> {
  const requested = (requestedBatchId ?? '').trim();
  if (requested) return requested;
  const resolved = await uniqueBatchIdForStates(['ready']);
  if (!resolved) {
    throw new SourceUploadManifestError(
      'No unique size-verified upload batch is ready. Finish or repair the current uploads before starting the pipeline.',
      409,
    );
  }
  return resolved;
}

export async function refreshUploadBatch(batchId: string): Promise<JsonObject> {
  const { data, error } = await supabaseAdmin.rpc('refresh_upload_batch_state', {
    p_batch_id: batchId,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Could not refresh upload batch: ${error.message}`,
      statusForRpcError(error.message),
    );
  }
  return rpcObject(data, 'Upload batch refresh');
}

export async function registerUploadBatch(input: {
  batchId: string;
  additionalFileCount: number;
  sourceKind: 'operator' | 'android_external' | 'gallery' | 'api';
  groupingKind: 'unassigned' | 'one_athlete' | 'session_multiple_athletes' | 'other';
}): Promise<JsonObject> {
  const { data, error } = await supabaseAdmin.rpc('register_upload_batch', {
    p_batch_id: input.batchId,
    p_additional_file_count: input.additionalFileCount,
    p_source_kind: input.sourceKind,
    p_grouping_kind: input.groupingKind,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Could not register upload batch: ${error.message}`,
      statusForRpcError(error.message),
    );
  }
  rpcObject(data, 'Upload batch registration');
  return refreshUploadBatch(input.batchId);
}

export async function removeSourceUploadsAfterSetupFailure(uploadIds: string[]): Promise<void> {
  if (!uploadIds.length) return;
  const { error } = await supabaseAdmin
    .from('source_uploads')
    .delete()
    .in('id', uploadIds);
  if (error) {
    throw new SourceUploadManifestError(
      `Could not remove failed source upload setup rows: ${error.message}`,
      503,
    );
  }
}

export async function assertUploadBatchReady(batchId: string): Promise<{
  batchId: string;
  expectedFileCount: number;
  inputManifest: JsonObject[];
}> {
  const { data, error } = await supabaseAdmin.rpc('assert_upload_batch_ready', {
    p_batch_id: batchId,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Upload batch is not ready: ${error.message}`,
      statusForRpcError(error.message),
    );
  }
  const result = rpcObject(data, 'Upload batch readiness');
  if (!Array.isArray(result.input_manifest)) {
    throw new SourceUploadManifestError('Upload batch readiness returned no input manifest', 503);
  }
  return {
    batchId: String(result.batch_id),
    expectedFileCount: Number(result.expected_file_count),
    inputManifest: result.input_manifest as JsonObject[],
  };
}

export async function markUploadBatchRunning(
  batchId: string,
  pipelineRunId: string,
): Promise<void> {
  const { error } = await supabaseAdmin.rpc('mark_upload_batch_running', {
    p_batch_id: batchId,
    p_pipeline_run_id: pipelineRunId,
  });
  if (error) {
    throw new SourceUploadManifestError(
      `Could not lock upload batch for pipeline run: ${error.message}`,
      statusForRpcError(error.message),
    );
  }
}

export async function releaseUploadBatchAfterDispatchFailure(
  batchId: string,
  pipelineRunId: string,
): Promise<void> {
  const { error } = await supabaseAdmin
    .from('upload_batches')
    .update({
      state: 'ready',
      pipeline_run_id: null,
      locked_at: null,
    })
    .eq('batch_id', batchId)
    .eq('pipeline_run_id', pipelineRunId)
    .eq('state', 'running');
  if (error) {
    throw new SourceUploadManifestError(
      `Could not release upload batch after dispatch failure: ${error.message}`,
      503,
    );
  }
}
