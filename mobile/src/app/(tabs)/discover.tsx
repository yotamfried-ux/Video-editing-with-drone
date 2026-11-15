import React from 'react';
import {
  FlatList,
  View,
  StyleSheet,
  RefreshControl,
} from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { EmptyState } from '@/shared/components/EmptyState';
import { Skeleton } from '@/shared/components/Skeleton';
import { SessionCard } from '@/features/sessions/components/SessionCard';
import { ReelThumb } from '@/features/sessions/components/ReelThumb';
import { useSessions } from '@/features/sessions/hooks/useSessions';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function DiscoverScreen() {
  const { sessions, loading, error, refresh, loadMore, hasMore } = useSessions();

  return (
    <SafeArea>
      <View style={styles.header}>
        <Text variant="display">SportReel</Text>
        <Text variant="caption" color={Colors.textSecondary}>
          Your clips from the water, ready to watch
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
          loading ? (
            // The shape of what is coming, so the screen does not jump when it arrives.
            <View testID="discover-loading">
              <Skeleton style={styles.skeletonTitle} />
              <View style={styles.grid}>
                {[0, 1, 2, 3].map((i) => <Skeleton key={i} style={styles.skeletonThumb} />)}
              </View>
            </View>
          ) : error ? (
            // A failed request is not "no sessions": say so and offer a retry.
            <EmptyState
              testID="discover-error"
              icon="wifi-off"
              title="Could not load sessions"
              body="Check your connection and try again."
              actionLabel="Try Again"
              actionTestID="discover-retry"
              onAction={refresh}
            />
          ) : (
            <EmptyState
              icon="video-outline"
              title="No sessions yet"
              body="Clips appear here after a filmed session. Pull down to refresh."
            />
          )
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
  skeletonTitle: { height: 22, width: '55%', margin: Spacing.md },
  skeletonThumb: { width: '48%', aspectRatio: 9 / 16, marginBottom: Spacing.sm },
});
