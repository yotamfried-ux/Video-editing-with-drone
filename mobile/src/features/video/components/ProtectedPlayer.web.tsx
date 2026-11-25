import React, { useEffect, useRef, useState } from 'react';
import { View, TouchableOpacity, StyleSheet } from 'react-native';
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
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [paused, setPaused] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    if (paused) {
      el.pause();
    } else {
      el.play().catch(() => {
        setPaused(true);
      });
    }
  }, [paused, streamUrl]);

  return (
    <View style={styles.container}>
      <TouchableOpacity
        activeOpacity={1}
        onPress={() => setControlsVisible((v) => !v)}
        style={StyleSheet.absoluteFill}
      >
        <video
          ref={videoRef}
          src={streamUrl}
          playsInline
          autoPlay
          controls={false}
          controlsList="nodownload noplaybackrate"
          disablePictureInPicture
          onContextMenu={(e) => e.preventDefault()}
          onEnded={() => {
            setPaused(true);
            onEnd?.();
          }}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            backgroundColor: '#000',
          }}
        />
      </TouchableOpacity>

      <WatermarkOverlay suffix={watermarkSuffix} preview />

      {controlsVisible && (
        <View style={styles.controls} pointerEvents="box-none">
          <TouchableOpacity
            style={styles.playBtn}
            onPress={() => setPaused((p) => !p)}
          >
            <Text variant="headline">{paused ? '▶' : '⏸'}</Text>
          </TouchableOpacity>
        </View>
      )}
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
