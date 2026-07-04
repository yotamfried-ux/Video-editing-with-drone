import React, { useCallback, useEffect, useState } from 'react';
import { View, StyleSheet, ScrollView, Alert } from 'react-native';
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

type UploadInit = OperatorUploadInitResponse & { storage_key?: string; storage_backend?: string };
type UploadVerify = { ok: boolean; exists: boolean; size?: number | null; storage_key?: string; r2_status?: number };

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
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [lastRunId, setLastRunId] = useState<string | null>(null);

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
      const result = await operatorFetch<PipelineDispatchResponse>('/api/operator/pipeline/start', { method: 'POST' });
      setLastRunId(result.pipeline_run_id);
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
        body: JSON.stringify({ full_clean: fullClean }),
      });
      setLastRunId(result.pipeline_run_id);
      const scope = result.full_clean ? 'Full clean' : 'Reset';
      Alert.alert('Reset triggered', `${scope} run ${result.pipeline_run_id.slice(0, 8)} started. Watch Recent pipeline runs for this reset.`);
    } catch (e) {
      handleOperatorError(e);
    } finally {
      setResetting(false);
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
      allowsMultipleSelection: false,
      videoMaxDuration: 7200,
    });
    if (result.canceled || !result.assets?.length) return;

    const asset = result.assets[0];
    const filename = asset.fileName ?? `footage_${Date.now()}.mp4`;
    const mimeType = asset.mimeType ?? 'video/mp4';

    setUploadProgress(0);
    try {
      const uploadInit = await operatorFetch<UploadInit>(
        '/api/operator/upload',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename, mimeType }),
        }
      );

      const task = FileSystem.createUploadTask(
        uploadInit.uploadUrl,
        asset.uri,
        {
          httpMethod: 'PUT',
          uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
          headers: { 'Content-Type': mimeType },
        },
        (progress) => {
          const pct = Math.round((progress.totalBytesSent / progress.totalBytesExpectedToSend) * 100);
          setUploadProgress(pct);
        }
      );
      const uploadResult = await task.uploadAsync();
      if (!uploadResult || uploadResult.status >= 300) {
        throw new Error(`Upload failed with status ${uploadResult?.status}`);
      }

      if (uploadInit.storage_key) {
        const verified = await operatorFetch<UploadVerify>('/api/operator/upload/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ storage_key: uploadInit.storage_key }),
        });
        if (!verified.exists) {
          throw new Error(`Upload finished but R2 verification failed for ${uploadInit.storage_key}`);
        }
      }

      setUploadProgress(null);
      Alert.alert(
        'Uploaded to queue',
        `"${uploadInit.filename}" is verified in RAW. Upload more footage for this athlete/session, then tap Run pipeline now when the batch is ready.`
      );
    } catch (e) {
      setUploadProgress(null);
      handleOperatorError(e);
    }
  };

  const busy = triggering || resetting || uploadProgress !== null;

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
                Upload all footage for a batch first. Run pipeline now only when the RAW queue is ready.
              </Text>
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
            <Button label={uploadProgress !== null ? `Uploading... ${uploadProgress}%` : 'Upload footage'} onPress={uploadFootage} disabled={busy} variant="secondary" style={{ height: 44 }} />
            <Button label={resetting ? 'Resetting...' : 'Reset and rerun'} onPress={confirmReset} disabled={busy} variant="secondary" style={{ height: 44, borderColor: Colors.danger }} />
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
  staleNotice: {
    gap: Spacing.xs,
    borderLeftWidth: 3,
    borderLeftColor: Colors.accent,
    paddingLeft: Spacing.sm,
  },
});
