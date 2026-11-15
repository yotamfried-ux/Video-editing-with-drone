import React from 'react';
import { Text as RNText, TextStyle } from 'react-native';
import { Colors } from '../constants/theme';
import { Typography } from '../constants/typography';

type Variant = keyof typeof Typography;

interface Props {
  children: React.ReactNode;
  variant?: Variant;
  color?: string;
  style?: TextStyle;
  numberOfLines?: number;
  testID?: string;
  onPress?: () => void;
}

export function Text({ children, variant = 'body', color, style, numberOfLines, testID, onPress }: Props) {
  return (
    <RNText
      testID={testID}
      onPress={onPress}
      accessibilityRole={onPress ? 'link' : undefined}
      style={[
        Typography[variant],
        { color: color ?? Colors.textPrimary },
        style,
      ]}
      numberOfLines={numberOfLines}
    >
      {children}
    </RNText>
  );
}
