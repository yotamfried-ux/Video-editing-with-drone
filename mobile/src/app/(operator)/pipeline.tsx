import React, { useCallback, useEffect, useState } from 'react';
import { View, StyleSheet, ScrollView, Alert } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import * as FileSystem from 'expo-file-system';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { PipelineBar } from '@/features/operator/components/PipelineBar';
import { usePipelineStatus } from '@/features/operator/hooks/usePipelineStatus';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import { Colors, Spacing } from '@/shared/constants/theme';

const STAGES = ['idle', 'downloading', 'analyzing', 'editing', 'qa', 'uploading', 'done'];

interface ReprocessRow {
  id: string;
  draft_name: string | null;
  notes: string;
  status: string;
  created_at: string;
}

interface PipelineStartResponse {
  ok: boolean;
  pipeline_run_id: string;
  github_actions_url?: string;
}

const STATUS_LABEL: Record<string, string> = {
  pending: '⏳ waiting for next run',
  queued: '🔁 re-editing now',
  done: '✅ done',
  source_not_found: '⚠️ source not found',
};

export default function PipelineScreen() {
  const status = usePipelineStatus();
  const meta = (status?.meta ?? {}) as Record<string, unknown>;
  const [requests, setRequests] = useState<ReprocessRow[]>([]);
  const [triggering, setTriggering] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [lastRunId, setLastRunId] = useState<string | null>(null);

  const loadRequests = useCallback(async () => {
    try {
      const { requests: data } = await operatorFetch<{ requests: ReprocessRow[] }>(
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
      const result = await operatorFetch<PipelineStartResponse>('/api/operator/pipeline/start', { method: 'POST' });
      setLastRunId(result.pipeline_run_id);
      Alert.alert('Pipeline triggered', `Run ${result.pipeline_run_id.slice(0, 8)} starts within a few seconds — watch the progress here.`);
    } catch (e) {
      Alert.alert('Failed', e instanceof Error ? e.message : 'Could not trigger the pipeline.');
    } finally {
      setTriggering(false);
    }
  };

  const confirmReset = () => {
    Alert.alert(
      'האם אתה בטוח?',
      'כל הטיוטות ב-REVIEW יימחקו, הסרטונים המעובדים יחזרו ל-RAW, והפייפליין יתחיל מחדש על אותו חומר.',
      [
        { text: 'ביטול', style: 'cancel' },
        { text: 'אפס והרץ מחדש', style: 'destructive', onPress: resetAndRerun },
      ]
    );
  };

  const resetAndRerun = async () => {
    setResetting(true);
    try {
      await operatorFetch('/api/operator/pipeline/reset', { method: 'POST' });
      Alert.alert('Reset triggered', 'The pipeline will reset and rerun within a few seconds.');
    } catch (e) {
      Alert.alert('Failed', e instanceof Error ? e.message : 'Could not reset the pipeline.');
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
      // Step 1: get Drive resumable upload URL (file never passes through Vercel)
      const { uploadUrl } = await operatorFetch<{ uploadUrl: string }>(
        '/api/operator/upload',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename, mimeType }),
        }
      );

      // Step 2: stream bytes directly to Drive with progress
      const task = FileSystem.createUploadTask(
        uploadUrl,
        asset.uri,
        {
          httpMethod: 'PUT',
          uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
          headers: { 'Content-Type': mimeType },
        },
        (progress) => {
          const pct = Math.round(
            (progress.totalBytesSent / progress.totalBytesExpectedToSend) * 100
          );
          setUploadProgress(pct);
        }
      );
      const uploadResult = await task.uploadAsync();
      if (!uploadResult || uploadResult.status >= 300) {
        throw new Error(`Upload failed with status ${uploadResult?.status}`);
      }

      setUploadProgress(null);

      // Step 3: trigger tracked pipeline run
      const run = await operatorFetch<PipelineStartResponse>('/api/operator/pipeline/start', { method: 'POST' });
      setLastRunId(run.pipeline_run_id);
      Alert.alert('Uploaded!', `"${filename}" is in RAW — run ${run.pipeline_run_id.slice(0, 8)} starts now.`);
    } catch (e) {
      setUploadProgress(null);
      Alert.alert('Failed', e instanceof Error ? e.message : 'Upload failed.');
    }
  };

  const busy = triggering || resetting || uploadProgress !== null;

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <ScrollView contentContainerStyle={{ gap: Spacing.md, paddingBottom: Spacing.xl }}>
          <Text variant="display">Pipeline</Text>
          <Text variant="caption" color={Colors.textSecondary}>
            Live status · polls every 5s
            {status?.updated_at ? ` · updated ${new Date(status.updated_at).toLocaleTimeString()}` : ''}
          </Text>

          <Card bordered style={{ gap: Spacing.md }}>
            <PipelineBar stage={status?.stage ?? 'idle'} progress={status?.progress ?? 0} />
            {lastRunId && (
              <Text variant="caption" color={Colors.textSecondary}>
                Current app-triggered run: {lastRunId.slice(0, 8)}
              </Text>
            )}

            <Button
              label={triggering ? 'Triggering…' : '▶ Run pipeline now'}
              onPress={runPipeline}
              disabled={busy}
              variant="secondary"
              style={{ height: 44 }}
            />

            <Button
              label={uploadProgress !== null ? `Uploading… ${uploadProgress}%` : '📤 Upload footage'}
              onPress={uploadFootage}
              disabled={busy}
              variant="secondary"
              style={{ height: 44 }}
            />

            <Button
              label={resetting ? 'Resetting…' : '🔄 Reset & rerun'}
              onPress={confirmReset}
              disabled={busy}
              variant="secondary"
              style={{ height: 44, borderColor: Colors.error ?? '#e53e3e' }}
            />
          </Card>

          {/* Stage timeline */}
          <Card bordered style={{ gap: Spacing.sm }}>
            <Text variant="title">Stages</Text>
            {STAGES.map((s) => {
              const isCurrent = status?.stage === s;
              const idx = STAGES.indexOf(status?.stage ?? 'idle');
              const done = STAGES.indexOf(s) < idx;
              return (
                <View key={s} style={styles.stageRow}>
                  <View
                    style={[
                      styles.dot,
                      done && { backgroundColor: Colors.success },
                      isCurrent && { backgroundColor: Colors.accent },
                    ]}
                  />
                  <Text
                    variant="body"
                    color={isCurrent ? Colors.textPrimary : Colors.textSecondary}
                  >
                    {s.toUpperCase()}
                  </Text>
                </View>
              );
            })}
          </Card>

          {/* Re-edit queue */}
          {requests.length > 0 && (
            <Card bordered style={{ gap: Spacing.sm }}>
              <Text variant="title">Re-edit requests</Text>
              {requests.map((r) => (
                <View key={r.id} style={{ gap: 2 }}>
                  <View style={styles.metaRow}>
                    <Text variant="caption" color={Colors.textPrimary} numberOfLines={1} style={{ flex: 1 }}>
                      {r.draft_name || r.id.slice(0, 8)}
                    </Text>
                    <Text variant="caption" color={Colors.accent}>
                      {STATUS_LABEL[r.status] ?? r.status}
                    </Text>
                  </View>
                  {!!r.notes && (
                    <Text variant="caption" color={Colors.textSecondary} numberOfLines={2}>
                      "{r.notes}"
                    </Text>
                  )}
                </View>
              ))}
            </Card>
          )}

          {/* Meta from last run */}
          {Object.keys(meta).length > 0 && (
            <Card bordered style={{ gap: Spacing.xs }}>
              <Text variant="title">Run Details</Text>
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
});
