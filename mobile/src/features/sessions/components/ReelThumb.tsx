import React from 'react';
import { TouchableOpacity, View, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Text } from '@/shared/components/Text';
import { Badge } from '@/shared/components/Badge';
import { Colors, Radius, Spacing } from '@/shared/constants/theme';
import type { ReelItem } from '../hooks/useSessions';

type IconName = React.ComponentProps<typeof MaterialCommunityIcons>['name'];

const SPORT_ICON: Record<string, IconName> = {
  surfing: 'surfing',
  football: 'soccer',
  basketball: 'basketball',
  skateboarding: 'skateboarding',
  skiing: 'ski',
  snowboarding: 'snowboard',
  cycling: 'bike',
  mtb: 'bike-fast',
  default: 'movie-open-outline',
};

interface Props {
  reel: ReelItem;
}

export function ReelThumb({ reel }: Props) {
  const router = useRouter();
  const icon = SPORT_ICON[reel.sport] ?? SPORT_ICON.default;
  const isExpired = new Date(reel.expires_at) < new Date();
  const isSold = reel.status === 'sold';
  const badgeType = isSold ? 'sold' : isExpired ? 'expired' : 'live';

  return (
    <TouchableOpacity
      testID={`reel-thumb-${reel.id}-${badgeType}`}
      style={styles.thumb}
      onPress={() => router.push(`/reel/${reel.token}`)}
      activeOpacity={0.8}
      accessibilityRole="button"
    >
      <View style={styles.placeholder}>
        <MaterialCommunityIcons name={icon} size={44} color={Colors.textSecondary} />
        {!isSold && !isExpired ? (
          <View style={styles.play}>
            <MaterialCommunityIcons name="play" size={22} color={Colors.background} />
          </View>
        ) : null}
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
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    backgroundColor: Colors.card,
    marginBottom: Spacing.sm,
    overflow: 'hidden',
  },
  placeholder: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.md,
    backgroundColor: Colors.card,
  },
  play: {
    width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
    backgroundColor: Colors.accent,
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
