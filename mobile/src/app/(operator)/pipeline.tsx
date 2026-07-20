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
const UPLOAD_CONCURRENCY_LIMIT = 3;
const EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1;
const VIDEO_FILE_EXTENSIONS = new Set([
  '.mp4',
  '.mov',
  '.m4v',
  '.avi',
  '.mkv',
  '.webm',
  '.mts',
  '.m2ts',
  '.mpg',
  '.mpeg',
]);

type UploadSession = OperatorUploadInitResponse & {
  mimeType?: string | null;
  storage_key?: string;
  storage_backend?: string;
};

type UploadInit = UploadSession & {
  uploads?: UploadSession[];
};

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
};

type ExternalVideoCandidate = {
  id: string;
  uri: string;
  filename: string;
  mimeType: string;
  selected: boolean;
};

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

function filenameFromDocumentUri(uri: string, index: number): string {
  try {
    const decoded = decodeURIComponent(uri.split('?')[0]);
    const candidate = decoded.split('/').filter(Boolean).pop();
    if (candidate && candidate.includes('.')) return candidate;
  } catch {
    // Fall through to a deterministic fallback when Android returns a malformed URI.
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
    case '.mov':
      return 'video/quicktime';
    case '.m4v':
      return 'video/x-m4v';
    case '.avi':
      return 'video/x-msvideo';
    case '.mkv':
      return 'video/x-matroska';
    case '.webm':
      return 'video/webm';
    case '.mts':
    case '.m2ts':
      return 'video/mp2t';
    case '.mpg':
    case '.mpeg':
      return 'video/mpeg';
    default:
      return 'video/mp4';
  }
}

