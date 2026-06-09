import React, { useState } from 'react';
import { View, StyleSheet, Modal } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useStripe } from '@stripe/stripe-react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { BitWebView } from '@/features/payment/components/BitWebView';
import { useCheckout } from '@/features/payment/hooks/useCheckout';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function CheckoutScreen() {
  const { reel_id } = useLocalSearchParams<{ reel_id: string }>();
  const router = useRouter();
  const { initPaymentSheet, presentPaymentSheet } = useStripe();
  const { createStripeCheckout, createMeshulamCheckout, loading, error } = useCheckout(reel_id);
  const [bitUrl, setBitUrl] = useState<string | null>(null);
  const [downloadToken, setDownloadToken] = useState<string | null>(null);
  const [priceDisplay, setPriceDisplay] = useState<string>('');

  const handleStripe = async () => {
    const checkout = await createStripeCheckout();
    if (!checkout) return;
    setPriceDisplay(`₪${(checkout.amount_ils / 100).toFixed(0)}`);
    setDownloadToken(checkout.download_token);
    await initPaymentSheet({
      paymentIntentClientSecret: checkout.clientSecret,
      merchantDisplayName: 'SportReel',
    });
    const { error: presentError } = await presentPaymentSheet();
    if (!presentError) {
      router.replace(`/success/${reel_id}?dt=${checkout.download_token}`);
    }
  };

  const handleBit = async () => {
    const checkout = await createMeshulamCheckout();
    if (!checkout) return;
    setPriceDisplay(`₪${(checkout.amount_ils / 100).toFixed(0)}`);
    setDownloadToken(checkout.download_token);
    setBitUrl(checkout.paymentUrl);
  };

  if (bitUrl) {
    return (
      <Modal animationType="slide" presentationStyle="fullScreen">
        <BitWebView
          paymentUrl={bitUrl}
          onSuccess={() => {
            setBitUrl(null);
            router.replace(`/success/${reel_id}?dt=${downloadToken}`);
          }}
          onCancel={() => setBitUrl(null)}
        />
      </Modal>
    );
  }

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
            HD quality · yours forever
          </Text>
        </Card>

        <Spacer size={Spacing.xl} />
        {error && <Text variant="caption" color={Colors.danger}>{error}</Text>}

        <Button label="Pay with Card" onPress={handleStripe} loading={loading} />
        <Spacer size={Spacing.md} />
        <Button label="Pay with Bit 📱" onPress={handleBit} loading={loading} variant="secondary" />
        <Spacer size={Spacing.sm} />
        <Button label="Cancel" onPress={() => router.back()} variant="ghost" />
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.xl, justifyContent: 'center' },
  priceCard: { alignItems: 'center', gap: 4 },
});
