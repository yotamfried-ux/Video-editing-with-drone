import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, StyleProp, ViewStyle } from 'react-native';
import { Colors, Radius } from '../constants/theme';

/**
 * A placeholder in the shape of the content that is loading. It pulses gently; with "reduce motion" on
 * it stays still.
 */
export function Skeleton({ style }: { style?: StyleProp<ViewStyle> }) {
  const opacity = useRef(new Animated.Value(0.55)).current;
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then((on) => { if (alive) setReduceMotion(on); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (reduceMotion) return;
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.55, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity, reduceMotion]);

  return (
    <Animated.View
      accessible={false}
      importantForAccessibility="no-hide-descendants"
      style={[{ backgroundColor: Colors.card, borderRadius: Radius.md, opacity }, style]}
    />
  );
}
