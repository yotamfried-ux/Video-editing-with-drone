import React from 'react';
import { View, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Text } from '@/shared/components/Text';
import { useOperatorUnlock } from '@/features/operator/hooks/useOperatorUnlock';
import { Colors, Spacing, Radius } from '@/shared/constants/theme';

const TABS = [
  { id: 'pipeline', icon: 'cog-play-outline', label: 'Pipeline', path: '/(operator)/pipeline' },
  { id: 'review', icon: 'clipboard-check-outline', label: 'Review', path: '/(operator)/review' },
  { id: 'analytics', icon: 'chart-line', label: 'Analytics', path: '/(operator)/analytics' },
  { id: 'pricing', icon: 'cash-multiple', label: 'Pricing', path: '/(operator)/pricing' },
  { id: 'reels', icon: 'filmstrip', label: 'Reels', path: '/(operator)/reels' },
  { id: 'athletes', icon: 'account-group-outline', label: 'Athletes', path: '/(operator)/athletes' },
  { id: 'support', icon: 'lifebuoy', label: 'Support', path: '/(operator)/support' },
  { id: 'settings', icon: 'cog-outline', label: 'Settings', path: '/(operator)/settings' },
] as const;

export function OperatorNav() {
  const router = useRouter();
  const pathname = usePathname();

  return (
    <View style={styles.wrap}>
      <View style={styles.header}>
        <Text variant="caption" color={Colors.accent}>OPERATOR · SPORTREEL</Text>
        <TouchableOpacity
          style={styles.exit}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityLabel="Exit operator mode"
          onPress={() => {
            // Re-lock so the next entry requires biometric again.
            useOperatorUnlock.getState().lock();
            router.replace('/(tabs)/discover');
          }}
        >
          <Text variant="caption" color={Colors.textSecondary}>Exit ✕</Text>
        </TouchableOpacity>
      </View>
      <ScrollView testID="operator-nav-scroll" horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
        {TABS.map((t) => {
          const active = pathname.split('/').pop() === t.path.split('/').pop();
          return (
            <TouchableOpacity
              key={t.path}
              testID={`operator-nav-${t.id}`}
              onPress={() => router.replace(t.path as never)}
              style={[styles.tab, active && styles.tabActive]}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
            >
              <MaterialCommunityIcons name={t.icon} size={16} color={active ? Colors.background : Colors.textSecondary} />
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
  exit: { minHeight: 32, justifyContent: 'center' },
  tab: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    minHeight: 44,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm,
    borderRadius: Radius.full,
    backgroundColor: Colors.card,
  },
  tabActive: { backgroundColor: Colors.accent },
});
