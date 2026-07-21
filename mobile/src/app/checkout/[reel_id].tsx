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

const STRIPE_RETURN_URL = 'sportreel://stripe-redirect';

export default function CheckoutScreen() {
  const { reel_id } = useLocalSearchParams<{ reel_id: string }>();
  const router = useRouter();
  const { initPaymentSheet, presentPaymentSheet } = useStripe();
  const {
    createStripeCheckout,
    createMeshulamCheckout,
    payerEmail,
    loading,
    error,
  } = useCheckout(reel_id);
  const setDownloadToken = useDownloadTokenStore((state) => state.set);
  const [paymentSheetBusy, setPaymentSheetBusy] = useState(false);
  const [bitUrl, setBitUrl] = useState<string | null>(null);
  const [priceDisplay, setPriceDisplay] = useState<string>('');

  // Consumer store builds must fail closed. Internal/direct builds opt in
  // explicitly; a missing environment variable never enables an external
  // payment path for the digital video product.
  const externalDigitalPaymentsEnabled = process.env.EXPO_PUBLIC_STRIPE_IN_APP_ENABLED === 'true';
  const bitEnabled = externalDigitalPaymentsEnabled && process.env.EXPO_PUBLIC_BIT_ENABLED === 'true';

  const handleStripe = async () => {
    if (!externalDigitalPaymentsEnabled) {
      Alert.alert(
        'Card payment unavailable in this build',
        'This store-distributed build cannot sell digital video through an external payment provider. Use the approved store purchase flow.',
      );
      return;
    }

    setPaymentSheetBusy(true);
    try {
      const checkout = await createStripeCheckout();
      if (!checkout) return;

      setPriceDisplay(`₪${(checkout.amount_ils / 100).toFixed(0)}`);
      // Persist before presenting PaymentSheet. The token cannot unlock the file
      // until the signed Stripe webhook marks this payment completed.
      await setDownloadToken(reel_id, checkout.download_token);

      const { error: initError } = await initPaymentSheet({
        paymentIntentClientSecret: checkout.clientSecret,
        merchantDisplayName: 'SportReel',
        returnURL: STRIPE_RETURN_URL,
        allowsDelayedPaymentMethods: false,
        defaultBillingDetails: {
          email: payerEmail,
        },
      });
      if (initError) {
        Alert.alert(
          `Secure checkout setup failed (${initError.code})`,
          initError.message,
        );
        return;
      }

      const { error: presentError } = await presentPaymentSheet();
      if (!presentError) {
        // PaymentSheet confirmed with Stripe. Product fulfillment remains owned
        // by the signed webhook, so the next screen displays processing until
        // the server reports status='completed'.
        router.replace(`/success/${reel_id}`);
        return;
      }

      switch (presentError.code) {
        case PaymentSheetError.Canceled:
          return;
        case PaymentSheetError.Timeout:
          Alert.alert('Payment timed out', 'No purchase was unlocked. Try again with a stable connection.');
          return;
        case PaymentSheetError.Failed:
        default:
          Alert.alert(`Payment failed (${presentError.code})`, presentError.message);
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
    if (!bitEnabled) {
      Alert.alert(
        'Bit payment unavailable in this build',
        'External payment methods are disabled for this store-distributed digital product.',
      );
      return;
    }
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
        {!externalDigitalPaymentsEnabled && (
          <Text variant="caption" color={Colors.textSecondary} style={{ textAlign: 'center' }}>
            External payment providers are disabled in consumer store builds for digital-content compliance.
          </Text>
        )}

        <Button label="Pay with Card" onPress={handleStripe} loading={busy} disabled={busy || !externalDigitalPaymentsEnabled} />
        <Spacer size={Spacing.md} />
        {bitEnabled && (
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
