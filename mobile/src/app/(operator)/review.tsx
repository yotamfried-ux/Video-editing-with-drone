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
import type { ApproveDraftResponse, DraftRow, DraftsResponse, ReprocessSubmitResponse } from '@/features/operator/types/contracts';
import { Colors, Spacing } from '@/shared/constants/theme';

function formatSize(bytes: number | null): string {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

function shortId(id?: string): string {
  return id ? id.slice(0, 8) : 'unknown';
}

function draftIsApprovalBlocked(draft: DraftRow): boolean {
  return Boolean(draft.approval_blocked || draft.review_required || draft.name.toUpperCase().includes('QA-FLAGGED'));
}

function approvalReasons(draft: DraftRow): string[] {
  const reasons = Array.isArray(draft.approval_blocked_reasons) ? draft.approval_blocked_reasons.filter(Boolean) : [];
  if (!reasons.length && draft.name.toUpperCase().includes('QA-FLAGGED')) {
    return ['Draft is QA-FLAGGED and must be sent to re-edit or manually reviewed before approval.'];
  }
  return reasons;
}

function showApprovalResult(result: ApproveDraftResponse) {
  if (result.delivery_started) {
    Alert.alert(
      'Delivery started',
      `Delivery workflow started. Delivery run: ${shortId(result.delivery_run_id)}.`,
    );
    return;
  }

  Alert.alert(
    'Approved, delivery not started',
    `The draft moved to APPROVED, but no delivery workflow was started. Delivery run: ${shortId(result.delivery_run_id)}. Check Delivery status before retrying.`,
  );
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
      const { drafts: data } = await operatorFetch<DraftsResponse>(
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
    const blocked = draftIsApprovalBlocked(draft);
    if (blocked) {
      Alert.alert(
        'Approval blocked',
        `${draft.name} requires review before approval. Send it to re-edit or clear the QA block first.\n\n${approvalReasons(draft).join('\n')}`
      );
      return;
    }
    Alert.alert(
      'Approve this reel?',
      `"${draft.name}" will move to APPROVED and start the delivery workflow now.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Approve',
          onPress: async () => {
            setApproving(draft.id);
            try {
              const result = await operatorFetch<ApproveDraftResponse>('/api/operator/drafts/approve', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  file_id: draft.id,
                  file_name: draft.name,
                  review_required: draft.review_required,
                  approval_blocked_reasons: draft.approval_blocked_reasons,
                }),
              });
              setDrafts((d) => d.filter((x) => x.id !== draft.id));
              showApprovalResult(result);
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
      const { pipeline_run_id: pipelineRunId } = await operatorFetch<ReprocessSubmitResponse>('/api/operator/reprocess', {
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
        `Pipeline run: ${shortId(pipelineRunId)}. Check Pipeline status for progress.`
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
                <Text variant="title">Could not load drafts</Text>
                <Text variant="caption" color={Colors.textSecondary}>{loadError}</Text>
              </Card>
            ) : (
              <Text variant="body" color={Colors.textSecondary}>
                No drafts waiting for review.
              </Text>
            )
          }
          ItemSeparatorComponent={() => <View style={{ height: Spacing.sm }} />}
          renderItem={({ item }) => {
            const blocked = draftIsApprovalBlocked(item);
            const reasons = approvalReasons(item);
            return (
              <Card bordered style={{ gap: Spacing.sm, borderColor: blocked ? Colors.danger : Colors.cardBorder }}>
                <Text variant="title" numberOfLines={2}>{item.name}</Text>
                <Text variant="caption" color={Colors.textSecondary}>
                  {new Date(item.created_at).toLocaleString()}
                  {item.size ? ` · ${formatSize(item.size)}` : ''}
                </Text>
                {blocked && (
                  <View style={styles.qaBlock}>
                    <Text variant="title">Approval blocked</Text>
                    <Text variant="caption" color={Colors.textSecondary}>
                      This draft must be sent to re-edit or manually reviewed before approval.
                    </Text>
                    {reasons.slice(0, 3).map((r) => (
                      <Text key={r} variant="caption" color={Colors.textSecondary}>• {r}</Text>
                    ))}
                  </View>
                )}
                {item.watch_url && (
                  <Button
                    label="Watch draft"
                    onPress={() => Linking.openURL(item.watch_url!)}
                    variant="ghost"
                    style={{ height: 44 }}
                  />
                )}
                <View style={styles.actions}>
                  <Button
                    label="Send to re-edit"
                    onPress={() => {
                      setReeditNotes(blocked ? reasons.join('\n') : '');
                      setReeditTarget(item);
                    }}
                    variant="secondary"
                    style={{ flex: 1, height: 44 }}
                  />
                  <Button
                    label={blocked ? 'Approval blocked' : approving === item.id ? 'Approving...' : 'Approve'}
                    onPress={() => approve(item)}
                    disabled={approving !== null || blocked}
                    style={{ flex: 1, height: 44 }}
                  />
                </View>
              </Card>
            );
          }}
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
              Describe what to change. Your notes go straight to the editing AI.
            </Text>
            <TextInput
              style={styles.notesInput}
              value={reeditNotes}
              onChangeText={setReeditNotes}
              placeholder="Notes for the re-edit..."
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
                label={submitting ? 'Sending...' : 'Send for re-edit'}
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
  qaBlock: {
    borderWidth: 1,
    borderColor: Colors.danger,
    borderRadius: 8,
    padding: Spacing.sm,
    gap: Spacing.xs,
  },
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
