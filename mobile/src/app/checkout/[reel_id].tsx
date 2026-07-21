import React, { useState } from 'react';
import { Alert, View, StyleSheet, Modal } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { PaymentSheetError, useStripe } from '@stripe/stripe-react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { BitWebView } from '@/features/payment/components/BitWebView';
import { useCheckout } from '@/features/payment/hooks/useCheckout';
import { useDownloadTokenStore } from '@/features/payment/downloadTokenStore';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function CheckoutScreen() {
  const { reel_id } = useLocalSearchParams<{ reel_id: string }>();
  const router = useRouter();
  const { initPaymentSheet, presentPaymentSheet } = useStripe();
  const { createStripeCheckout, createMeshulamCheckout, loading, error } = useCheckout(reel_id);
  const setDownloadToken = useDownloadTokenStore((state) => state.set);
  const [paymentSheetBusy, setPaymentSheetBusy] = useState(false);
  const [bitUrl, setBitUrl] = useState<string | null>(null);
  const [priceDisplay, setPriceDisplay] = useState<string>('');

  const handleStripe = async () => {
    setPaymentSheetBusy(true);
    try {
      const checkout = await createStripeCheckout();
      if (!checkout) return;

      setPriceDisplay(`₪${(checkout.amount_ils / 100).toFixed(0)}`);
      await setDownloadToken(reel_id, checkout.download_token);

      const { error: initError } = await initPaymentSheet({
        paymentIntentClientSecret: checkout.clientSecret,
        merchantDisplayName: 'SportReel',
        returnURL: 'sportreel://stripe-redirect',
        allowsDelayedPaymentMethods: false,
      });
      if (initError) {
        Alert.alert('Could not open secure checkout', initError.message);
        return;
      }

      const { error: presentError } = await presentPaymentSheet();
      if (!presentError) {
        // PaymentSheet confirms with Stripe, but durable product fulfillment is
        // owned by the signed webhook. The next screen waits for that evidence.
        router.replace(`/success/${reel_id}`);
        return;
      }

      if (presentError.code !== PaymentSheetError.Canceled) {
        Alert.alert('Payment failed', presentError.message);
      }
    } catch (paymentError) {
      Alert.alert(
        'Payment unavailable',
        paymentError instanceof Error ? paymentError.message : 'Unable to start payment',
      );
    } finally {
      setPaymentSheetBusy(false);
    }
  };

  const handleBit = async () => {
    const checkout = await createMeshulamCheckout();
    if (!checkout) return;
    setPriceDisplay(`₪${(checkout.amount_ils / 100).toFixed(0)}`);
    await setDownloadToken(reel_id, checkout.download_token);
    setBitUrl(checkout.paymentUrl);
  };

  if (bitUrl) {
    return (
      <Modal animationType="slide" presentationStyle="fullScreen">
        <BitWebView
          reelId={reel_id}
          paymentUrl={bitUrl}
          onSuccess={() => {
            setBitUrl(null);
            router.replace(`/success/${reel_id}`);
          }}
          onCancel={() => setBitUrl(null)}
        />
      </Modal>
    );
  }

  const busy = loading || paymentSheetBusy;

  return (
    <SafeArea>
      <View style={styles.container}>
        <Text variant="display" style={{ textAlign: 'center' }}>Get Your Clip</Text>
        <Spacer size={Spacing.sm} />
        <Text variant="body" color={Colors.textSecondary} style={{ textAlign: 'center' }}>
          Download your personal highlight reel forever.
        </Text>
        <Spacer size={Spacing.xl} />

        <Card bordered style={styles.priceCard}>
          <Text variant="headline" style={{ textAlign: 'center' }}>{priceDisplay || 'One-time purchase'}</Text>
          <Text variant="caption" color={Colors.textSecondary} style={{ textAlign: 'center' }}>
            4K personal video · yours forever
          </Text>
        </Card>

        <Spacer size={Spacing.xl} />
        {error && <Text variant="caption" color={Colors.danger}>{error}</Text>}

        <Button label="Pay with Card" onPress={handleStripe} loading={busy} disabled={busy} />
        <Spacer size={Spacing.md} />
        {!!process.env.EXPO_PUBLIC_BIT_ENABLED && (
          <>
            <Button label="Pay with Bit 📱" onPress={handleBit} loading={loading} disabled={busy} variant="secondary" />
            <Spacer size={Spacing.sm} />
          </>
        )}
        <Spacer size={Spacing.sm} />
        <Button label="Cancel" onPress={() => router.back()} disabled={busy} variant="ghost" />
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.xl, justifyContent: 'center' },
  priceCard: { alignItems: 'center', gap: 4 },
});
