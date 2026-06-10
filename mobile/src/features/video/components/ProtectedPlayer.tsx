import React, { useRef, useState } from 'react';
import { View, TouchableOpacity, StyleSheet } from 'react-native';
import Video, { VideoRef } from 'react-native-video';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
} from 'react-native-reanimated';
import { useScreenCapture } from '../hooks/useScreenCapture';
import { WatermarkOverlay } from './WatermarkOverlay';
import { Text } from '@/shared/components/Text';

interface Props {
  streamUrl: string;
  watermarkSuffix: string;
  onEnd?: () => void;
}

export function ProtectedPlayer({ streamUrl, watermarkSuffix, onEnd }: Props) {
  useScreenCapture();
  const videoRef = useRef<VideoRef>(null);
  const [paused, setPaused] = useState(false);
  const controlsOpacity = useSharedValue(1);

  const animStyle = useAnimatedStyle(() => ({
    opacity: controlsOpacity.value,
  }));

  const toggleControls = () => {
    controlsOpacity.value = withTiming(
      controlsOpacity.value > 0.5 ? 0 : 1,
      { duration: 200 }
    );
  };

  return (
    <View style={styles.container}>
      <TouchableOpacity
        activeOpacity={1}
        onPress={toggleControls}
        style={StyleSheet.absoluteFill}
      >
        <Video
          ref={videoRef}
          source={{ uri: streamUrl }}
          style={StyleSheet.absoluteFill}
          resizeMode="cover"
          paused={paused}
          onEnd={onEnd}
          repeat={false}
        />
      </TouchableOpacity>

      <WatermarkOverlay suffix={watermarkSuffix} preview />

      <Animated.View style={[styles.controls, animStyle]} pointerEvents="box-none">
        <TouchableOpacity
          style={styles.playBtn}
          onPress={() => setPaused(!paused)}
        >
          <Text variant="headline">{paused ? '▶' : '⏸'}</Text>
        </TouchableOpacity>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  controls: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playBtn: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
  },
});
