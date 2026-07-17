import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Linking,
  Modal,
  RefreshControl,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import type {
  ApproveDraftResponse,
  DraftRow,
  DraftsResponse,
  ReprocessSubmitResponse,
} from '@/features/operator/types/contracts';
import { Colors, Spacing } from '@/shared/constants/theme';

function formatSize(bytes: number | null): string {
  if (!bytes) return '';
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

function shortId(id?: string | null): string {
  return id ? id.slice(0, 8) : 'unknown';
}

function draftIsApprovalBlocked(draft: DraftRow): boolean {
  return Boolean(
    draft.approval_blocked
      || draft.review_required
      || draft.reedit_task
      || draft.name.toUpperCase().includes('QA-FLAGGED'),
  );
}

function approvalReasons(draft: DraftRow): string[] {
  const taskReasons = Array.isArray(draft.reedit_task?.approval_blocked_reasons)
    ? draft.reedit_task.approval_blocked_reasons.filter(Boolean)
    : [];
  const reasons = Array.isArray(draft.approval_blocked_reasons)
    ? draft.approval_blocked_reasons.filter(Boolean)
    : [];
  if (taskReasons.length) return taskReasons;
  if (!reasons.length && draft.name.toUpperCase().includes('QA-FLAGGED')) {
    return ['Final QA did not pass. Re-edit or manual review is required before approval.'];
  }
  return reasons;
}

function reeditNotesForDraft(draft: DraftRow): string {
  const taskNotes = draft.reedit_task?.notes?.trim();
  if (taskNotes) return taskNotes;
  return approvalReasons(draft).join('\n');
}

function reeditAttemptLabel(draft: DraftRow): string | null {
  const task = draft.reedit_task;
  if (!task) return null;
  const attempts = Number(task.attempt_count ?? 0);
  const max = Number(task.max_attempts ?? 3);
  return `Re-edit ${task.status} · attempt ${attempts}/${max}`;
}

function readableDraftLabel(name: string): { athlete: string; reel: string } {
  const withoutPrefix = name.replace(/^DRAFT_/i, '').replace(/\.mp4$/i, '');
  const withoutDate = withoutPrefix.replace(/_\d{8}$/i, '');
  const partMatch = withoutDate.match(/\s*\(part\s+(\d+)\)\s*$/i);
  const part = partMatch?.[1];
  const athlete = withoutDate
    .replace(/\s*\(part\s+\d+\)\s*$/i, '')
    .replace(/\s*\(music\)\s*$/i, '')
    .replace(/\s*QA-FLAGGED\s*$/i, '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return {
    athlete: athlete || 'Athlete',
    reel: part ? `Performance reel · Part ${part}` : 'Performance reel',
  };
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
    `The reel moved to APPROVED, but no delivery workflow was started. Delivery run: ${shortId(result.delivery_run_id)}.`,
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

  const handleOperatorError = (error: unknown) => {
    const message = error instanceof Error ? error.message : 'Unknown error';
    if (message.includes('secret not set')) {
      Alert.alert('Operator secret required', message, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Go to Settings', onPress: () => router.push('/(operator)/settings' as never) },
      ]);
      return;
    }
    Alert.alert('Failed', message);
  };

  const load = useCallback(async () => {
    try {
      const { drafts: data } = await operatorFetch<DraftsResponse>('/api/operator/drafts');
      setDrafts(data ?? []);
      setLoadError(null);
    } catch (error) {
      setDrafts([]);
      setLoadError(error instanceof Error ? error.message : 'Failed to load drafts');
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

  const openReedit = (draft: DraftRow) => {
    setReeditNotes(reeditNotesForDraft(draft));
    setReeditTarget(draft);
  };

  const approve = (draft: DraftRow) => {
    if (draftIsApprovalBlocked(draft)) {
      Alert.alert(
        'Approval blocked',
        `${draft.name} did not pass final QA. Send it to re-edit before approval.\n\n${approvalReasons(draft).join('\n')}`,
      );
      return;
    }
    Alert.alert(
      'Approve this performance reel?',
      'The reel will move to APPROVED and the delivery workflow will start.',
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
              setDrafts((current) => current.filter((item) => item.id !== draft.id));
              showApprovalResult(result);
            } catch (error) {
              handleOperatorError(error);
            } finally {
              setApproving(null);
            }
          },
        },
      ],
    );
  };

  const submitReedit = async () => {
    if (!reeditTarget) return;
    setSubmitting(true);
    try {
      const result = await operatorFetch<ReprocessSubmitResponse>('/api/operator/reprocess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reprocess_request_id: reeditTarget.reedit_task?.id,
          draft_name: reeditTarget.name,
          notes: reeditNotes.trim(),
        }),
      });
      setReeditTarget(null);
      setReeditNotes('');
      await load();
      Alert.alert(
        'Sent for re-edit',
        `Pipeline run: ${shortId(result.pipeline_run_id)}. Check Pipeline status for progress.`,
      );
    } catch (error) {
      handleOperatorError(error);
    } finally {
      setSubmitting(false);
    }
  };

  const blockedCount = drafts.filter(draftIsApprovalBlocked).length;

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <FlatList
          data={drafts}
          keyExtractor={(draft) => draft.id}
          refreshControl={(
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={Colors.accent}
            />
          )}
          ListHeaderComponent={(
            <View style={styles.header}>
              <Text variant="display">Review</Text>
              <Text variant="caption" color={Colors.textSecondary}>
                Performance reels waiting for review · pull to refresh
              </Text>
              {blockedCount > 0 && (
                <Card bordered style={styles.operatorAlert}>
                  <Text variant="title">
                    {blockedCount} reel{blockedCount === 1 ? '' : 's'} did not pass final QA
                  </Text>
                  <Text variant="caption" color={Colors.textSecondary}>
                    Approval is blocked until the reel is regenerated and passes QA.
                  </Text>
                </Card>
              )}
            </View>
          )}
          ListEmptyComponent={(
            !loaded ? (
              <ActivityIndicator color={Colors.accent} style={styles.loading} />
            ) : loadError ? (
              <Card bordered style={styles.errorCard}>
                <Text variant="title">Could not load drafts</Text>
                <Text variant="caption" color={Colors.textSecondary}>{loadError}</Text>
              </Card>
            ) : (
              <Text variant="body" color={Colors.textSecondary}>
                No performance reels are waiting for review.
              </Text>
            )
          )}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          renderItem={({ item }) => {
            const blocked = draftIsApprovalBlocked(item);
            const reasons = approvalReasons(item);
            const attemptLabel = reeditAttemptLabel(item);
            const label = readableDraftLabel(item.name);
            return (
              <Card bordered style={[styles.draftCard, blocked && styles.blockedCard]}>
                <Text variant="title" numberOfLines={2}>{label.athlete}</Text>
                <Text variant="body" color={Colors.accent}>{label.reel}</Text>
                <Text variant="caption" color={Colors.textSecondary}>
                  {new Date(item.created_at).toLocaleString()}
                  {item.size ? ` · ${formatSize(item.size)}` : ''}
                </Text>

                <View style={[styles.statusBox, blocked ? styles.statusBlocked : styles.statusReady]}>
                  <Text variant="title">{blocked ? 'QA failed · re-edit required' : 'QA passed · ready to review'}</Text>
                  {attemptLabel && (
                    <Text variant="caption" color={Colors.textSecondary}>{attemptLabel}</Text>
                  )}
                  {blocked && reasons.slice(0, 3).map((reason) => (
                    <Text key={reason} variant="caption" color={Colors.textSecondary}>• {reason}</Text>
                  ))}
                </View>

                {item.watch_url && (
                  <Button
                    label="Watch performance reel"
                    onPress={() => Linking.openURL(item.watch_url!)}
                    variant="ghost"
                    style={styles.fullButton}
                  />
                )}
                <View style={styles.actions}>
                  <Button
                    label={blocked ? 'Send QA notes to re-edit' : 'Send to re-edit'}
                    onPress={() => openReedit(item)}
                    variant={blocked ? 'primary' : 'secondary'}
                    style={styles.fullButton}
                  />
                  <Button
                    label={blocked ? 'Approval blocked' : approving === item.id ? 'Approving…' : 'Approve reel'}
                    onPress={() => approve(item)}
                    disabled={approving !== null || blocked}
                    style={styles.fullButton}
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
            <Text variant="title">Send performance reel to re-edit</Text>
            <Text variant="caption" color={Colors.textSecondary} numberOfLines={2}>
              {reeditTarget ? readableDraftLabel(reeditTarget.name).athlete : ''}
            </Text>
            <Text variant="body" color={Colors.textSecondary}>
              QA notes are prefilled when the reel is blocked. Add only instructions that are useful for the next edit.
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
                style={styles.fullButton}
              />
              <Button
                label={submitting ? 'Sending…' : 'Send for re-edit'}
                onPress={submitReedit}
                disabled={submitting || !reeditNotes.trim()}
                variant="secondary"
                style={styles.fullButton}
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
  header: { marginBottom: Spacing.md, gap: Spacing.sm },
  loading: { marginTop: Spacing.xl },
  separator: { height: Spacing.sm },
  draftCard: { gap: Spacing.sm },
  blockedCard: { borderColor: Colors.danger },
  actions: { gap: Spacing.sm },
  fullButton: { width: '100%', minHeight: 48 },
  operatorAlert: { borderColor: Colors.danger, gap: Spacing.xs },
  errorCard: { gap: Spacing.sm, borderColor: Colors.danger },
  statusBox: {
    borderWidth: 1,
    borderRadius: 8,
    padding: Spacing.sm,
    gap: Spacing.xs,
  },
  statusBlocked: { borderColor: Colors.danger },
  statusReady: { borderColor: Colors.cardBorder },
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
