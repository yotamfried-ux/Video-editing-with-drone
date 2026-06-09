import React from 'react';
import { View, Text, StyleSheet, TextStyle } from 'react-native';

interface Props {
  suffix: string;
  preview?: boolean;
}

export function WatermarkOverlay({ suffix, preview = true }: Props) {
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      {preview && (
        <>
          {/* Diagonal tiled PREVIEW text */}
          {POSITIONS.map((pos, i) => (
            <Text key={i} style={[styles.tile, pos]}>PREVIEW</Text>
          ))}
          {/* Token identifier bottom-right */}
          <View style={styles.tokenContainer}>
            <Text style={styles.token}>#{suffix}</Text>
          </View>
        </>
      )}
    </View>
  );
}

// Positions spread across the screen for the tiled watermark
const POSITIONS: TextStyle[] = [
  { top: '15%',  left: '5%',  transform: [{ rotate: '-35deg' }] },
  { top: '15%',  left: '52%', transform: [{ rotate: '-35deg' }] },
  { top: '38%',  left: '18%', transform: [{ rotate: '-35deg' }] },
  { top: '38%',  left: '65%', transform: [{ rotate: '-35deg' }] },
  { top: '60%',  left: '5%',  transform: [{ rotate: '-35deg' }] },
  { top: '60%',  left: '52%', transform: [{ rotate: '-35deg' }] },
  { top: '80%',  left: '25%', transform: [{ rotate: '-35deg' }] },
];

const styles = StyleSheet.create({
  tile: {
    position: 'absolute',
    color: 'rgba(255,255,255,0.22)',
    fontSize: 18,
    fontWeight: '800',
    letterSpacing: 6,
  },
  tokenContainer: {
    position: 'absolute',
    bottom: 88,
    right: 16,
    backgroundColor: 'rgba(0,0,0,0.35)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
  },
  token: {
    color: 'rgba(255,255,255,0.55)',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1,
  },
});
