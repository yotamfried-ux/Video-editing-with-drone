import React, { useEffect, useState } from 'react';
import { FlatList, View, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { useAuth } from '@/shared/hooks/useAuth';
import { Colors, Spacing } from '@/shared/constants/theme';
import { ReelThumb } from '@/features/sessions/components/ReelThumb';
import { supabase } from '@/shared/lib/supabase';
import type { ReelItem } from '@/features/sessions/hooks/useSessions';

export default function HighlightsScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [reels, setReels] = useState<ReelItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      router.replace('/(auth)/login');
      return;
    }
    const load = async () => {
      const { data: profile } = await supabase
        .from('athlete_profiles')
        .select('id')
        .eq('user_id', user.id)
        .single();

      if (profile) {
        const { data } = await supabase
          .from('reels')
          .select(
            'id, token, sport, recording_date, stream_uid, status, expires_at'
          )
          .eq('matched_athlete', profile.id)
          .order('created_at', { ascending: false });
        setReels((data as ReelItem[]) ?? []);
      }
      setLoading(false);
    };
    load();
  }, [user]);

  if (!user) return null;

  return (
    <SafeArea>
      <View style={styles.header}>
        <Text variant="display">My Highlights</Text>
        <Text variant="caption" color={Colors.textSecondary}>
          Your personal clip collection
        </Text>
      </View>
      <FlatList
        data={reels}
        keyExtractor={(r) => r.id}
        numColumns={2}
        columnWrapperStyle={styles.row}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => <ReelThumb reel={item} />}
        ListEmptyComponent={
          !loading ? (
            <View style={styles.empty}>
              <Text variant="headline" color={Colors.textSecondary}>
                No highlights yet
              </Text>
              <Text variant="body" color={Colors.textSecondary}>
                Add your photo to get notified when you appear in a clip.
              </Text>
            </View>
          ) : null
        }
      />
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  header: { padding: Spacing.lg, paddingBottom: Spacing.sm },
  list: { paddingHorizontal: Spacing.md, paddingBottom: Spacing.xl },
  row: { justifyContent: 'space-between' },
  empty: {
    flex: 1,
    alignItems: 'center',
    padding: Spacing.xxl,
    gap: Spacing.sm,
  },
});
