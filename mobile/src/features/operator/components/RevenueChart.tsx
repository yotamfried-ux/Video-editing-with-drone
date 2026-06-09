import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Text } from '@/shared/components/Text';
import { Colors, Spacing } from '@/shared/constants/theme';

interface Props {
  todayRevenue: number;
  weekRevenue: number;
  monthRevenue: number;
}

function formatIls(agorot: number): string {
  return `₪${(agorot / 100).toFixed(0)}`;
}

export function RevenueChart({
  todayRevenue,
  weekRevenue,
  monthRevenue,
}: Props) {
  return (
    <View style={styles.row}>
      {[
        { label: 'Today', value: todayRevenue },
        { label: '7 Days', value: weekRevenue },
        { label: '30 Days', value: monthRevenue },
      ].map(({ label, value }) => (
        <View key={label} style={styles.card}>
          <Text variant="display" color={Colors.accent}>
            {formatIls(value)}
          </Text>
          <Text variant="caption" color={Colors.textSecondary}>
            {label}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: Spacing.sm },
  card: {
    flex: 1,
    backgroundColor: Colors.card,
    borderRadius: 12,
    padding: Spacing.md,
    alignItems: 'center',
    gap: 4,
  },
});
