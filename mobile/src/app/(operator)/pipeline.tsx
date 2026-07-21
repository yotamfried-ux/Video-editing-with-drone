import React, { useCallback, useEffect, useState } from 'react';
import { View, StyleSheet, ScrollView, Alert, Platform, Pressable } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import * as FileSystem from 'expo-file-system';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { PipelineBar } from '@/features/operator/components/PipelineBar';
import { PipelineRunsCard } from '@/features/operator/components/PipelineRunsCard';
import { DeliveryStatusCard } from '@/features/operator/components/DeliveryStatusCard';
import { usePipelineStatus } from '@/features/operator/hooks/usePipelineStatus';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import {
  clearPersistedMultipartBatch,
  loadActiveMultipartBatch,
  resumeMultipartUpload,
} from '@/features/operator/lib/resumableMultipartUpload';
import {
  isRetryableUploadError,
  runQueue,
  UploadHttpError,
  withRetry,
} from '@/features/operator/lib/uploadQueue';
import type {
  OperatorUploadInitResponse,
  PipelineDispatchResponse,
  PipelineResetResponse,
  PipelineRun,
  ReprocessListResponse,
  ReprocessRow,
} from '@/features/operator/types/contracts';
import { Colors, Spacing } from '@/shared/constants/theme';

const STAGES = ['idle', 'downloading', 'analyzing', 'editing', 'qa', 'uploading', 'done'];
const UPLOAD_CONCURRENCY_LIMIT = 1;
const EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1;
const MAX_UPLOAD_BATCH_FILES = 20;
const MAX_UPLOAD_ATTEMPTS = 3;
const UPLOAD_RETRY_BACKOFF_CAPS_MS = [2000, 5000];
const VIDEO_FILE_EXTENSIONS = new Set([
  '.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm', '.mts', '.m2ts', '.mpg', '.mpeg',
]);

type UploadSession = OperatorUploadInitResponse & {
  mimeType?: string | null;
  storage_key?: string;
  storage_backend?: 'r2' | 'drive' | string;
  upload_mode?: 'multipart_resumable' | 'single_put';
  multipart_upload_id?: string | null;
  part_size_bytes?: number | null;
  multipart_reused?: boolean;
  already_complete?: boolean;
  existing_size_bytes?: number | null;
};

type UploadInit = UploadSession & { uploads?: UploadSession[] };
type UploadVerify = { ok: boolean; exists: boolean; size?: number | null; storage_key?: string; r2_status?: number };
type UploadItemStatus = 'queued' | 'initializing' | 'uploading' | 'verified' | 'failed';

type UploadFileState = {
  id: string;
  uri: string;
  filename: string;
  mimeType: string;
  progress: number;
  status: UploadItemStatus;
  batch_id?: string | null;
  error?: string | null;
  requiresLocalCopy?: boolean;
  externalSource?: boolean;
  storage_key?: string | null;
  sourceSizeBytes?: number | null;
  attempt?: number;
};

type ExternalVideoCandidate = {
  id: string;
  uri: string;
  filename: string;
  mimeType: string;
  selected: boolean;
};

type PreparedUpload = { uri: string; cleanup: () => Promise<void> };

const STATUS_LABEL: Record<string, string> = {
  pending: 'Waiting for next run',
  queued: 'Re-editing now',
  done: 'Done',
  source_not_found: 'Source not found',
};

const RUN_STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  no_input: 'No input',
  dispatch_failed: 'Dispatch failed',
};

const UPLOAD_STATUS_LABEL: Record<UploadItemStatus, string> = {
  queued: 'Queued',
  initializing: 'Preparing',
  uploading: 'Uploading',
  verified: 'Verified',
  failed: 'Failed',
};

function terminalStageForRun(run: PipelineRun | null): string {
  if (!run) return 'idle';
  if (run.status === 'succeeded') return 'done';
  if (run.status === 'failed' || run.status === 'dispatch_failed') return 'failed';
  if (run.status === 'no_input') return 'no_input';
  return run.stage ?? 'idle';
}

function displayProgressForRun(run: PipelineRun | null): number {
  if (!run) return 0;
  if (run.progress != null) return run.progress;
  if (['succeeded', 'failed', 'dispatch_failed', 'no_input'].includes(run.status)) return 1;
  return 0;
}

