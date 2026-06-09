import React from 'react';
import {
  TouchableOpacity, Text, ActivityIndicator,
  StyleSheet, ViewStyle, TextStyle,
} from 'react-native';
import { Colors, Spacing, Radius } from '../constants/theme';
import { Typography } from '../constants/typography';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';

interface Props {
  label: string;
  onPress: () => void;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
}

const variantStyles: Record<Variant, { container: ViewStyle; text: TextStyle }> = {
  primary: {
    container: { backgroundColor: Colors.accent },
    text: { color: Colors.background },
  },
  secondary: {
    container: { backgroundColor: Colors.card, borderWidth: 1, borderColor: Colors.cardBorder },
    text: { color: Colors.textPrimary },
  },
  ghost: {
    container: { backgroundColor: 'transparent' },
    text: { color: Colors.accent },
  },
  danger: {
    container: { backgroundColor: Colors.danger },
    text: { color: Colors.textPrimary },
  },
};

export function Button({ label, onPress, variant = 'primary', loading, disabled, style }: Props) {
  const vs = variantStyles[variant];
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled || loading}
      activeOpacity={0.75}
      style={[styles.base, vs.container, (disabled || loading) && styles.disabled, style]}
    >
      {loading
        ? <ActivityIndicator color={vs.text.color as string} />
        : <Text style={[styles.label, vs.text]}>{label}</Text>
      }
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    height: 52,
    borderRadius: Radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.lg,
  },
  label: {
    ...Typography.title,
    letterSpacing: 0.2,
  },
  disabled: { opacity: 0.45 },
});
