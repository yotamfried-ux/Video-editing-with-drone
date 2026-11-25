import React from 'react';
import {
  TouchableOpacity, Text, ActivityIndicator,
  StyleSheet, ViewStyle, TextStyle,
} from 'react-native';
import { hapticLight } from '../lib/haptics';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Colors, Spacing, Radius } from '../constants/theme';
import { Typography } from '../constants/typography';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'dangerText';

interface Props {
  label: string;
  onPress: () => void;
  variant?: Variant;
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  testID?: string;
  /** Shown before the label. */
  icon?: React.ComponentProps<typeof MaterialCommunityIcons>['name'];
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
  // A destructive action that should not be the loudest thing on the screen.
  dangerText: {
    container: { backgroundColor: 'transparent' },
    text: { color: Colors.danger },
  },
};

export function Button({ label, onPress, variant = 'primary', loading, disabled, style, testID, icon }: Props) {
  const vs = variantStyles[variant];
  const press = () => {
    // A light tap confirms the press on the actions that change something.
    if (variant === 'primary' || variant === 'danger' || variant === 'dangerText') void hapticLight();
    onPress();
  };
  return (
    <TouchableOpacity
      testID={testID}
      onPress={press}
      disabled={disabled || loading}
      activeOpacity={0.75}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: Boolean(disabled || loading), busy: Boolean(loading) }}
      style={[styles.base, vs.container, (disabled || loading) && styles.disabled, style]}
    >
      {loading
        ? <ActivityIndicator color={vs.text.color as string} />
        : (
          <>
            {icon ? <MaterialCommunityIcons name={icon} size={20} color={vs.text.color as string} /> : null}
            <Text style={[styles.label, vs.text]}>{label}</Text>
          </>
        )
      }
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  base: {
    height: 52,
    borderRadius: Radius.lg,
    flexDirection: 'row',
    gap: Spacing.sm,
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
