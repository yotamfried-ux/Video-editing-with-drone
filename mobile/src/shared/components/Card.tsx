import React from 'react';
import { View, StyleSheet, StyleProp, ViewStyle } from 'react-native';
import { Colors, Radius, Spacing } from '../constants/theme';

interface Props {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  bordered?: boolean;
}

export function Card({ children, style, bordered }: Props) {
  return (
    <View style={[styles.card, bordered && styles.bordered, style]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.card,
    borderRadius: Radius.lg,
    padding: Spacing.md,
  },
  bordered: {
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
});
