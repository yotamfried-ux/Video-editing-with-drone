import React, { useEffect, useState, useCallback } from 'react';
import { View, StyleSheet, FlatList, Linking, RefreshControl } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Badge } from '@/shared/components/Badge';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import { Colors, Spacing } from '@/shared/constants/theme';

const APP_DOMAIN = process.env.EXPO_PUBLIC_APP_DOMAIN ?? 'sportreel.app';

interface ReelRow {
  id: string;
  token: string;
  sport: string | null;
  athlete_desc: string | null;
  status: string;
  expires_at: string;
  recording_date: string | null;
}

export default function OperatorReelsScreen() {
  const router = useRouter();
  const [reels, setReels] = useState<ReelRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    // reels no longer allow broad anon read; fetch via the operator API.
    try {
      const { reels: data } = await operatorFetch<{ reels: ReelRow[] }>('/api/operator/reels');
      setReels(data ?? []);
    } catch {
      setReels([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const share = (reel: ReelRow) => {
    const url = `https://${APP_DOMAIN}/reel/${reel.token}`;
    const msg = encodeURIComponent(
      `🎬 Your SportReel highlight is ready! Watch it here (available 48h): ${url}`
    );
    Linking.openURL(`whatsapp://send?text=${msg}`).catch(() =>
      Linking.openURL(`https://wa.me/?text=${msg}`)
    );
  };

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <FlatList
          data={reels}
          keyExtractor={(r) => r.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.accent} />}
          ListHeaderComponent={
            <View style={{ marginBottom: Spacing.md }}>
              <Text variant="display">Reels</Text>
              <Text variant="caption" color={Colors.textSecondary}>
                {reels.length} total · pull to refresh
              </Text>
            </View>
          }
          ListEmptyComponent={
            <Text variant="body" color={Colors.textSecondary}>No reels yet.</Text>
          }
          ItemSeparatorComponent={() => <View style={{ height: Spacing.sm }} />}
          renderItem={({ item }) => (
            <Card bordered style={{ gap: Spacing.sm }}>
              <View style={styles.cardHead}>
                <View style={{ flex: 1 }}>
                  <Text variant="title" style={{ textTransform: 'capitalize' }}>
                    {item.sport ?? 'Unknown sport'}
                  </Text>
                  <Text variant="caption" color={Colors.textSecondary} numberOfLines={1}>
                    {item.athlete_desc || 'No description'}
                    {item.recording_date ? ` · ${item.recording_date}` : ''}
                  </Text>
                </View>
                {item.status === 'sold' ? (
                  <Badge type="sold" />
                ) : item.status === 'expired' ? (
                  <Badge type="expired" />
                ) : (
                  <Badge type="live" expiresAt={item.expires_at} />
                )}
              </View>
              <View style={styles.actions}>
                <Button
                  label="Preview"
                  onPress={() => router.push(`/reel/${item.token}`)}
                  variant="ghost"
                  style={{ flex: 1, height: 44 }}
                />
                <Button
                  label="Share via WhatsApp"
                  onPress={() => share(item)}
                  variant="secondary"
                  style={{ flex: 1, height: 44 }}
                />
              </View>
            </Card>
          )}
        />
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  cardHead: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm },
  actions: { flexDirection: 'row', gap: Spacing.sm },
});
