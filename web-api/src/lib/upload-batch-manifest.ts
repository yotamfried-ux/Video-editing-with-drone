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
  if (/not ready|cannot accept|cannot run|invalid|exceed|mismatch|between/i.test(message)) return 409;
  return 503;
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
  return rpcObject(data, 'Upload batch registration');
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
