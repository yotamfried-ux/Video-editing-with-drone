import React, { useState } from 'react';
import { View, StyleSheet, ScrollView, TextInput } from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { usePricing } from '@/features/operator/hooks/usePricing';
import { Colors, Spacing } from '@/shared/constants/theme';

function PriceRow({
  sport,
  priceIls,
  saving,
  onSave,
}: {
  sport: string;
  priceIls: number;
  saving: boolean;
  onSave: (shekels: number) => void;
}) {
  // store as shekels (display), persist as agorot
  const [value, setValue] = useState(String(Math.round(priceIls / 100)));

  return (
    <Card bordered style={styles.row}>
      <View style={{ flex: 1 }}>
        <Text variant="title" style={{ textTransform: 'capitalize' }}>{sport}</Text>
        {sport === 'default' && (
          <Text variant="caption" color={Colors.textSecondary}>
            Fallback for unlisted sports
          </Text>
        )}
      </View>
      <View style={styles.priceInputWrap}>
        <Text variant="title" color={Colors.textSecondary}>₪</Text>
        <TextInput
          value={value}
          onChangeText={setValue}
          keyboardType="number-pad"
          style={styles.priceInput}
          placeholderTextColor={Colors.textSecondary}
        />
      </View>
      <Button
        label={saving ? '…' : 'Save'}
        onPress={() => {
          const n = parseInt(value, 10);
          if (!Number.isNaN(n)) onSave(n * 100);
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
            Set a one-time price per sport. Prices are in shekels (₪).
          </Text>

          {error && (
            <Text variant="caption" color={Colors.danger}>{error}</Text>
          )}

          {rows
            .slice()
            .sort((a, b) => (a.sport === 'default' ? 1 : b.sport === 'default' ? -1 : a.sport.localeCompare(b.sport)))
            .map((r) => (
              <PriceRow
                key={r.sport}
                sport={r.sport}
                priceIls={r.price_ils}
                saving={saving === r.sport}
                onSave={(agorot) => updatePrice(r.sport, agorot)}
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
              keyboardType="number-pad"
              style={styles.addInput}
            />
            <Button
              label="Add Sport"
              onPress={() => {
                const n = parseInt(newPrice, 10);
                if (newSport.trim() && !Number.isNaN(n)) {
                  addSport(newSport.trim().toLowerCase(), n * 100);
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
    minWidth: 56,
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
