import React from 'react';
import {
  FlatList,
  View,
  StyleSheet,
  RefreshControl,
} from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { SessionCard } from '@/features/sessions/components/SessionCard';
import { ReelThumb } from '@/features/sessions/components/ReelThumb';
import { useSessions } from '@/features/sessions/hooks/useSessions';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function DiscoverScreen() {
  const { sessions, loading, refresh, loadMore, hasMore } = useSessions();

  return (
    <SafeArea>
      <View style={styles.header}>
        <Text variant="display">SportReel</Text>
        <Text variant="caption" color={Colors.textSecondary}>
          Catch your moments
        </Text>
      </View>
      <FlatList
        data={sessions}
        keyExtractor={(s) => `${s.recording_date}__${s.sport}`}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={refresh}
            tintColor={Colors.accent}
          />
        }
        onEndReached={() => hasMore && loadMore()}
        onEndReachedThreshold={0.3}
        contentContainerStyle={styles.list}
        renderItem={({ item: session }) => (
          <View>
            <SessionCard
              recording_date={session.recording_date}
              sport={session.sport}
              reelCount={session.reels.length}
            />
            <View style={styles.grid}>
              {session.reels.map((reel) => (
                <ReelThumb key={reel.id} reel={reel} />
              ))}
            </View>
          </View>
        )}
        ListEmptyComponent={
          !loading ? (
            <View style={styles.empty}>
              <Text variant="headline" color={Colors.textSecondary}>
                No sessions yet
              </Text>
              <Text variant="body" color={Colors.textSecondary}>
                Check back after a session!
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
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'space-between',
  },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xxl,
    gap: Spacing.sm,
  },
});
