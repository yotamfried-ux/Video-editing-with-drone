import React, { useState } from 'react';
import { View, StyleSheet, TouchableOpacity } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Badge } from '@/shared/components/Badge';
import { ProtectedPlayer } from '@/features/video/components/ProtectedPlayer';
import { useReelStream } from '@/features/video/hooks/useReelStream';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function ReelScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  const { data, loading, error } = useReelStream(token);
  const [ended, setEnded] = useState(false);

  if (loading) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <Text variant="body" color={Colors.textSecondary}>Loading…</Text>
        </View>
      </SafeArea>
    );
  }

  if (error) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <Text variant="headline" color={Colors.danger}>
            {error.includes('410') ? 'This clip has expired' : 'Clip unavailable'}
          </Text>
          <Button label="Go Back" onPress={() => router.back()} variant="ghost" style={{ marginTop: Spacing.md }} />
        </View>
      </SafeArea>
    );
  }

  return (
    <View style={styles.fullscreen}>
      <ProtectedPlayer
        streamUrl={data!.streamUrl}
        watermarkSuffix={data!.watermarkSuffix}
        onEnd={() => setEnded(true)}
      />

      {/* Back button */}
      <TouchableOpacity style={styles.back} onPress={() => router.back()}>
        <Text variant="title">←</Text>
      </TouchableOpacity>

      {/* Badge top-right */}
      <View style={styles.badgeContainer}>
        <Badge type="live" expiresAt={data!.expiresAt} />
      </View>

      {/* Buy button bottom */}
      <View style={styles.buyContainer}>
        <Button
          label="Buy This Clip"
          onPress={() => router.push(`/checkout/${token}`)}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fullscreen: { flex: 1, backgroundColor: '#000' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: Spacing.sm },
  back: {
    position: 'absolute', top: 56, left: Spacing.md,
    padding: Spacing.sm, backgroundColor: 'rgba(0,0,0,0.5)',
    borderRadius: 20,
  },
  badgeContainer: { position: 'absolute', top: 56, right: Spacing.md },
  buyContainer: {
    position: 'absolute', bottom: 40, left: Spacing.lg, right: Spacing.lg,
  },
});
