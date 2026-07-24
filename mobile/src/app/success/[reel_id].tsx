import React, { useCallback, useEffect, useState } from 'react';
import { View, StyleSheet, Alert } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import * as FileSystem from 'expo-file-system';
import * as Haptics from 'expo-haptics';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { apiFetch } from '@/shared/lib/api';
import {
  clearCheckoutSessionId,
  useDownloadTokenStore,
} from '@/features/payment/downloadTokenStore';
import { Colors, Spacing } from '@/shared/constants/theme';

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
type FulfillmentState = 'checking' | 'pending' | 'completed' | 'failed' | 'missing';

type PaymentStatusResponse = {
  status: 'pending' | 'completed' | 'failed';
  ready: boolean;
};

export default function SuccessScreen() {
  const { reel_id } = useLocalSearchParams<{ reel_id: string }>();
  const router = useRouter();
  const cachedToken = useDownloadTokenStore((state) => state.get(reel_id));
  const hydrateToken = useDownloadTokenStore((state) => state.hydrate);
  const clearToken = useDownloadTokenStore((state) => state.clear);
  const [token, setToken] = useState<string | undefined>(cachedToken);
  const [fulfillment, setFulfillment] = useState<FulfillmentState>('checking');
  const [checking, setChecking] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloaded, setDownloaded] = useState(false);

  const checkPayment = useCallback(async (poll = false) => {
    setChecking(true);
    setFulfillment('checking');
    try {
      const resolvedToken = token ?? await hydrateToken(reel_id);
      if (!resolvedToken) {
        setFulfillment('missing');
        return;
      }
      setToken(resolvedToken);

      const delays = poll ? [0, 1200, 2000, 3000, 5000, 8000] : [0];
      for (const delay of delays) {
        if (delay) await sleep(delay);
        const payment = await apiFetch<PaymentStatusResponse>(`/api/payment-status/${resolvedToken}`);
        if (payment.status === 'completed') {
          await clearCheckoutSessionId(reel_id);
          setFulfillment('completed');
          return;
        }
        if (payment.status === 'failed') {
          // A terminal PaymentIntent must not be reused as the idempotent source
          // for a new attempt. Keep the token for support/audit, but rotate the
          // checkout session when the user returns to checkout.
          await clearCheckoutSessionId(reel_id);
          setFulfillment('failed');
          return;
        }
      }
      setFulfillment('pending');
    } catch (error) {
      setFulfillment('pending');
      if (!poll) {
        Alert.alert('Could not verify payment', error instanceof Error ? error.message : 'Status unavailable');
      }
    } finally {
      setChecking(false);
    }
  }, [hydrateToken, reel_id, token]);

  useEffect(() => {
    checkPayment(true).catch(() => {});
  }, [checkPayment]);

  const download = async () => {
    if (!token || fulfillment !== 'completed') {
      Alert.alert('Payment still processing', 'Wait for payment confirmation before downloading.');
      return;
    }
    if (!FileSystem.documentDirectory) {
      Alert.alert('Download unavailable', 'App document storage is unavailable on this device.');
      return;
    }

    setDownloading(true);
    try {
      const { downloadUrl } = await apiFetch<{ downloadUrl: string }>(`/api/download/${token}`);
      const destination = `${FileSystem.documentDirectory}sportreel_${reel_id}.mp4`;
      const result = await FileSystem.downloadAsync(downloadUrl, destination);
      if (result.status >= 300) throw new Error(`Download failed with status ${result.status}`);

      setDownloaded(true);
      await clearToken(reel_id);
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      Alert.alert('Downloaded!', 'Your clip has been saved to your device.');
    } catch (error) {
      Alert.alert('Download failed', error instanceof Error ? error.message : 'Download failed');
    } finally {
      setDownloading(false);
    }
  };

  const title = fulfillment === 'completed'
    ? 'Payment confirmed'
    : fulfillment === 'failed'
      ? 'Payment failed'
      : 'Finalizing payment';
  const message = fulfillment === 'completed'
    ? 'Stripe confirmed the payment and your clip is ready to download.'
    : fulfillment === 'failed'
      ? 'Stripe did not complete this payment. You have not been granted the download.'
      : fulfillment === 'missing'
        ? 'The secure purchase token is missing on this device. Contact support with the reel ID.'
        : 'The secure Stripe form finished. We are waiting for the signed server confirmation before unlocking the clip.';

  return (
    <SafeArea>
      <View style={styles.container}>
        <Text style={{ fontSize: 72, textAlign: 'center' }}>🎬</Text>
        <Text variant="display" style={{ textAlign: 'center' }}>{title}</Text>
        <Text variant="body" color={Colors.textSecondary} style={{ textAlign: 'center' }}>{message}</Text>
        <Spacer size={Spacing.xl} />

        {downloaded ? (
          <Text variant="title" color={Colors.success} style={{ textAlign: 'center' }}>✓ Saved to your device</Text>
        ) : fulfillment === 'completed' ? (
          <Button label={downloading ? 'Downloading…' : 'Download to Phone'} onPress={download} loading={downloading} disabled={downloading} />
        ) : fulfillment === 'failed' ? (
          <Button label="Return to checkout" onPress={() => router.replace(`/checkout/${reel_id}`)} variant="secondary" />
        ) : (
          <Button label={checking ? 'Checking…' : 'Check payment status'} onPress={() => checkPayment(false)} loading={checking} disabled={checking || fulfillment === 'missing'} variant="secondary" />
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
