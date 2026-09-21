import React, { useState } from 'react';
import { Alert, Linking, StyleSheet, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { useCheckout } from '@/features/payment/hooks/useCheckout';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function CheckoutScreen() {
  const { reel_id: token } = useLocalSearchParams<{ reel_id: string }>();
  const router = useRouter();
  const { createStripeCheckout, loading, error } = useCheckout(token);
  const [priceDisplay, setPriceDisplay] = useState<string>('');

  const handleStripe = async () => {
    const checkout = await createStripeCheckout();
    if (!checkout) return;
    setPriceDisplay(`₪${(checkout.amount_ils / 100).toFixed(0)}`);
    if (!checkout.checkout_url) {
      Alert.alert('Checkout failed', 'Stripe Checkout URL was not returned');
      return;
    }
    try {
      await Linking.openURL(checkout.checkout_url);
    } catch {
      Alert.alert('Checkout failed', 'Cannot open Stripe checkout on this device');
    }
  };

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