function latestRunLabel(run: PipelineRun): string {
  return `${RUN_STATUS_LABEL[run.status] ?? run.status} · ${run.id.slice(0, 8)}`;
}

function selectedAssetFilename(asset: ImagePicker.ImagePickerAsset, index: number): string {
  return asset.fileName ?? `footage_${Date.now()}_${index + 1}.mp4`;
}

function selectedAssetMimeType(asset: ImagePicker.ImagePickerAsset): string {
  return asset.mimeType ?? 'video/mp4';
}

function selectedAssetSize(asset: ImagePicker.ImagePickerAsset): number | null {
  const value = Number((asset as ImagePicker.ImagePickerAsset & { fileSize?: number }).fileSize);
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}

function filenameFromDocumentUri(uri: string, index: number): string {
  try {
    const decoded = decodeURIComponent(uri.split('?')[0]);
    const candidate = decoded.split('/').filter(Boolean).pop();
    if (candidate && candidate.includes('.')) return candidate;
  } catch {
    // Fall through to a deterministic fallback for malformed Android URIs.
  }
  return `external_footage_${Date.now()}_${index + 1}.mp4`;
}

function fileExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf('.');
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : '';
}

function isSupportedVideoFilename(filename: string): boolean {
  return VIDEO_FILE_EXTENSIONS.has(fileExtension(filename));
}

function mimeTypeForFilename(filename: string): string {
  switch (fileExtension(filename)) {
    case '.mov': return 'video/quicktime';
    case '.m4v': return 'video/x-m4v';
    case '.avi': return 'video/x-msvideo';
    case '.mkv': return 'video/x-matroska';
    case '.webm': return 'video/webm';
    case '.mts':
    case '.m2ts': return 'video/mp2t';
    case '.mpg':
    case '.mpeg': return 'video/mpeg';
    default: return 'video/mp4';
  }
}

function cacheSafeFilename(filename: string): string {
  return filename.replace(/[^a-zA-Z0-9._-]/g, '_');
}

function newClientBatchId(): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  return `batch_mobile_${stamp}_${Math.random().toString(36).slice(2, 10)}`;
}

function retryableUploadLifecycleError(error: unknown): boolean {
  if (error instanceof UploadHttpError && error.status === 409 && /no longer exists/i.test(error.message)) return true;
  return isRetryableUploadError(error);
}

