import React, { useState } from 'react';
import { View, StyleSheet, Alert } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import * as FileSystem from 'expo-file-system';
import * as Haptics from 'expo-haptics';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { apiFetch } from '@/shared/lib/api';
import { useDownloadTokenStore } from '@/features/payment/downloadTokenStore';
import { Colors, Spacing } from '@/shared/constants/theme';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function SuccessScreen() {
  const { reel_id } = useLocalSearchParams<{ reel_id: string }>();
  const router = useRouter();
  const dt = useDownloadTokenStore((s) => s.get(reel_id));
  const clearToken = useDownloadTokenStore((s) => s.clear);
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);

  const download = async () => {
    if (!dt) { Alert.alert('Error', 'No download token'); return; }
    setDownloading(true);
    try {
      // The payment is confirmed asynchronously by the webhook, so the download
      // endpoint returns 403 until status='completed'. Retry with backoff so a
      // just-finished purchase still works without unlocking anything early.
      let downloadUrl: string | undefined;
      const delays = [0, 1500, 3000, 5000, 5000];
      for (let i = 0; i < delays.length; i++) {
        if (delays[i]) await sleep(delays[i]);
        try {
          ({ downloadUrl } = await apiFetch<{ downloadUrl: string }>(`/api/download/${dt}`));
          break;
        } catch (err: any) {
          const pending = String(err?.message ?? '').includes('403');
          if (!pending || i === delays.length - 1) throw err;
        }
      }
      if (!downloadUrl) throw new Error('Download not ready');

      const dest = FileSystem.documentDirectory + `sportreel_${reel_id}.mp4`;
      await FileSystem.downloadAsync(downloadUrl, dest);
      setDownloaded(true);
      clearToken(reel_id);
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Alert.alert('Downloaded!', 'Your clip has been saved to your device.');
    } catch (e: any) {
      Alert.alert('Download failed', e.message);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <SafeArea>
      <View style={styles.container}>
        <Text style={{ fontSize: 72, textAlign: 'center' }}>🎬</Text>
        <Text variant="display" style={{ textAlign: 'center' }}>You own it!</Text>
        <Text variant="body" color={Colors.textSecondary} style={{ textAlign: 'center' }}>
          Payment confirmed. Your clip is ready to download.
        </Text>
        <Spacer size={Spacing.xl} />
        {downloaded ? (
          <Text variant="title" color={Colors.success} style={{ textAlign: 'center' }}>✓ Saved to your device</Text>
        ) : (
          <Button label={downloading ? 'Downloading…' : 'Download to Phone'} onPress={download} loading={downloading} />
        )}
        <Spacer size={Spacing.md} />
        <Button label="Back to Discover" onPress={() => router.replace('/(tabs)/discover')} variant="ghost" />
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.xl, justifyContent: 'center', gap: Spacing.sm },
});
