import React, { useCallback, useEffect, useState } from 'react';
import { View, StyleSheet } from 'react-native';
import { Card } from '@/shared/components/Card';
import { Text } from '@/shared/components/Text';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import { Colors, Spacing } from '@/shared/constants/theme';

type PipelineRun = {
  id: string;
  source: string;
  status: string;
  stage: string | null;
  progress: number | null;
  github_run_url: string | null;
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  no_input: 'No input',
  dispatch_failed: 'Dispatch failed',
};

const SOURCE_LABEL: Record<string, string> = {
  manual: 'Manual run',
  upload: 'Upload',
  reset: 'Reset',
  reprocess: 'Re-edit',
  drive_watcher: 'Drive watcher',
};

function fmtTime(value: string | null | undefined): string {
  if (!value) return '';
  return new Date(value).toLocaleString();
}

function fmtProgress(value: number | null | undefined): string {
  if (value == null) return '';
  return `${Math.round(value * 100)}%`;
}

export function PipelineRunsCard() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const result = await operatorFetch<{ runs: PipelineRun[] }>('/api/operator/pipeline/runs?limit=8');
      setRuns(result.runs ?? []);
      setError(null);
    } catch (e) {
      setRuns([]);
      setError(e instanceof Error ? e.message : 'Could not load pipeline runs');
    }
  }, []);

  useEffect(() => {
    loadRuns();
    const timer = setInterval(loadRuns, 10000);
    return () => clearInterval(timer);
  }, [loadRuns]);

  return (
    <Card bordered style={{ gap: Spacing.sm }}>
      <Text variant="title">Recent pipeline runs</Text>
      {error ? (
        <Text variant="caption" color={Colors.danger}>{error}</Text>
      ) : runs.length === 0 ? (
        <Text variant="caption" color={Colors.textSecondary}>No tracked runs yet.</Text>
      ) : (
        runs.map((run) => (
          <View key={run.id} style={styles.runRow}>
            <View style={styles.runHeader}>
              <Text variant="caption" color={Colors.textPrimary} style={{ flex: 1 }}>
                {(SOURCE_LABEL[run.source] ?? run.source)} · {run.id.slice(0, 8)}
              </Text>
              <Text variant="caption" color={Colors.accent}>
                {STATUS_LABEL[run.status] ?? run.status}
              </Text>
            </View>
            <Text variant="caption" color={Colors.textSecondary}>
              {(run.stage ?? 'unknown').toUpperCase()} {fmtProgress(run.progress)} · {fmtTime(run.queued_at)}
            </Text>
            {!!run.error && (
              <Text variant="caption" color={Colors.danger} numberOfLines={2}>{run.error}</Text>
            )}
          </View>
        ))
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  runRow: { gap: 2, paddingVertical: 4 },
  runHeader: { flexDirection: 'row', justifyContent: 'space-between', gap: Spacing.sm },
});
