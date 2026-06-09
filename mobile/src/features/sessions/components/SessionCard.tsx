import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Text } from '@/shared/components/Text';
import { Colors, Spacing } from '@/shared/constants/theme';

interface Props {
  recording_date: string;
  sport: string;
  reelCount: number;
}

export function SessionCard({ recording_date, sport, reelCount }: Props) {
  const date = new Date(recording_date).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
  return (
    <View style={styles.header}>
      <Text variant="title">{date}</Text>
      <Text variant="caption" color={Colors.textSecondary}>
        {sport} · {reelCount} clip{reelCount !== 1 ? 's' : ''}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingVertical: Spacing.md,
    paddingHorizontal: Spacing.md,
  },
});