export default function PipelineScreen() {
  const router = useRouter();
  const {
    status,
    latestRun,
    globalLiveStale,
    globalLiveStaleReason,
    loading: statusLoading,
    error: statusError,
  } = usePipelineStatus();
  const meta = (status?.meta ?? {}) as Record<string, unknown>;
  const displayStage = globalLiveStale && latestRun ? terminalStageForRun(latestRun) : status?.stage ?? 'idle';
  const displayProgress = globalLiveStale && latestRun ? displayProgressForRun(latestRun) : status?.progress ?? 0;

  const handleOperatorError = (error: unknown) => {
    const message = error instanceof Error ? error.message : 'Unknown error';
    if (message.includes('secret not set')) {
      Alert.alert('Operator secret required', message, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Go to Settings', onPress: () => router.push('/(operator)/settings' as never) },
      ]);
    } else {
      Alert.alert('Failed', message);
    }
  };

  const [requests, setRequests] = useState<ReprocessRow[]>([]);
  const [triggering, setTriggering] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [selectingExternalStorage, setSelectingExternalStorage] = useState(false);
  const [retryingFailedUploads, setRetryingFailedUploads] = useState(false);
  const [externalCandidates, setExternalCandidates] = useState<ExternalVideoCandidate[]>([]);
  const [uploadItems, setUploadItems] = useState<UploadFileState[]>([]);
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);
  const [lastBatchId, setLastBatchId] = useState<string | null>(null);

  const updateUploadItem = useCallback((id: string, patch: Partial<UploadFileState>) => {
    setUploadItems((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }, []);

  const loadRequests = useCallback(async () => {
    try {
      const { requests: data } = await operatorFetch<ReprocessListResponse>('/api/operator/reprocess');
      setRequests(data ?? []);
    } catch {
      setRequests([]);
    }
  }, []);

  useEffect(() => {
    loadRequests();
    const timer = setInterval(loadRequests, 15000);
    return () => clearInterval(timer);
  }, [loadRequests]);

  useEffect(() => {
    let mounted = true;
    loadActiveMultipartBatch().then((restored) => {
      if (!mounted || !restored) return;
      setActiveBatchId(restored.batchId);
      setUploadItems(restored.uploads.map((record) => ({
        id: record.clientUploadId,
        uri: record.sourceUri,
        filename: record.filename,
        mimeType: record.mimeType,
        progress: Math.min(100, Math.round((record.uploadedBytes / Math.max(record.sourceSizeBytes, 1)) * 100)),
        status: record.status === 'verified' ? 'verified' : 'failed',
        batch_id: record.batchId,
        error: record.status === 'verified' ? null : record.error ?? 'Interrupted upload ready to resume',
        externalSource: record.externalSource,
        requiresLocalCopy: record.externalSource,
        storage_key: record.storageKey,
        sourceSizeBytes: record.sourceSizeBytes,
      })));
    }).catch(() => {
      // Persistence recovery is best-effort; the operator can select footage again.
    });
    return () => { mounted = false; };
  }, []);

  const unresolvedUploads = uploadItems.some((item) => item.status !== 'verified');

  const runPipeline = async () => {
    if (uploadItems.length > 0 && unresolvedUploads) {
      Alert.alert('Uploads incomplete', 'Pipeline start is blocked until every selected upload is verified.');
      return;
    }

    setTriggering(true);
    try {
      const result = await operatorFetch<PipelineDispatchResponse>('/api/operator/pipeline/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: activeBatchId }),
      });
      setLastRunId(result.pipeline_run_id);
      const finishedBatch = result.batch_id ?? activeBatchId;
      if (finishedBatch) {
        await clearPersistedMultipartBatch(finishedBatch);
        setLastBatchId(finishedBatch);
        setActiveBatchId(null);
        setUploadItems([]);
      }
      Alert.alert('Pipeline triggered', `Run ${result.pipeline_run_id.slice(0, 8)} starts within a few seconds. Watch Recent pipeline runs for this run.`);
    } catch (error) {
      handleOperatorError(error);
    } finally {
      setTriggering(false);
    }
  };

  const confirmReset = () => {
    Alert.alert('Reset and rerun', 'Choose reset scope:', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Standard reset', onPress: () => resetAndRerun(false) },
      { text: 'Full clean', style: 'destructive', onPress: () => resetAndRerun(true) },
    ]);
  };

  const resetAndRerun = async (fullClean: boolean) => {
    setResetting(true);
    try {
      const result = await operatorFetch<PipelineResetResponse>('/api/operator/pipeline/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_clean: fullClean, batch_id: lastBatchId ?? activeBatchId }),
      });
      setLastRunId(result.pipeline_run_id);
      if (result.batch_id) setLastBatchId(result.batch_id);
      Alert.alert('Reset triggered', `${result.full_clean ? 'Full clean' : 'Reset'} run ${result.pipeline_run_id.slice(0, 8)} started.`);
    } catch (error) {
      handleOperatorError(error);
    } finally {
      setResetting(false);
    }
  };

  const sourceSizeForItem = async (item: UploadFileState): Promise<number> => {
    if (Number.isSafeInteger(item.sourceSizeBytes) && Number(item.sourceSizeBytes) > 0) return Number(item.sourceSizeBytes);
    const info = await FileSystem.getInfoAsync(item.uri);
    if (!info.exists || info.isDirectory || !Number.isSafeInteger(info.size) || info.size <= 0) {
      throw new Error(`Cannot determine the source size for ${item.filename}`);
    }
    updateUploadItem(item.id, { sourceSizeBytes: info.size });
    return info.size;
  };

  const prepareLegacyUpload = async (item: UploadFileState): Promise<PreparedUpload> => {
    if (!item.requiresLocalCopy) return { uri: item.uri, cleanup: async () => {} };
    if (!FileSystem.cacheDirectory) throw new Error('App cache is unavailable for the selected SD / USB video.');

    const temporaryUri = `${FileSystem.cacheDirectory}sportreel-upload-${Date.now()}-${cacheSafeFilename(item.id)}-${cacheSafeFilename(item.filename)}`;
    updateUploadItem(item.id, { status: 'initializing', error: null });
    await FileSystem.copyAsync({ from: item.uri, to: temporaryUri });
    return {
      uri: temporaryUri,
      cleanup: async () => {
        try {
          await FileSystem.deleteAsync(temporaryUri, { idempotent: true });
        } catch {
          // Cleanup must never replace the upload result.
        }
      },
    };
  };

  const requestUploadSession = async (item: UploadFileState, batchId: string, sourceSizeBytes: number): Promise<UploadSession> => {
    const uploadInit = await operatorFetch<UploadInit>('/api/operator/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: item.filename,
        mimeType: item.mimeType,
        batch_id: batchId,
        upload_mode: 'multipart_resumable',
        client_upload_id: item.id,
        source_size_bytes: sourceSizeBytes,
      }),
    });
    return uploadInit.uploads?.[0] ?? uploadInit;
  };

  const uploadLegacyPreparedFile = async (
    item: UploadFileState,
    session: UploadSession,
    uploadUri: string,
    sourceSizeBytes: number,
  ) => {
    if (!session.uploadUrl) throw new Error(`Missing upload URL for ${item.filename}`);
    updateUploadItem(item.id, {
      status: 'uploading',
      batch_id: session.batch_id,
      storage_key: session.storage_key ?? null,
      error: null,
    });

    const task = FileSystem.createUploadTask(
      session.uploadUrl,
      uploadUri,
      {
        httpMethod: 'PUT',
        uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
        headers: { 'Content-Type': item.mimeType },
      },
      (progress) => {
        const expected = progress.totalBytesExpectedToSend || 1;
        updateUploadItem(item.id, { progress: Math.round((progress.totalBytesSent / expected) * 100) });
      },
    );

    const result = await task.uploadAsync();
    if (!result) throw new Error('Upload ended without an HTTP response');
    if (result.status >= 300) throw new UploadHttpError(result.status);

    if (session.storage_key) {
      const verified = await operatorFetch<UploadVerify>('/api/operator/upload/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ storage_key: session.storage_key, expected_size_bytes: sourceSizeBytes }),
      });
      if (!verified.exists || verified.size !== sourceSizeBytes) {
        throw new Error(`Upload size verification failed for ${session.storage_key}: expected ${sourceSizeBytes}, found ${verified.size ?? 'missing'}`);
      }
    }

    updateUploadItem(item.id, {
      status: 'verified',
      progress: 100,
      batch_id: session.batch_id,
      storage_key: session.storage_key ?? null,
      sourceSizeBytes,
      error: null,
    });
  };

  const uploadItemWithRetries = async (item: UploadFileState, batchId: string): Promise<void> => {
    let prepared: PreparedUpload | null = null;
    try {
      const sourceSizeBytes = await sourceSizeForItem(item);
      await withRetry(
        async () => {
          const session = await requestUploadSession(item, batchId, sourceSizeBytes);
          if (session.storage_backend === 'r2' && session.upload_mode === 'multipart_resumable') {
            updateUploadItem(item.id, {
              status: 'uploading',
              batch_id: session.batch_id ?? batchId,
              storage_key: session.storage_key ?? null,
              sourceSizeBytes,
              error: null,
            });
            await resumeMultipartUpload({
              clientUploadId: item.id,
              batchId: session.batch_id ?? batchId,
              sourceUri: item.uri,
              filename: item.filename,
              mimeType: item.mimeType,
              sourceSizeBytes,
              externalSource: Boolean(item.externalSource),
              session,
              onProgress: (sent, total) => updateUploadItem(item.id, {
                status: 'uploading',
                progress: Math.min(100, Math.round((sent / Math.max(total, 1)) * 100)),
                storage_key: session.storage_key ?? null,
              }),
            });
            updateUploadItem(item.id, {
              status: 'verified',
              progress: 100,
              batch_id: session.batch_id ?? batchId,
              storage_key: session.storage_key ?? null,
              sourceSizeBytes,
              error: null,
            });
            return;
          }

          prepared ??= await prepareLegacyUpload(item);
          await uploadLegacyPreparedFile(item, session, prepared.uri, sourceSizeBytes);
        },
        {
          maxAttempts: MAX_UPLOAD_ATTEMPTS,
          backoffMs: UPLOAD_RETRY_BACKOFF_CAPS_MS,
          shouldRetry: retryableUploadLifecycleError,
          onAttempt: (attempt) => updateUploadItem(item.id, {
            status: 'initializing',
            attempt,
            error: attempt > 1 ? `Resuming automatically (${attempt}/${MAX_UPLOAD_ATTEMPTS})` : null,
          }),
        },
      );
    } catch (error) {
      updateUploadItem(item.id, {
        status: 'failed',
        error: error instanceof Error ? error.message : 'Upload failed',
      });
      throw error;
    } finally {
      if (prepared) await prepared.cleanup();
    }
  };

  const runUploadQueue = async (items: UploadFileState[], startingBatchId: string | null) => {
    const stableBatchId = startingBatchId ?? newClientBatchId();
    setActiveBatchId(stableBatchId);
    const concurrency = items.some((item) => item.externalSource)
      ? EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT
      : UPLOAD_CONCURRENCY_LIMIT;
    const results = await runQueue(items, (item) => uploadItemWithRetries(item, stableBatchId), concurrency);
    return { stableBatchId, results };
  };

  const retryUploadItem = async (item: UploadFileState) => {
    try {
      await uploadItemWithRetries(item, item.batch_id ?? activeBatchId ?? newClientBatchId());
    } catch (error) {
      handleOperatorError(error);
    }
  };

  const retryAllFailedUploads = async () => {
    const failedItems = uploadItems.filter((item) => item.status === 'failed');
    if (!failedItems.length) return;

    setRetryingFailedUploads(true);
    try {
      const { results } = await runUploadQueue(failedItems, activeBatchId);
      const failedAgain = results.filter((result) => result.status === 'rejected').length;
      if (failedAgain) {
        Alert.alert('Some uploads still failing', `${failedAgain} of ${failedItems.length} files failed again. Check the connection and retry when stable.`);
      } else {
        Alert.alert('Uploads verified', `${failedItems.length} previously failed files resumed and verified.`);
      }
    } finally {
      setRetryingFailedUploads(false);
    }
  };

  const uploadSelectedItems = async (items: UploadFileState[]) => {
    if (items.length > MAX_UPLOAD_BATCH_FILES) {
      Alert.alert('Too many videos', `Select at most ${MAX_UPLOAD_BATCH_FILES} videos for one batch.`);
      return;
    }
    if (uploadItems.some((item) => item.status !== 'verified')) {
      Alert.alert('Resolve current uploads', 'Retry or complete every failed upload before adding more footage to this batch.');
      return;
    }

    setUploadItems(items);
    const { stableBatchId, results } = await runUploadQueue(items, activeBatchId);
    const failed = results.filter((result) => result.status === 'rejected').length;
    if (failed) {
      Alert.alert('Some uploads failed', `${failed} of ${items.length} files failed after part-level retries. Use Retry all failed to resume only missing parts.`);
      return;
    }
    Alert.alert('Uploaded to queue', `${items.length} files verified in RAW batch ${stableBatchId.slice(0, 24)}. Run the pipeline only when the batch is complete.`);
  };

  const uploadFootage = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Permission required', 'Please allow access to your media library.');
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: 'videos',
      allowsMultipleSelection: true,
      videoMaxDuration: 7200,
    });
    if (result.canceled || !result.assets?.length) return;

    const items: UploadFileState[] = result.assets.map((asset, index) => {
      const filename = selectedAssetFilename(asset, index);
      return {
        id: `${Date.now()}_${index}_${filename}`,
        uri: asset.uri,
        filename,
        mimeType: selectedAssetMimeType(asset),
        sourceSizeBytes: selectedAssetSize(asset),
        progress: 0,
        status: 'queued',
        batch_id: activeBatchId,
        error: null,
        externalSource: false,
      };
    });
    await uploadSelectedItems(items);
  };

  const toggleExternalCandidate = (id: string) => {
    setExternalCandidates((candidates) => candidates.map((candidate) => (
      candidate.id === id ? { ...candidate, selected: !candidate.selected } : candidate
    )));
  };

  const uploadSelectedExternalVideos = async () => {
    const selected = externalCandidates.filter((candidate) => candidate.selected);
    if (!selected.length) {
      Alert.alert('Select videos', 'Choose at least one video from the folder before uploading.');
      return;
    }

    const items: UploadFileState[] = selected.map((candidate, index) => ({
      id: `${Date.now()}_external_${index}_${candidate.filename}`,
      uri: candidate.uri,
      filename: candidate.filename,
      mimeType: candidate.mimeType,
      progress: 0,
      status: 'queued',
      batch_id: activeBatchId,
      error: null,
      externalSource: true,
      requiresLocalCopy: true,
    }));
    setExternalCandidates([]);
    await uploadSelectedItems(items);
  };

  const uploadExternalStorageFolder = async () => {
    if (Platform.OS !== 'android') {
      Alert.alert('Android only', 'Direct SD / USB video selection is currently available on Android.');
      return;
    }

    setSelectingExternalStorage(true);
    try {
      const permission = await FileSystem.StorageAccessFramework.requestDirectoryPermissionsAsync();
      if (!permission.granted) return;
      const documentUris = await FileSystem.StorageAccessFramework.readDirectoryAsync(permission.directoryUri);
      const videos = documentUris
        .map((uri, index) => ({ uri, filename: filenameFromDocumentUri(uri, index) }))
        .filter((document) => isSupportedVideoFilename(document.filename))
        .sort((left, right) => left.filename.localeCompare(right.filename));

      if (!videos.length) {
        setExternalCandidates([]);
        Alert.alert('No videos found', 'Choose the SD / USB folder that directly contains the video clips.');
        return;
      }
      setExternalCandidates(videos.map((document, index) => ({
        id: `${permission.directoryUri}_${index}_${document.filename}`,
        uri: document.uri,
        filename: document.filename,
        mimeType: mimeTypeForFilename(document.filename),
        selected: false,
      })));
    } catch (error) {
      handleOperatorError(error);
    } finally {
      setSelectingExternalStorage(false);
    }
  };

  const uploadBusy = uploadItems.some((item) => ['queued', 'initializing', 'uploading'].includes(item.status));
  const failedUploads = uploadItems.filter((item) => item.status === 'failed');
  const verifiedUploads = uploadItems.filter((item) => item.status === 'verified').length;
  const pipelineBlockedByUploads = uploadItems.length > 0 && verifiedUploads !== uploadItems.length;
  const busy = triggering || resetting || selectingExternalStorage || retryingFailedUploads || uploadBusy;

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <ScrollView contentContainerStyle={{ gap: Spacing.md, paddingBottom: Spacing.xl }}>
          <Text variant="display">Pipeline</Text>
          <Text variant="caption" color={statusError ? Colors.danger : Colors.textSecondary}>
            {statusError
              ? `Status unavailable: ${statusError}`
              : statusLoading
                ? 'Loading global live status...'
                : `Global live status · polls every 5s${status?.updated_at ? ` · updated ${new Date(status.updated_at).toLocaleTimeString()}` : ''}`}
          </Text>

          <Card bordered style={{ gap: Spacing.md }}>
            <View style={{ gap: Spacing.xs }}>
              <Text variant="title">Global live progress</Text>
              <Text variant="caption" color={Colors.textSecondary}>
                Upload all footage for a batch first. Run the pipeline only when every selected upload is verified.
              </Text>
              {activeBatchId && <Text variant="caption" color={Colors.accent}>Current upload batch: {activeBatchId.slice(0, 24)}</Text>}
              {lastBatchId && !activeBatchId && <Text variant="caption" color={Colors.textSecondary}>Last completed batch: {lastBatchId.slice(0, 24)}</Text>}
            </View>
            <PipelineBar stage={displayStage} progress={displayProgress} />
            {globalLiveStale && latestRun && (
              <View style={styles.staleNotice}>
                <Text variant="caption" color={latestRun.status === 'succeeded' || latestRun.status === 'no_input' ? Colors.success : Colors.danger}>
                  {globalLiveStaleReason ?? `Global live signal is stale; latest run ${latestRun.id.slice(0, 8)} finished with status ${latestRun.status}.`}
                </Text>
                <Text variant="caption" color={Colors.textSecondary}>Showing verified latest run status instead: {latestRunLabel(latestRun)}</Text>
              </View>
            )}
            {lastRunId && <Text variant="caption" color={Colors.textSecondary}>Last app-triggered run: {lastRunId.slice(0, 8)}</Text>}

            <Button label={triggering ? 'Triggering...' : 'Run pipeline now'} onPress={runPipeline} disabled={busy || pipelineBlockedByUploads} variant="secondary" style={{ height: 44 }} />
            <Button label={uploadBusy ? `Uploading ${verifiedUploads}/${uploadItems.length}...` : 'Upload from gallery'} onPress={uploadFootage} disabled={busy} variant="secondary" style={{ height: 44 }} />

            {Platform.OS === 'android' && (
              <>
                <Button label={selectingExternalStorage ? 'Opening SD / USB...' : 'Choose videos from SD / USB'} onPress={uploadExternalStorageFolder} disabled={busy} variant="secondary" style={{ height: 44 }} />
                <Text variant="caption" color={Colors.textSecondary}>Choose the folder on the card or USB drive, then select only the videos to upload. Completed parts resume after an interruption.</Text>
                {externalCandidates.length > 0 && (
                  <View style={styles.externalSelectionPanel}>
                    <View style={styles.metaRow}>
                      <Text variant="caption" color={Colors.textPrimary}>Select videos · {externalCandidates.filter((candidate) => candidate.selected).length}/{externalCandidates.length}</Text>
                      <Button label="Clear" onPress={() => setExternalCandidates((candidates) => candidates.map((candidate) => ({ ...candidate, selected: false })))} disabled={busy} variant="ghost" style={{ height: 34 }} />
                    </View>
                    <Button label="Select all" onPress={() => setExternalCandidates((candidates) => candidates.map((candidate) => ({ ...candidate, selected: true })))} disabled={busy} variant="ghost" style={{ height: 36 }} />
                    {externalCandidates.map((candidate) => (
                      <Pressable
                        key={candidate.id}
                        onPress={() => toggleExternalCandidate(candidate.id)}
                        disabled={busy}
                        accessibilityRole="checkbox"
                        accessibilityState={{ checked: candidate.selected, disabled: busy }}
                        style={({ pressed }) => [
                          styles.externalSelectionRow,
                          candidate.selected && styles.externalSelectionRowSelected,
                          pressed && !busy && { opacity: 0.75 },
                        ]}
                      >
                        <View style={[styles.selectionIndicator, candidate.selected && styles.selectionIndicatorSelected]}>
                          <Text variant="caption" color={candidate.selected ? Colors.background : Colors.textSecondary}>{candidate.selected ? '✓' : ''}</Text>
                        </View>
                        <Text variant="caption" color={Colors.textPrimary} numberOfLines={2} style={{ flex: 1 }}>{candidate.filename}</Text>
                      </Pressable>
                    ))}
                    <Button label={`Upload selected (${externalCandidates.filter((candidate) => candidate.selected).length})`} onPress={uploadSelectedExternalVideos} disabled={busy || !externalCandidates.some((candidate) => candidate.selected)} variant="secondary" style={{ height: 44 }} />
                  </View>
                )}
              </>
            )}

            <Button label={resetting ? 'Resetting...' : 'Reset and rerun'} onPress={confirmReset} disabled={busy} variant="secondary" style={{ height: 44, borderColor: Colors.danger }} />

            {uploadItems.length > 0 && (
              <View style={{ gap: Spacing.sm }}>
                <View style={styles.metaRow}>
                  <Text variant="caption" color={failedUploads.length ? Colors.danger : Colors.textSecondary}>Upload batch progress · {verifiedUploads}/{uploadItems.length} verified</Text>
                  {failedUploads.length > 0 && <Button label={retryingFailedUploads ? 'Retrying...' : `Resume all failed (${failedUploads.length})`} onPress={retryAllFailedUploads} disabled={busy} variant="ghost" style={{ height: 36 }} />}
                </View>
                {pipelineBlockedByUploads && <Text variant="caption" color={Colors.danger}>Pipeline start is blocked until every selected upload is verified.</Text>}
                {uploadItems.map((item) => (
                  <View key={item.id} style={styles.uploadRow}>
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text variant="caption" color={Colors.textPrimary} numberOfLines={1}>{item.filename}</Text>
                      <Text variant="caption" color={item.status === 'failed' ? Colors.danger : Colors.textSecondary}>
                        {UPLOAD_STATUS_LABEL[item.status]} · {item.progress}%{item.attempt ? ` · attempt ${item.attempt}/${MAX_UPLOAD_ATTEMPTS}` : ''}{item.error ? ` · ${item.error}` : ''}
                      </Text>
                    </View>
                    {item.status === 'failed' && <Button label="Resume" onPress={() => retryUploadItem(item)} disabled={busy} variant="ghost" style={{ height: 36 }} />}
                  </View>
                ))}
              </View>
            )}
          </Card>

          <PipelineRunsCard />
          <DeliveryStatusCard />

          <Card bordered style={{ gap: Spacing.sm }}>
            <Text variant="title">Global live stages</Text>
            {STAGES.map((stage) => {
              const currentIndex = STAGES.indexOf(displayStage);
              const isCurrent = displayStage === stage;
              const done = currentIndex >= 0 && STAGES.indexOf(stage) < currentIndex;
              return (
                <View key={stage} style={styles.stageRow}>
                  <View style={[styles.dot, done && { backgroundColor: Colors.success }, isCurrent && { backgroundColor: Colors.accent }]} />
                  <Text variant="body" color={isCurrent ? Colors.textPrimary : Colors.textSecondary}>{stage.toUpperCase()}</Text>
                </View>
              );
            })}
          </Card>

          {requests.length > 0 && (
            <Card bordered style={{ gap: Spacing.sm }}>
              <Text variant="title">Re-edit requests</Text>
              {requests.map((request) => (
                <View key={request.id} style={{ gap: 2 }}>
                  <View style={styles.metaRow}>
                    <Text variant="caption" color={Colors.textPrimary} numberOfLines={1} style={{ flex: 1 }}>{request.draft_name || request.id.slice(0, 8)}</Text>
                    <Text variant="caption" color={Colors.accent}>{STATUS_LABEL[request.status] ?? request.status}</Text>
                  </View>
                  {!!request.notes && <Text variant="caption" color={Colors.textSecondary} numberOfLines={2}>"{request.notes}"</Text>}
                </View>
              ))}
            </Card>
          )}

          {Object.keys(meta).length > 0 && (
            <Card bordered style={{ gap: Spacing.xs }}>
              <Text variant="title">Global live metadata</Text>
              <Text variant="caption" color={Colors.textSecondary}>Metadata from the singleton live signal. Run history above is the durable action log.</Text>
              <Spacer size={Spacing.xs} />
              {Object.entries(meta).map(([key, value]) => (
                <View key={key} style={styles.metaRow}>
                  <Text variant="caption" color={Colors.textSecondary}>{key}</Text>
                  <Text variant="caption" color={Colors.accent}>{String(value)}</Text>
                </View>
              ))}
            </Card>
          )}
        </ScrollView>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  stageRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: Colors.cardBorder },
  metaRow: { flexDirection: 'row', justifyContent: 'space-between', gap: Spacing.sm },
  uploadRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 8,
    padding: Spacing.sm,
  },
  externalSelectionPanel: {
    gap: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 8,
    padding: Spacing.sm,
  },
  externalSelectionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 8,
    padding: Spacing.sm,
  },
  externalSelectionRowSelected: { borderColor: Colors.accent },
  selectionIndicator: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  selectionIndicatorSelected: { backgroundColor: Colors.accent, borderColor: Colors.accent },
  staleNotice: {
    gap: Spacing.xs,
    borderLeftWidth: 3,
    borderLeftColor: Colors.accent,
    paddingLeft: Spacing.sm,
  },
});
