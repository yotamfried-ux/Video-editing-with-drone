import React from 'react';
import { View } from 'react-native';

export function Spacer({ size = 16, horizontal }: { size?: number; horizontal?: boolean }) {
  return <View style={horizontal ? { width: size } : { height: size }} />;
}
