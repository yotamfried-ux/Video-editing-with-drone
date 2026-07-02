import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  StyleSheet,
  FlatList,
  Linking,
  RefreshControl,
  Modal,
  TextInput,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Badge } from '@/shared/components/Badge';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import type { OperatorReelRow, OperatorReelsResponse, ReprocessSubmitResponse } from '@/features/operator/types/contracts';
import { Colors, Spacing } from '@/shared/constants/theme';

const APP_DOMAIN = process.env.EXPO_PUBLIC_APP_DOMAIN ?? 'sportreel.app';

function shortId(id?: string): string {
  return id ? id.slice(0, 8) : 'unknown';
}

export default function OperatorReelsScreen() {
  const router = useRouter();
  const [reels, setReels] = useState<OperatorReelRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [reprocessTarget, setReprocessTarget] = useState<OperatorReelRow | null>(null);
  const [reprocessNotes, setReprocessNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleOperatorError = (e: unknown) => {
    const msg = e instanceof Error ? e.message : 'Unknown error';
    if (msg.includes('secret not set')) {
      Alert.alert('Operator secret required', msg, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Go to Settings', onPress: () => router.push('/(operator)/settings' as never) },
      ]);
    } else {
      Alert.alert('Failed', msg);
    }
  };

  const load = useCallback(async () => {
    try {
      const { reels: data } = await operatorFetch<OperatorReelsResponse>('/api/operator/reels');
      setReels(data ?? []);
      setLoadError(null);
    } catch (e) {
      setReels([]);
      setLoadError(e instanceof Error ? e.message : 'Failed to load reels');
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const share = (reel: OperatorReelRow) => {
    const url = `https://${APP_DOMAIN}/reel/${reel.token}`;
    const msg = encodeURIComponent(
      `Your SportReel highlight is ready. Watch it here: ${url}`
    );
    Linking.openURL(`whatsapp://send?text=${msg}`).catch(() =>
      Linking.openURL(`https://wa.me/?text=${msg}`)
    );
  };

  const submitReprocess = async () => {
    if (!reprocessTarget) return;
    setSubmitting(true);
    try {
      const result = await operatorFetch<ReprocessSubmitResponse>('/api/operator/reprocess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reel_id: reprocessTarget.id,
          notes: reprocessNotes.trim(),
        }),
      });
      setReprocessTarget(null);
      setReprocessNotes('');
      Alert.alert(
        'Sent for re-edit',
        `Pipeline run: ${shortId(result.pipeline_run_id)}. Check Pipeline status for progress.`
      );
    } catch (e) {
      handleOperatorError(e);
    } finally {
      setSubmitting(false);
    }
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
            !loaded ? (
              <ActivityIndicator color={Colors.accent} style={{ marginTop: Spacing.xl }} />
            ) : loadError ? (
              <Card bordered style={{ gap: Spacing.sm, borderColor: Colors.danger }}>
                <Text variant="title">Could not load reels</Text>
                <Text variant="caption" color={Colors.textSecondary}>{loadError}</Text>
              </Card>
            ) : (
              <Text variant="body" color={Colors.textSecondary}>No reels yet.</Text>
            )
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
                <Button label="Preview" onPress={() => router.push(`/reel/${item.token}`)} variant="ghost" style={{ flex: 1, height: 44 }} />
                <Button label="Share via WhatsApp" onPress={() => share(item)} variant="secondary" style={{ flex: 1, height: 44 }} />
              </View>
              <Button
                label="Send back for re-edit"
                onPress={() => {
                  setReprocessNotes('');
                  setReprocessTarget(item);
                }}
                variant="ghost"
                style={{ height: 44 }}
              />
            </Card>
          )}
        />
      </View>

      <Modal visible={reprocessTarget !== null} transparent animationType="fade" onRequestClose={() => setReprocessTarget(null)}>
        <View style={styles.modalBackdrop}>
          <Card bordered style={styles.modalCard}>
            <Text variant="title">Re-edit reel</Text>
            <Text variant="caption" color={Colors.textSecondary}>{reprocessTarget?.athlete_desc || reprocessTarget?.sport || ''}</Text>
            <Text variant="body" color={Colors.textSecondary}>Describe what should change. Your notes go straight to the editing AI.</Text>
            <TextInput
              style={styles.notesInput}
              value={reprocessNotes}
              onChangeText={setReprocessNotes}
              placeholder="Notes for the re-edit..."
              placeholderTextColor={Colors.textSecondary}
              multiline
              numberOfLines={4}
              textAlignVertical="top"
            />
            <View style={styles.actions}>
              <Button label="Cancel" onPress={() => setReprocessTarget(null)} variant="ghost" style={{ flex: 1, height: 44 }} />
              <Button
                label={submitting ? 'Sending...' : 'Send for re-edit'}
                onPress={submitReprocess}
                disabled={submitting || !reprocessNotes.trim()}
                variant="secondary"
                style={{ flex: 1, height: 44 }}
              />
            </View>
          </Card>
        </View>
      </Modal>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  cardHead: { flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm },
  actions: { flexDirection: 'row', gap: Spacing.sm },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'center', padding: Spacing.lg },
  modalCard: { gap: Spacing.sm },
  notesInput: {
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 8,
    padding: Spacing.sm,
    minHeight: 96,
    color: Colors.textPrimary,
  },
});
