import React, { useState } from 'react';
import { Alert, Linking, StyleSheet, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { apiFetch } from '@/shared/lib/api';
import { Colors, Spacing } from '@/shared/constants/theme';

type CheckoutResponse = {
  checkout_url: string | null;
  session_id: string;
  purchase_id: string;
  amount_ils: number;
  currency: string;
};

function formatIls(agorot: number): string {
  return `₪${(agorot / 100).toFixed(0)}`;
}

export default function CheckoutScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [checkout, setCheckout] = useState<CheckoutResponse | null>(null);

  const startCheckout = async () => {
    if (!token) return;

    // Reuse the existing Stripe session URL instead of creating a new purchase row.
    if (checkout?.checkout_url) {
      try {
        await Linking.openURL(checkout.checkout_url);
      } catch {
        Alert.alert('Checkout failed', 'Cannot open Stripe checkout on this device');
      }
      return;
    }

    setLoading(true);
    try {
      const result = await apiFetch<CheckoutResponse>(`/api/checkout/${token}`, {
        method: 'POST',
      });
      setCheckout(result);
      if (!result.checkout_url) throw new Error('Checkout URL was not returned');
      const canOpen = await Linking.canOpenURL(result.checkout_url);
      if (!canOpen) throw new Error('Cannot open Stripe checkout on this device');
      await Linking.openURL(result.checkout_url);
    } catch (e) {
      Alert.alert('Checkout failed', e instanceof Error ? e.message : 'Could not start checkout');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeArea>
      <View style={styles.container}>
        <Button label="← Back" onPress={() => router.back()} variant="ghost" style={styles.backButton} />
        <Card bordered style={styles.card}>
          <Text variant="display">Buy this clip</Text>
          <Text variant="body" color={Colors.textSecondary}>
            Payment opens in Stripe Checkout. After payment, return to SportReel to see the clip marked as sold.
          </Text>
          {checkout && (
            <Text variant="title" color={Colors.accent}>
              {formatIls(checkout.amount_ils)}
            </Text>
          )}
          <Button
            label={loading ? 'Opening checkout…' : checkout ? 'Open checkout again' : 'Continue to payment'}
            loading={loading}
            onPress={startCheckout}
          />
          <Text variant="caption" color={Colors.textSecondary}>
            Secure payment handled by Stripe. Your payment details are never stored in SportReel.
          </Text>
        </Card>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: Spacing.lg,
    justifyContent: 'center',
  },
  backButton: {
    alignSelf: 'flex-start',
    marginBottom: Spacing.md,
  },
  card: {
    gap: Spacing.md,
  },
});
