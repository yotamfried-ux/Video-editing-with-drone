import React from 'react';
import { TouchableOpacity, View, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { Text } from '@/shared/components/Text';
import { Badge } from '@/shared/components/Badge';
import { Colors, Radius, Spacing } from '@/shared/constants/theme';
import type { ReelItem } from '../hooks/useSessions';

const SPORT_EMOJI: Record<string, string> = {
  surfing: '🏄',
  football: '⚽',
  basketball: '🏀',
  skateboarding: '🛹',
  skiing: '⛷️',
  snowboarding: '🏂',
  cycling: '🚴',
  mtb: '🚵',
  default: '🎬',
};

interface Props {
  reel: ReelItem;
}

export function ReelThumb({ reel }: Props) {
  const router = useRouter();
  const emoji = SPORT_EMOJI[reel.sport] ?? SPORT_EMOJI.default;
  const isExpired = new Date(reel.expires_at) < new Date();
  const isSold = reel.status === 'sold';
  const badgeType = isSold ? 'sold' : isExpired ? 'expired' : 'live';

  return (
    <TouchableOpacity
      style={styles.thumb}
      onPress={() => router.push(`/reel/${reel.token}`)}
      activeOpacity={0.8}
    >
      <View style={styles.placeholder}>
        <Text style={{ fontSize: 36 }}>{emoji}</Text>
      </View>
      <View style={styles.overlay}>
        <Badge
          type={badgeType}
          expiresAt={!isSold && !isExpired ? reel.expires_at : undefined}
        />
      </View>
      <View style={styles.label}>
        <Text variant="caption" color={Colors.textSecondary}>
          {reel.sport ?? 'Sport'}
        </Text>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  thumb: {
    width: '48%',
    aspectRatio: 9 / 16,
    borderRadius: Radius.md,
    backgroundColor: Colors.card,
    marginBottom: Spacing.sm,
    overflow: 'hidden',
  },
  placeholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.card,
  },
  overlay: {
    position: 'absolute',
    top: Spacing.sm,
    left: Spacing.sm,
  },
  label: {
    position: 'absolute',
    bottom: Spacing.sm,
    left: Spacing.sm,
  },
});
