import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors, Radius, Spacing } from '../constants/theme';

type BadgeType = 'live' | 'sold' | 'expired';

interface Props {
  type: BadgeType;
  expiresAt?: string;
}

function formatCountdown(expiresAt: string): string {
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return 'Expired';
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export function Badge({ type, expiresAt }: Props) {
  const configs = {
    live:    { bg: Colors.danger,   text: expiresAt ? formatCountdown(expiresAt) : 'LIVE', label: '● ' },
    sold:    { bg: Colors.success,  text: 'Purchased', label: '' },
    expired: { bg: Colors.card,     text: 'Expired',   label: '' },
  };
  const cfg = configs[type];
  return (
    <View style={[styles.badge, { backgroundColor: cfg.bg }]}>
      <Text style={styles.text}>{cfg.label}{cfg.text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
    borderRadius: Radius.full,
  },
  text: { color: '#fff', fontSize: 11, fontWeight: '600' },
});
