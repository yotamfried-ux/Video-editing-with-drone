import React, { useCallback, useEffect, useState } from 'react';
import { View, StyleSheet, ScrollView, Alert } from 'react-native';
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
      await operatorFetch('/api/operator/pipeline/run', { method: 'POST' });
      Alert.alert('Pipeline triggered', 'The run starts within a few seconds — watch the progress here.');
    } catch (e) {
      Alert.alert('Failed', e instanceof Error ? e.message : 'Could not trigger the pipeline.');
    } finally {
      setTriggering(false);
    }
  };

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
            <Button
              label={triggering ? 'Triggering…' : '▶ Run pipeline now'}
              onPress={runPipeline}
              disabled={triggering}
              variant="secondary"
              style={{ height: 44 }}
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
                      “{r.notes}”
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
