import React from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { PipelineBar } from '@/features/operator/components/PipelineBar';
import { usePipelineStatus } from '@/features/operator/hooks/usePipelineStatus';
import { Colors, Spacing } from '@/shared/constants/theme';

const STAGES = ['idle', 'downloading', 'analyzing', 'editing', 'qa', 'done'];

export default function PipelineScreen() {
  const status = usePipelineStatus();
  const meta = (status?.meta ?? {}) as Record<string, unknown>;

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
  metaRow: { flexDirection: 'row', justifyContent: 'space-between' },
});
