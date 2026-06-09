import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export function WatermarkOverlay({ suffix }: { suffix: string }) {
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <View style={styles.container}>
        <Text style={styles.text}>{suffix}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    bottom: 80,
    right: 20,
  },
  text: {
    color: 'rgba(255,255,255,0.18)',
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: 2,
  },
});
