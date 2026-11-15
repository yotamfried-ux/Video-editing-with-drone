import React, { useState } from 'react';
import { Linking, View, StyleSheet, Switch, TouchableOpacity } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { ProtectedPlayer } from '@/features/video/components/ProtectedPlayer';
import { useReelStream } from '@/features/video/hooks/useReelStream';
import { previewExplanation, previewLabel } from '@/features/reel/previewInfo';
import { useReelOwnership } from '@/features/reel/useReelOwnership';
import { isSafeCheckoutUrl } from '@/features/payment/lib/checkout';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function ReelScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  const { data, loading, error } = useReelStream(token);
  const { ownership, busy, error: followError, setFollowing } = useReelOwnership(token);
  const [ended, setEnded] = useState(false);
  const goBack = () => (router.canGoBack() ? router.back() : router.replace('/(tabs)/discover'));

  if (loading) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <Text variant="body" color={Colors.textSecondary}>Loading…</Text>
        </View>
      </SafeArea>
    );
  }

  if (error || !data) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <Text variant="headline" color={Colors.danger}>
            {error?.includes('410') ? 'This clip has expired' : 'Clip unavailable'}
          </Text>
          <Button label="Go Back" onPress={goBack} variant="ghost" style={{ marginTop: Spacing.md }} />
        </View>
      </SafeArea>
    );
  }

  const purchased = Boolean(ownership?.purchased);
  const soldToSomeoneElse = Boolean(data.sold) && !purchased;

  return (
    <View style={styles.fullscreen}>
      <ProtectedPlayer
        streamUrl={data.streamUrl}
        watermarkSuffix={data.watermarkSuffix}
        onEnd={() => setEnded(true)}
      />

      <TouchableOpacity testID="reel-back" style={styles.back} onPress={goBack}>
        <Text variant="title">←</Text>
      </TouchableOpacity>

      {/* What the customer is looking at: a preview, and how much of the clip it is. */}
      <View style={styles.previewChip} pointerEvents="none">
        <Text testID="reel-preview-label" variant="caption" color={Colors.textPrimary}>
          {previewLabel(data.previewSeconds, data.fullSeconds)}
        </Text>
      </View>

      <View style={styles.panel}>
        {purchased ? (
          <>
            <Text testID="reel-owned" variant="title">You own this clip</Text>
            <Text variant="caption" color={Colors.textSecondary}>
              Above is the preview. Your download is the full clip in full quality, without the watermark.
            </Text>
            <Button
              testID="reel-download"
              label={ownership?.download_url ? 'Download full clip' : 'Preparing your clip…'}
              disabled={!isSafeCheckoutUrl(ownership?.download_url)}
              onPress={() => {
                if (isSafeCheckoutUrl(ownership?.download_url)) Linking.openURL(ownership.download_url);
              }}
            />
            {ownership?.can_follow && (
              <View style={styles.followRow}>
                <View style={{ flex: 1 }}>
                  <Text variant="body">Tell me about more clips of this athlete</Text>
                  <Text variant="caption" color={Colors.textSecondary}>
                    We will send a notification when a new clip of them is ready.
                  </Text>
                </View>
                <Switch
                  testID="reel-follow-switch"
                  value={Boolean(ownership.following)}
                  disabled={busy}
                  onValueChange={(next) => setFollowing(next)}
                />
              </View>
            )}
            {followError && <Text variant="caption" color={Colors.danger}>{followError}</Text>}
          </>
        ) : (
          <>
            <Text testID="reel-preview-explanation" variant="caption" color={Colors.textPrimary}>
              {ended ? 'The preview has ended. ' : ''}
              {previewExplanation(data.fullSeconds)}
            </Text>
            {soldToSomeoneElse ? (
              <Text testID="reel-sold" variant="title" color={Colors.textSecondary}>This clip was already sold</Text>
            ) : (
              <Button
                testID="reel-buy"
                label="Buy the full clip"
                onPress={() => router.push(`/checkout/${token}`)}
              />
            )}
          </>
        )}
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
  previewChip: {
    position: 'absolute', top: 60, right: Spacing.md,
    paddingHorizontal: Spacing.sm, paddingVertical: 6,
    backgroundColor: 'rgba(0,0,0,0.65)', borderRadius: 14,
  },
  panel: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    padding: Spacing.lg, paddingBottom: 36, gap: Spacing.sm,
    backgroundColor: 'rgba(10,14,26,0.86)',
  },
  followRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, marginTop: Spacing.xs },
});