function cacheSafeFilename(filename: string): string {
  return filename.replace(/[^a-zA-Z0-9._-]/g, '_');
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

  const handleOperatorError = (e: unknown) => {
    const msg = e instanceof Error ? e.message : 'Unknown error';
    if (msg.includes('secret not set')) {
      Alert.alert('Operator secret required', msg, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Go to Settings', onPress: () => router.push('/(operator)/settings' as never) },
      ]);
    } else {
      Alert.alert('Failed', msg);
    }
  };
  const [requests, setRequests] = useState<ReprocessRow[]>([]);
  const [triggering, setTriggering] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [selectingExternalStorage, setSelectingExternalStorage] = useState(false);
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
      const { requests: data } = await operatorFetch<ReprocessListResponse>(
        '/api/operator/reprocess'
      );
      setRequests(data ?? []);
    } catch {
      setRequests([]);
    }
  }, []);

  useEffect(() => {
    loadRequests();
    const t = setInterval(loadRequests, 15000);
    return () => clearInterval(t);
  }, [loadRequests]);

  const runPipeline = async () => {
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
        setLastBatchId(finishedBatch);
        setActiveBatchId(null);
      }
      Alert.alert('Pipeline triggered', `Run ${result.pipeline_run_id.slice(0, 8)} starts within a few seconds. Watch Recent pipeline runs for this run.`);
    } catch (e) {
      handleOperatorError(e);
    } finally {
      setTriggering(false);
    }
  };

  const confirmReset = () => {
    Alert.alert(
      'Reset and rerun',
      'Choose reset scope:',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Standard reset', onPress: () => resetAndRerun(false) },
        { text: 'Full clean', style: 'destructive', onPress: () => resetAndRerun(true) },
      ]
    );
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
      const scope = result.full_clean ? 'Full clean' : 'Reset';
      Alert.alert('Reset triggered', `${scope} run ${result.pipeline_run_id.slice(0, 8)} started. Watch Recent pipeline runs for this reset.`);
    } catch (e) {
      handleOperatorError(e);
    } finally {
      setResetting(false);
    }
  };

  const uploadAssetToSession = async (item: UploadFileState, session: UploadSession) => {
    if (!session.uploadUrl) throw new Error(`Missing upload URL for ${item.filename}`);

    let uploadUri = item.uri;
    let temporaryUploadUri: string | null = null;
    updateUploadItem(item.id, {
      status: item.requiresLocalCopy ? 'initializing' : 'uploading',
      progress: 0,
      batch_id: session.batch_id,
      error: null,
      filename: session.filename || item.filename,
    });

    try {
      if (item.requiresLocalCopy) {
        if (!FileSystem.cacheDirectory) {
          throw new Error('App cache is unavailable for the selected SD / USB video.');
        }
        temporaryUploadUri = `${FileSystem.cacheDirectory}sportreel-upload-${Date.now()}-${cacheSafeFilename(item.id)}-${cacheSafeFilename(item.filename)}`;
        await FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri });
        uploadUri = temporaryUploadUri;
        updateUploadItem(item.id, { status: 'uploading' });
      }

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
          const pct = Math.round((progress.totalBytesSent / expected) * 100);
          updateUploadItem(item.id, { progress: pct });
        }
      );
      const uploadResult = await task.uploadAsync();
      if (!uploadResult || uploadResult.status >= 300) {
        throw new Error(`Upload failed with status ${uploadResult?.status}`);
      }

      if (session.storage_key) {
        const verified = await operatorFetch<UploadVerify>('/api/operator/upload/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ storage_key: session.storage_key }),
        });
        if (!verified.exists) {
          throw new Error(`Upload finished but R2 verification failed for ${session.storage_key}`);
        }
      }

      updateUploadItem(item.id, { status: 'verified', progress: 100, batch_id: session.batch_id, error: null });
    } finally {
      if (temporaryUploadUri) {
        try {
          await FileSystem.deleteAsync(temporaryUploadUri, { idempotent: true });
        } catch {
          // Cache cleanup must not hide the upload result.
        }
      }
    }
  };

  const retryUploadItem = async (item: UploadFileState) => {
    updateUploadItem(item.id, { status: 'initializing', progress: 0, error: null });
    try {
      const uploadInit = await operatorFetch<UploadInit>(
        '/api/operator/upload',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: item.filename,
            mimeType: item.mimeType,
            batch_id: item.batch_id ?? activeBatchId,
          }),
        }
      );
      const session = uploadInit.uploads?.[0] ?? uploadInit;
      if (session.batch_id) setActiveBatchId(session.batch_id);
      await uploadAssetToSession(item, session);
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Upload failed';
      updateUploadItem(item.id, { status: 'failed', error: message });
      handleOperatorError(e);
    }
  };

  const uploadSelectedItems = async (items: UploadFileState[]) => {
    setUploadItems(items);

    try {
      setUploadItems((current) => current.map((item) => ({ ...item, status: 'initializing' })));
      const uploadInit = await operatorFetch<UploadInit>(
        '/api/operator/upload',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            files: items.map((item) => ({ filename: item.filename, mimeType: item.mimeType })),
            batch_id: activeBatchId,
          }),
        }
      );
      const sessions = uploadInit.uploads?.length ? uploadInit.uploads : [uploadInit];
      const batchId = uploadInit.batch_id ?? sessions[0]?.batch_id ?? activeBatchId;
      if (batchId) setActiveBatchId(batchId);

      const results: PromiseSettledResult<void>[] = new Array(items.length);
      let nextIndex = 0;
      const concurrencyLimit = items.some((item) => item.requiresLocalCopy)
        ? EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT
        : UPLOAD_CONCURRENCY_LIMIT;
      const workerCount = Math.min(concurrencyLimit, items.length);
      await Promise.all(
        Array.from({ length: workerCount }, async () => {
          while (nextIndex < items.length) {
            const index = nextIndex;
            nextIndex += 1;
            const item = items[index];
            const session = sessions[index];
            try {
              if (!item) continue;
              if (!session) throw new Error(`Missing upload session for ${item.filename}`);
              await uploadAssetToSession(item, session);
              results[index] = { status: 'fulfilled', value: undefined };
            } catch (reason) {
              results[index] = { status: 'rejected', reason };
            }
          }
        })
      );

      const failed = results.filter((uploadResult) => uploadResult.status === 'rejected');
      if (failed.length) {
        results.forEach((uploadResult, index) => {
          if (uploadResult.status === 'rejected') {
            updateUploadItem(items[index].id, {
              status: 'failed',
              error: uploadResult.reason instanceof Error ? uploadResult.reason.message : 'Upload failed',
            });
          }
        });
        Alert.alert('Some uploads failed', `${failed.length} of ${items.length} files failed. Retry failed files before running the pipeline.`);
        return;
      }

      Alert.alert(
        'Uploaded to queue',
        `${items.length} file${items.length === 1 ? '' : 's'} verified in RAW batch ${batchId?.slice(0, 16) ?? 'current'}. Upload more footage for this athlete/session, then tap Run pipeline now when the batch is ready.`
      );
    } catch (e) {
      setUploadItems((current) => current.map((item) => ({ ...item, status: 'failed', error: e instanceof Error ? e.message : 'Upload failed' })));
      handleOperatorError(e);
    }
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
        progress: 0,
        status: 'queued',
        batch_id: activeBatchId,
        error: null,
      };
    });
    await uploadSelectedItems(items);
  };

  const toggleExternalCandidate = (id: string) => {
    setExternalCandidates((candidates) =>
      candidates.map((candidate) =>
        candidate.id === id ? { ...candidate, selected: !candidate.selected } : candidate
      )
    );
  };

  const uploadSelectedExternalVideos = async () => {
    const selectedCandidates = externalCandidates.filter((candidate) => candidate.selected);
    if (!selectedCandidates.length) {
      Alert.alert('Select videos', 'Choose at least one video from the folder before uploading.');
      return;
    }

    const items: UploadFileState[] = selectedCandidates.map((candidate, index) => ({
      id: `${Date.now()}_external_${index}_${candidate.filename}`,
      uri: candidate.uri,
      filename: candidate.filename,
      mimeType: candidate.mimeType,
      progress: 0,
      status: 'queued',
      batch_id: activeBatchId,
      error: null,
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
      const videoDocuments = documentUris
        .map((uri, index) => ({ uri, filename: filenameFromDocumentUri(uri, index) }))
        .filter((document) => isSupportedVideoFilename(document.filename))
        .sort((left, right) => left.filename.localeCompare(right.filename));

      if (!videoDocuments.length) {
        setExternalCandidates([]);
        Alert.alert(
          'No videos found',
          'Choose the SD / USB folder that directly contains the video clips, then try again.'
        );
        return;
      }

      setExternalCandidates(
        videoDocuments.map((document, index) => ({
          id: `${permission.directoryUri}_${index}_${document.filename}`,
          uri: document.uri,
          filename: document.filename,
          mimeType: mimeTypeForFilename(document.filename),
          selected: false,
        }))
      );
    } catch (e) {
      handleOperatorError(e);
    } finally {
      setSelectingExternalStorage(false);
    }
  };

  const uploadBusy = uploadItems.some((item) => ['queued', 'initializing', 'uploading'].includes(item.status));
  const verifiedUploads = uploadItems.filter((item) => item.status === 'verified').length;
  const busy = triggering || resetting || selectingExternalStorage || uploadBusy;

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
                Upload all footage for a batch first. Run pipeline now only when the current batch is ready.
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
                <Text variant="caption" color={Colors.textSecondary}>
                  Showing verified latest run status instead: {latestRunLabel(latestRun)}
                </Text>
              </View>
            )}
            {lastRunId && (
              <Text variant="caption" color={Colors.textSecondary}>
                Last app-triggered run: {lastRunId.slice(0, 8)} · see Recent pipeline runs for run-scoped status
              </Text>
            )}

            <Button label={triggering ? 'Triggering...' : 'Run pipeline now'} onPress={runPipeline} disabled={busy} variant="secondary" style={{ height: 44 }} />
            <Button
              label={uploadBusy ? `Uploading ${verifiedUploads}/${uploadItems.length}...` : 'Upload from gallery'}
              onPress={uploadFootage}
              disabled={busy}
              variant="secondary"
              style={{ height: 44 }}
            />
            {Platform.OS === 'android' && (
              <>
                <Button
                  label={selectingExternalStorage ? 'Opening SD / USB...' : 'Choose videos from SD / USB'}
                  onPress={uploadExternalStorageFolder}
                  disabled={busy}
                  variant="secondary"
                  style={{ height: 44 }}
                />
                <Text variant="caption" color={Colors.textSecondary}>
                  First choose the folder on the card or USB drive. Then select only the videos you want to upload.
                </Text>
                {externalCandidates.length > 0 && (
                  <View style={styles.externalSelectionPanel}>
                    <View style={styles.metaRow}>
                      <Text variant="caption" color={Colors.textPrimary}>
                        Select videos · {externalCandidates.filter((candidate) => candidate.selected).length}/{externalCandidates.length}
                      </Text>
                      <Button
                        label="Clear"
                        onPress={() => setExternalCandidates((candidates) => candidates.map((candidate) => ({ ...candidate, selected: false })))}
                        disabled={busy}
                        variant="ghost"
                        style={{ height: 34 }}
                      />
                    </View>
                    <Button
                      label="Select all"
                      onPress={() => setExternalCandidates((candidates) => candidates.map((candidate) => ({ ...candidate, selected: true })))}
                      disabled={busy}
                      variant="ghost"
                      style={{ height: 36 }}
                    />
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
                          <Text variant="caption" color={candidate.selected ? Colors.background : Colors.textSecondary}>
                            {candidate.selected ? '✓' : ''}
                          </Text>
                        </View>
                        <Text variant="caption" color={Colors.textPrimary} numberOfLines={2} style={{ flex: 1 }}>
                          {candidate.filename}
                        </Text>
                      </Pressable>
                    ))}
                    <Button
                      label={`Upload selected (${externalCandidates.filter((candidate) => candidate.selected).length})`}
                      onPress={uploadSelectedExternalVideos}
                      disabled={busy || !externalCandidates.some((candidate) => candidate.selected)}
                      variant="secondary"
                      style={{ height: 44 }}
                    />
                  </View>
                )}
              </>
            )}
            <Button label={resetting ? 'Resetting...' : 'Reset and rerun'} onPress={confirmReset} disabled={busy} variant="secondary" style={{ height: 44, borderColor: Colors.danger }} />
            {uploadItems.length > 0 && (
              <View style={{ gap: Spacing.sm }}>
                <Text variant="caption" color={Colors.textSecondary}>Upload batch progress</Text>
                {uploadItems.map((item) => (
                  <View key={item.id} style={styles.uploadRow}>
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text variant="caption" color={Colors.textPrimary} numberOfLines={1}>{item.filename}</Text>
                      <Text variant="caption" color={item.status === 'failed' ? Colors.danger : Colors.textSecondary}>
                        {UPLOAD_STATUS_LABEL[item.status]} · {item.progress}%
                        {item.error ? ` · ${item.error}` : ''}
                      </Text>
                    </View>
                    {item.status === 'failed' && (
                      <Button
                        label="Retry"
                        onPress={() => retryUploadItem(item)}
                        variant="ghost"
                        style={{ height: 36 }}
                      />
                    )}
                  </View>
                ))}
              </View>
            )}
          </Card>

          <PipelineRunsCard />
          <DeliveryStatusCard />

          <Card bordered style={{ gap: Spacing.sm }}>
            <Text variant="title">Global live stages</Text>
            {STAGES.map((s) => {
              const displayStageIndex = STAGES.indexOf(displayStage);
              const isCurrent = displayStage === s;
              const done = displayStageIndex >= 0 && STAGES.indexOf(s) < displayStageIndex;
              return (
                <View key={s} style={styles.stageRow}>
                  <View style={[styles.dot, done && { backgroundColor: Colors.success }, isCurrent && { backgroundColor: Colors.accent }]} />
                  <Text variant="body" color={isCurrent ? Colors.textPrimary : Colors.textSecondary}>{s.toUpperCase()}</Text>
                </View>
              );
            })}
          </Card>

          {requests.length > 0 && (
            <Card bordered style={{ gap: Spacing.sm }}>
              <Text variant="title">Re-edit requests</Text>
              {requests.map((r) => (
                <View key={r.id} style={{ gap: 2 }}>
                  <View style={styles.metaRow}>
                    <Text variant="caption" color={Colors.textPrimary} numberOfLines={1} style={{ flex: 1 }}>{r.draft_name || r.id.slice(0, 8)}</Text>
                    <Text variant="caption" color={Colors.accent}>{STATUS_LABEL[r.status] ?? r.status}</Text>
                  </View>
                  {!!r.notes && <Text variant="caption" color={Colors.textSecondary} numberOfLines={2}>"{r.notes}"</Text>}
                </View>
              ))}
            </Card>
          )}

          {Object.keys(meta).length > 0 && (
            <Card bordered style={{ gap: Spacing.xs }}>
              <Text variant="title">Global live metadata</Text>
              <Text variant="caption" color={Colors.textSecondary}>Metadata from the singleton live signal. Run history above is the durable action log.</Text>
              <Spacer size={Spacing.xs} />
              {Object.entries(meta).map(([k, v]) => (
                <View key={k} style={styles.metaRow}>
                  <Text variant="caption" color={Colors.textSecondary}>{k}</Text>
                  <Text variant="caption" color={Colors.accent}>{String(v)}</Text>
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
  externalSelectionRowSelected: {
    borderColor: Colors.accent,
  },
  selectionIndicator: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  selectionIndicatorSelected: {
    backgroundColor: Colors.accent,
    borderColor: Colors.accent,
  },
  staleNotice: {
    gap: Spacing.xs,
    borderLeftWidth: 3,
    borderLeftColor: Colors.accent,
    paddingLeft: Spacing.sm,
  },
});
