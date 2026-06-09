import React from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { RevenueChart } from '@/features/operator/components/RevenueChart';
import { useOperatorAnalytics } from '@/features/operator/hooks/useAnalytics';
import { Colors, Spacing, Radius } from '@/shared/constants/theme';

function FunnelBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? value / max : 0;
  return (
    <View style={{ gap: 4 }}>
      <View style={styles.funnelLabel}>
        <Text variant="caption" color={Colors.textSecondary}>{label}</Text>
        <Text variant="caption">{value}</Text>
      </View>
      <View style={styles.funnelTrack}>
        <View style={[styles.funnelFill, { width: `${Math.max(pct * 100, 2)}%` }]} />
      </View>
    </View>
  );
}

export default function AnalyticsScreen() {
  const data = useOperatorAnalytics();

  if (!data) {
    return (
      <SafeArea>
        <View style={styles.container}>
          <OperatorNav />
          <Text variant="body" color={Colors.textSecondary}>Loading analytics…</Text>
        </View>
      </SafeArea>
    );
  }

  const conversion = data.funnelViewed > 0
    ? ((data.funnelPaid / data.funnelViewed) * 100).toFixed(1)
    : '0.0';
  const expiryRate = data.totalReels > 0
    ? ((data.expiredReels / data.totalReels) * 100).toFixed(0)
    : '0';

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <ScrollView contentContainerStyle={{ gap: Spacing.md, paddingBottom: Spacing.xl }}>
          <Text variant="display">Analytics</Text>

          <RevenueChart
            todayRevenue={data.todayRevenue}
            weekRevenue={data.weekRevenue}
            monthRevenue={data.monthRevenue}
          />

          <Card bordered style={{ gap: Spacing.md }}>
            <Text variant="title">Conversion Funnel</Text>
            <FunnelBar label="Viewed" value={data.funnelViewed} max={data.funnelViewed} />
            <FunnelBar label="Checkout started" value={data.funnelCheckout} max={data.funnelViewed} />
            <FunnelBar label="Paid" value={data.funnelPaid} max={data.funnelViewed} />
            <Spacer size={Spacing.xs} />
            <Text variant="caption" color={Colors.accent}>
              {conversion}% view → purchase conversion
            </Text>
          </Card>

          <View style={styles.statRow}>
            <Card bordered style={styles.stat}>
              <Text variant="headline" color={Colors.success}>{data.soldReels}</Text>
              <Text variant="caption" color={Colors.textSecondary}>Sold</Text>
            </Card>
            <Card bordered style={styles.stat}>
              <Text variant="headline" color={Colors.danger}>{expiryRate}%</Text>
              <Text variant="caption" color={Colors.textSecondary}>Expiry rate</Text>
            </Card>
            <Card bordered style={styles.stat}>
              <Text variant="headline">{data.totalReels}</Text>
              <Text variant="caption" color={Colors.textSecondary}>Total reels</Text>
            </Card>
          </View>
        </ScrollView>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  funnelLabel: { flexDirection: 'row', justifyContent: 'space-between' },
  funnelTrack: { height: 10, borderRadius: Radius.full, backgroundColor: Colors.background, overflow: 'hidden' },
  funnelFill: { height: '100%', backgroundColor: Colors.accent, borderRadius: Radius.full },
  statRow: { flexDirection: 'row', gap: Spacing.sm },
  stat: { flex: 1, alignItems: 'center', gap: 4 },
});
