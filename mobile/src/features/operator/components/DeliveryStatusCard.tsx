import React, { useCallback, useEffect, useState } from 'react';
import { View, StyleSheet } from 'react-native';
import { Card } from '@/shared/components/Card';
import { Text } from '@/shared/components/Text';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import type { DeliveryRun, DeliveryStatusResponse } from '@/features/operator/types/contracts';
import { Colors, Spacing } from '@/shared/constants/theme';

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Delivery running',
  discover_published: 'In Discover',
  succeeded: 'Done',
  failed: 'Failed',
  dispatch_failed: 'Dispatch failed',
};

function fmtTime(value: string | null | undefined): string {
  if (!value) return '';
  return new Date(value).toLocaleString();
}

export function DeliveryStatusCard() {
  const [runs, setRuns] = useState<DeliveryRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const result = await operatorFetch<DeliveryStatusResponse>('/api/operator/delivery-status?limit=8');
      setRuns(result.runs ?? []);
      setError(null);
    } catch (e) {
      setRuns([]);
      setError(e instanceof Error ? e.message : 'Could not load delivery status');
    }
  }, []);

  useEffect(() => {
    loadRuns();
    const timer = setInterval(loadRuns, 10000);
    return () => clearInterval(timer);
  }, [loadRuns]);

  return (
    <Card bordered style={{ gap: Spacing.sm }}>
      <Text variant="title">Delivery status</Text>
      <Text variant="caption" color={Colors.textSecondary}>
        Approved videos appear in Discover after the delivery workflow publishes the preview.
      </Text>
      {error ? (
        <Text variant="caption" color={Colors.danger}>{error}</Text>
      ) : runs.length === 0 ? (
        <Text variant="caption" color={Colors.textSecondary}>No approvals tracked yet.</Text>
      ) : (
        runs.map((run) => (
          <View key={run.id} style={styles.runRow}>
            <View style={styles.runHeader}>
              <Text variant="caption" color={Colors.textPrimary} style={{ flex: 1 }} numberOfLines={1}>
                {run.approved_file_name || run.source_video || run.id.slice(0, 8)}
              </Text>
              <Text variant="caption" color={run.discover_reel_id ? Colors.success : Colors.accent}>
                {STATUS_LABEL[run.status] ?? run.status}
              </Text>
            </View>
            <Text variant="caption" color={Colors.textSecondary}>
              {run.stage.toUpperCase()} · {fmtTime(run.approved_at)}
            </Text>
            {!!run.discover_reel_id && (
              <Text variant="caption" color={Colors.success}>Discover reel: {run.discover_reel_id.slice(0, 8)}</Text>
            )}
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
