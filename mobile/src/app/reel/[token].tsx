import React, { useState } from 'react';
import { Linking, View, StyleSheet, TouchableOpacity } from 'react-native';
import { ActivityIndicator, Switch } from 'react-native-paper';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { EmptyState } from '@/shared/components/EmptyState';
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
  // Android 16 draws under the system bars: keep the controls clear of them on every device.
  const insets = useSafeAreaInsets();
  const goBack = () => (router.canGoBack() ? router.back() : router.replace('/(tabs)/discover'));

  if (loading) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <ActivityIndicator animating color={Colors.accent} />
          <Text variant="body" color={Colors.textSecondary}>Loading the preview…</Text>
        </View>
      </SafeArea>
    );
  }

  if (error || !data) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <EmptyState
            icon={error?.includes('410') ? 'clock-alert-outline' : 'video-off-outline'}
            title={error?.includes('410') ? 'This clip has expired' : 'Clip unavailable'}
            body={error?.includes('410')
              ? 'Clips stay on sale for a limited time after the session.'
              : 'It may have been removed, or the connection dropped.'}
            actionLabel="Go Back"
            onAction={goBack}
          />
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

      <TouchableOpacity
        testID="reel-back"
        style={[styles.back, { top: insets.top + Spacing.sm }]}
        onPress={goBack}
        accessibilityRole="button"
        accessibilityLabel="Back"
        hitSlop={8}
      >
        <MaterialCommunityIcons name="arrow-left" size={24} color={Colors.textPrimary} />
      </TouchableOpacity>

      {/* What the customer is looking at: a preview, and how much of the clip it is. */}
      <View style={[styles.previewChip, { top: insets.top + Spacing.sm + 6 }]} pointerEvents="none">
        <MaterialCommunityIcons name="eye-outline" size={14} color={Colors.textPrimary} />
        <Text testID="reel-preview-label" variant="caption" color={Colors.textPrimary}>
          {previewLabel(data.previewSeconds, data.fullSeconds)}
        </Text>
      </View>

      <View style={[styles.panel, { paddingBottom: insets.bottom + Spacing.lg }]}>
        {purchased ? (
          <>
            <View style={styles.ownedRow}>
              <MaterialCommunityIcons name="check-decagram" size={22} color={Colors.success} />
              <Text testID="reel-owned" variant="title">You own this clip</Text>
            </View>
            <Text variant="caption" color={Colors.textSecondary}>
              Above is the preview. Your download is the full clip in full quality, without the watermark.
            </Text>
            <Button
              testID="reel-download"
              icon="download"
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
                icon="lock-open-variant-outline"
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
    position: 'absolute', left: Spacing.md,
    width: 44, height: 44, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.5)', borderRadius: 22,
  },
  ownedRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  previewChip: {
    position: 'absolute', right: Spacing.md,
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: Spacing.sm, paddingVertical: 6,
    backgroundColor: 'rgba(0,0,0,0.65)', borderRadius: 14,
  },
  panel: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    padding: Spacing.lg, gap: Spacing.sm,
    backgroundColor: 'rgba(10,14,26,0.86)',
  },
  followRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, marginTop: Spacing.xs },
});
