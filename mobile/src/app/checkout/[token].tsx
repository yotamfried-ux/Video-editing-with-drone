import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { ScreenHeader } from '@/shared/components/ScreenHeader';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useCheckout } from '@/features/payment/hooks/useCheckout';
import { formatIls } from '@/features/payment/lib/checkout';
import { Colors, Spacing } from '@/shared/constants/theme';

function Point({ icon, text }: { icon: React.ComponentProps<typeof MaterialCommunityIcons>['name']; text: string }) {
  return (
    <View style={styles.point}>
      <MaterialCommunityIcons name={icon} size={20} color={Colors.success} />
      <View style={styles.pointText}><Text variant="body">{text}</Text></View>
    </View>
  );
}

export default function CheckoutScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const router = useRouter();
  const { checkout, loading, error, start } = useCheckout(token);

  return (
    <SafeArea>
      <ScreenHeader
        backTestID="checkout-back"
        onBack={() => (router.canGoBack() ? router.back() : router.replace('/(tabs)/discover'))}
      />
      <View style={styles.container}>
        <Card bordered style={styles.card}>
          <Text variant="display">Buy this clip</Text>
          {checkout && (
            <Text testID="checkout-price" variant="display" color={Colors.accent}>
              {formatIls(checkout.amount_ils)}
            </Text>
          )}
          <View style={styles.points}>
            <Point icon="movie-open-check-outline" text="The full clip in full quality, without the watermark" />
            <Point icon="download-outline" text="Download it from the clip's page after paying" />
            <Point icon="shield-lock-outline" text="Card details are entered on the payment provider's page and are never stored in SportReel" />
          </View>
          {error && (
            <Text testID="checkout-error" variant="caption" color={Colors.danger}>
              {error}
            </Text>
          )}
          <Button
            testID="checkout-continue"
            icon="lock-outline"
            label={loading ? 'Opening payment…' : checkout ? 'Open payment page again' : 'Continue to payment'}
            loading={loading}
            onPress={start}
          />
          <Text variant="caption" color={Colors.textSecondary}>
            Payment opens on a secure page in your browser. After paying, come back to SportReel.
          </Text>
        </Card>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg, justifyContent: 'center' },
  points: { gap: Spacing.sm },
  point: { flexDirection: 'row', gap: Spacing.sm, alignItems: 'flex-start' },
  pointText: { flex: 1 },
  card: { gap: Spacing.md },
});
