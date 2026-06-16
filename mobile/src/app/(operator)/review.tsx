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
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import { Colors, Spacing } from '@/shared/constants/theme';

interface DraftRow {
  id: string;
  name: string;
  created_at: string;
  size: number | null;
  watch_url: string | null;
}

function formatSize(bytes: number | null): string {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

export default function OperatorReviewScreen() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);
  const [reeditTarget, setReeditTarget] = useState<DraftRow | null>(null);
  const [reeditNotes, setReeditNotes] = useState('');
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
      const { drafts: data } = await operatorFetch<{ drafts: DraftRow[] }>(
        '/api/operator/drafts'
      );
      setDrafts(data ?? []);
      setLoadError(null);
    } catch (e) {
      setDrafts([]);
      setLoadError(e instanceof Error ? e.message : 'Failed to load drafts');
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

  const approve = (draft: DraftRow) => {
    Alert.alert(
      'Approve this reel?',
      `"${draft.name}" will move to APPROVED and get delivered to the athlete on the next pipeline run.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Approve',
          onPress: async () => {
            setApproving(draft.id);
            try {
              await operatorFetch('/api/operator/drafts/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_id: draft.id }),
              });
              setDrafts((d) => d.filter((x) => x.id !== draft.id));
              Alert.alert('Approved ✅', 'The reel moved to APPROVED and will be delivered on the next run.');
            } catch (e) {
              handleOperatorError(e);
            } finally {
              setApproving(null);
            }
          },
        },
      ]
    );
  };

  const submitReedit = async () => {
    if (!reeditTarget) return;
    setSubmitting(true);
    try {
      await operatorFetch('/api/operator/reprocess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          draft_name: reeditTarget.name,
          notes: reeditNotes.trim(),
        }),
      });
      setReeditTarget(null);
      setReeditNotes('');
      Alert.alert(
        'Sent for re-edit',
        'The source footage will be reprocessed with your notes on the next pipeline run.'
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
          data={drafts}
          keyExtractor={(d) => d.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.accent} />}
          ListHeaderComponent={
            <View style={{ marginBottom: Spacing.md }}>
              <Text variant="display">Review</Text>
              <Text variant="caption" color={Colors.textSecondary}>
                Drafts waiting for your approval · pull to refresh
              </Text>
            </View>
          }
          ListEmptyComponent={
            !loaded ? (
              <ActivityIndicator color={Colors.accent} style={{ marginTop: Spacing.xl }} />
            ) : loadError ? (
              <Card bordered style={{ gap: Spacing.sm, borderColor: Colors.danger }}>
                <Text variant="title">Couldn't load drafts</Text>
                <Text variant="caption" color={Colors.textSecondary}>{loadError}</Text>
              </Card>
            ) : (
              <Text variant="body" color={Colors.textSecondary}>
                No drafts waiting for review. 🎉
              </Text>
            )
          }
          ItemSeparatorComponent={() => <View style={{ height: Spacing.sm }} />}
          renderItem={({ item }) => (
            <Card bordered style={{ gap: Spacing.sm }}>
              <Text variant="title" numberOfLines={2}>{item.name}</Text>
              <Text variant="caption" color={Colors.textSecondary}>
                {new Date(item.created_at).toLocaleString()}
                {item.size ? ` · ${formatSize(item.size)}` : ''}
              </Text>
              {item.watch_url && (
                <Button
                  label="▶ Watch in Drive"
                  onPress={() => Linking.openURL(item.watch_url!)}
                  variant="ghost"
                  style={{ height: 44 }}
                />
              )}
              <View style={styles.actions}>
                <Button
                  label="Send to re-edit"
                  onPress={() => {
                    setReeditNotes('');
                    setReeditTarget(item);
                  }}
                  variant="secondary"
                  style={{ flex: 1, height: 44 }}
                />
                <Button
                  label={approving === item.id ? 'Approving…' : '✓ Approve'}
                  onPress={() => approve(item)}
                  disabled={approving !== null}
                  style={{ flex: 1, height: 44 }}
                />
              </View>
            </Card>
          )}
        />
      </View>

      <Modal
        visible={reeditTarget !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setReeditTarget(null)}
      >
        <View style={styles.modalBackdrop}>
          <Card bordered style={styles.modalCard}>
            <Text variant="title">Send draft to re-edit</Text>
            <Text variant="caption" color={Colors.textSecondary} numberOfLines={1}>
              {reeditTarget?.name}
            </Text>
            <Text variant="body" color={Colors.textSecondary}>
              Describe what to change — your notes go straight to the editing AI
              (e.g. "wrong surfer in clip 3", "too much slow-mo").
            </Text>
            <TextInput
              style={styles.notesInput}
              value={reeditNotes}
              onChangeText={setReeditNotes}
              placeholder="Notes for the re-edit…"
              placeholderTextColor={Colors.textSecondary}
              multiline
              numberOfLines={4}
              textAlignVertical="top"
            />
            <View style={styles.actions}>
              <Button
                label="Cancel"
                onPress={() => setReeditTarget(null)}
                variant="ghost"
                style={{ flex: 1, height: 44 }}
              />
              <Button
                label={submitting ? 'Sending…' : 'Send for re-edit'}
                onPress={submitReedit}
                disabled={submitting || !reeditNotes.trim()}
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
  actions: { flexDirection: 'row', gap: Spacing.sm },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    padding: Spacing.lg,
  },
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
