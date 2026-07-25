import React, { useEffect, useState } from 'react';
import { View, StyleSheet, ScrollView, TextInput } from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { usePricing } from '@/features/operator/hooks/usePricing';
import { Colors, Spacing } from '@/shared/constants/theme';

function displayPrice(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

function parseMajorIls(value: string): number | null {
  const normalized = value.trim().replace(',', '.');
  if (!normalized) return null;
  const amount = Number(normalized);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  return Math.round(amount * 100) / 100;
}

function PriceRow({
  sport,
  priceIls,
  saving,
  onSave,
}: {
  sport: string;
  priceIls: number;
  saving: boolean;
  onSave: (majorIls: number) => void;
}) {
  const [value, setValue] = useState(displayPrice(priceIls));

  useEffect(() => {
    setValue(displayPrice(priceIls));
  }, [priceIls]);

  return (
    <Card bordered style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text variant="title" style={{ textTransform: 'capitalize' }}>{sport}</Text>
        {sport === 'default' && (
          <Text variant="caption" color={Colors.textSecondary}>Fallback for unlisted sports</Text>
        )}
      </View>
      <View style={styles.priceInputWrap}>
        <Text variant="title" color={Colors.textSecondary}>₪</Text>
        <TextInput
          value={value}
          onChangeText={setValue}
          keyboardType="decimal-pad"
          style={styles.priceInput}
          placeholderTextColor={Colors.textSecondary}
        />
      </View>
      <Button
        label={saving ? '…' : 'Save'}
        onPress={() => {
          const amount = parseMajorIls(value);
          if (amount !== null) onSave(amount);
        }}
        loading={saving}
        variant="secondary"
        style={{ height: 44, paddingHorizontal: Spacing.md }}
      />
    </Card>
  );
}

export default function PricingScreen() {
  const { rows, saving, error, updatePrice, addSport } = usePricing();
  const [newSport, setNewSport] = useState('');
  const [newPrice, setNewPrice] = useState('');

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <ScrollView contentContainerStyle={{ gap: Spacing.md, paddingBottom: Spacing.xl }}>
          <Text variant="display">Pricing</Text>
          <Text variant="caption" color={Colors.textSecondary}>
            Set a one-time price per sport in shekels. The server converts it to agorot only when creating the Stripe payment.
          </Text>

          {error && <Text variant="caption" color={Colors.danger}>{error}</Text>}

          {rows
            .slice()
            .sort((left, right) => (left.sport === 'default' ? 1 : right.sport === 'default' ? -1 : left.sport.localeCompare(right.sport)))
            .map((row) => (
              <PriceRow
                key={row.sport}
                sport={row.sport}
                priceIls={row.price_ils}
                saving={saving === row.sport}
                onSave={(majorIls) => updatePrice(row.sport, majorIls)}
              />
            ))}

          <Spacer size={Spacing.md} />
          <Card bordered style={{ gap: Spacing.sm }}>
            <Text variant="title">Add a Sport</Text>
            <TextInput
              value={newSport}
              onChangeText={setNewSport}
              placeholder="Sport name (e.g. skateboarding)"
              placeholderTextColor={Colors.textSecondary}
              autoCapitalize="none"
              style={styles.addInput}
            />
            <TextInput
              value={newPrice}
              onChangeText={setNewPrice}
              placeholder="Price in ₪"
              placeholderTextColor={Colors.textSecondary}
              keyboardType="decimal-pad"
              style={styles.addInput}
            />
            <Button
              label="Add Sport"
              onPress={() => {
                const amount = parseMajorIls(newPrice);
                const sport = newSport.trim().toLowerCase();
                if (sport && amount !== null) {
                  addSport(sport, amount);
                  setNewSport('');
                  setNewPrice('');
                }
              }}
            />
          </Card>
        </ScrollView>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  priceInputWrap: { flexDirection: 'row', alignItems: 'center', gap: 2 },
  priceInput: {
    color: Colors.textPrimary,
    fontSize: 18,
    fontWeight: '700',
    minWidth: 72,
    textAlign: 'right',
    paddingVertical: Spacing.xs,
  },
  addInput: {
    backgroundColor: Colors.background,
    color: Colors.textPrimary,
    borderRadius: 12,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    fontSize: 15,
  },
});
