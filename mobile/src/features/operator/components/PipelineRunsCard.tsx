import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, View, StyleSheet } from 'react-native';
import { Card } from '@/shared/components/Card';
import { Text } from '@/shared/components/Text';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import type { PipelineRun, PipelineRunsResponse } from '@/features/operator/types/contracts';
import { Colors, Radius, Spacing } from '@/shared/constants/theme';

const COLLAPSED_LIMIT = 3;

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  no_input: 'No input',
  dispatch_failed: 'Dispatch failed',
};

const SOURCE_LABEL: Record<string, string> = {
  manual: 'Manual',
  upload: 'Upload',
  reset: 'Reset',
  reprocess: 'Re-edit',
  drive_watcher: 'Drive',
};

function fmtTime(value: string | null | undefined): string {
  if (!value) return '';
  return new Date(value).toLocaleString(undefined, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtProgress(value: number | null | undefined): string {
  if (value == null) return '';
  return `${Math.round(value * 100)}%`;
}

function statusColor(status: string): string {
  if (status === 'succeeded') return Colors.success;
  if (status === 'failed' || status === 'dispatch_failed') return Colors.danger;
  if (status === 'queued' || status === 'running') return Colors.accent;
  return Colors.textSecondary;
}

function compactStage(run: PipelineRun): string {
  const stage = run.stage ? run.stage.replace(/_/g, ' ') : 'unknown';
  const progress = fmtProgress(run.progress);
  return progress ? `${stage} · ${progress}` : stage;
}

export function PipelineRunsCard() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [expandedErrorId, setExpandedErrorId] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const result = await operatorFetch<PipelineRunsResponse>('/api/operator/pipeline/runs?limit=12');
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

  const visibleRuns = useMemo(
    () => (showAll ? runs : runs.slice(0, COLLAPSED_LIMIT)),
    [runs, showAll],
  );

  const hiddenCount = Math.max(0, runs.length - COLLAPSED_LIMIT);

  return (
    <Card bordered style={{ gap: Spacing.sm }}>
      <View style={styles.cardHeader}>
        <View style={{ flex: 1 }}>
          <Text variant="title">Recent pipeline runs</Text>
          {runs.length > 0 && (
            <Text variant="caption" color={Colors.textSecondary}>
              Showing {visibleRuns.length} of {runs.length}
            </Text>
          )}
        </View>
        {hiddenCount > 0 && (
          <Pressable onPress={() => setShowAll((value) => !value)} hitSlop={8}>
            <Text variant="caption" color={Colors.accent}>
              {showAll ? 'Show less' : `View all (${runs.length})`}
            </Text>
          </Pressable>
        )}
      </View>

      {error ? (
        <Text variant="caption" color={Colors.danger}>{error}</Text>
      ) : runs.length === 0 ? (
        <Text variant="caption" color={Colors.textSecondary}>No tracked runs yet.</Text>
      ) : (
        visibleRuns.map((run) => {
          const isErrorExpanded = expandedErrorId === run.id;
          const hasError = Boolean(run.error);
          return (
            <View key={run.id} style={styles.runRow}>
              <View style={styles.runTopLine}>
                <View style={[styles.statusDot, { backgroundColor: statusColor(run.status) }]} />
                <Text variant="caption" color={statusColor(run.status)} style={styles.statusText} numberOfLines={1}>
                  {STATUS_LABEL[run.status] ?? run.status}
                </Text>
                <Text variant="caption" color={Colors.textPrimary} style={styles.sourceText} numberOfLines={1}>
                  {SOURCE_LABEL[run.source] ?? run.source} · {run.id.slice(0, 8)}
                </Text>
              </View>

              <Text variant="caption" color={Colors.textSecondary} numberOfLines={1}>
                {compactStage(run)} · {fmtTime(run.queued_at)}
              </Text>

              {hasError && (
                <Pressable
                  style={styles.errorToggle}
                  onPress={() => setExpandedErrorId(isErrorExpanded ? null : run.id)}
                >
                  <Text variant="caption" color={Colors.danger} numberOfLines={isErrorExpanded ? undefined : 1}>
                    {isErrorExpanded ? run.error : 'View error'}
                  </Text>
                </Pressable>
              )}
            </View>
          );
        })
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: Spacing.sm,
  },
  runRow: {
    gap: 2,
    paddingVertical: Spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: Colors.cardBorder,
  },
  runTopLine: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: Radius.full,
  },
  statusText: {
    minWidth: 76,
  },
  sourceText: {
    flex: 1,
  },
  errorToggle: {
    alignSelf: 'flex-start',
    marginTop: 2,
  },
});
