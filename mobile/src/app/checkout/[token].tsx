import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { useCheckout } from '@/features/payment/hooks/useCheckout';
import { formatIls } from '@/features/payment/lib/checkout';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function CheckoutScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  const { checkout, loading, error, start } = useCheckout(token);

  return (
    <SafeArea>
      <View style={styles.container}>
        <Button
          testID="checkout-back"
          label="← Back"
          onPress={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/discover'))}
          variant="ghost"
          style={styles.backButton}
        />
        <Card bordered style={styles.card}>
          <Text variant="display">Buy this clip</Text>
          <Text variant="body" color={Colors.textSecondary}>
            Payment opens on a secure payment page in your browser. After paying, come back to SportReel to see
            the clip marked as sold.
          </Text>
          {checkout && (
            <Text variant="title" color={Colors.accent}>
              {formatIls(checkout.amount_ils)}
            </Text>
          )}
          {error && (
            <Text testID="checkout-error" variant="caption" color={Colors.danger}>
              {error}
            </Text>
          )}
          <Button
            testID="checkout-continue"
            label={loading ? 'Opening payment…' : checkout ? 'Open payment page again' : 'Continue to payment'}
            loading={loading}
            onPress={start}
          />
          <Text variant="caption" color={Colors.textSecondary}>
            Your card details are entered on the payment provider's page and are never stored in SportReel.
          </Text>
        </Card>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg, justifyContent: 'center' },
  backButton: { alignSelf: 'flex-start', marginBottom: Spacing.md },
  card: { gap: Spacing.md },
});
