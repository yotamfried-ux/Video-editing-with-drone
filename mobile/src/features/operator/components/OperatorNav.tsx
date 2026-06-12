import React from 'react';
import { View, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { Text } from '@/shared/components/Text';
import { useOperatorUnlock } from '@/features/operator/hooks/useOperatorUnlock';
import { Colors, Spacing, Radius } from '@/shared/constants/theme';

const TABS = [
  { label: 'Pipeline', path: '/(operator)/pipeline' },
  { label: 'Review', path: '/(operator)/review' },
  { label: 'Analytics', path: '/(operator)/analytics' },
  { label: 'Pricing', path: '/(operator)/pricing' },
  { label: 'Reels', path: '/(operator)/reels' },
  { label: 'Support', path: '/(operator)/support' },
  { label: 'Settings', path: '/(operator)/settings' },
] as const;

export function OperatorNav() {
  const router = useRouter();
  const pathname = usePathname();

  return (
    <View style={styles.wrap}>
      <View style={styles.header}>
        <Text variant="caption" color={Colors.accent}>OPERATOR · SPORTREEL</Text>
        <TouchableOpacity
          onPress={() => {
            // Re-lock so the next entry requires biometric again.
            useOperatorUnlock.getState().lock();
            router.replace('/(tabs)/discover');
          }}
        >
          <Text variant="caption" color={Colors.textSecondary}>Exit ✕</Text>
        </TouchableOpacity>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
        {TABS.map((t) => {
          const active = pathname.includes(t.path.split('/').pop()!);
          return (
            <TouchableOpacity
              key={t.path}
              onPress={() => router.replace(t.path as never)}
              style={[styles.tab, active && styles.tabActive]}
            >
              <Text variant="caption" color={active ? Colors.background : Colors.textSecondary}>
                {t.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: Spacing.sm, paddingBottom: Spacing.sm },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  tabs: { gap: Spacing.xs, paddingVertical: Spacing.xs },
  tab: {
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Radius.full,
    backgroundColor: Colors.card,
  },
  tabActive: { backgroundColor: Colors.accent },
});
