import React from 'react';
import { View, StyleSheet } from 'react-native';
import { Text } from '@/shared/components/Text';
import { Colors, Spacing, Radius } from '@/shared/constants/theme';

interface Props {
  stage: string;
  progress: number;
}

export function PipelineBar({ stage, progress }: Props) {
  return (
    <View style={styles.container}>
      <View style={styles.track}>
        <View
          style={[
            styles.fill,
            { width: `${Math.round(progress * 100)}%` },
          ]}
        />
      </View>
      <Text variant="caption" color={Colors.textSecondary}>
        {stage.toUpperCase()} — {Math.round(progress * 100)}%
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: Spacing.sm },
  track: {
    height: 6,
    borderRadius: Radius.full,
    backgroundColor: Colors.card,
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
    borderRadius: Radius.full,
    backgroundColor: Colors.accent,
  },
});
