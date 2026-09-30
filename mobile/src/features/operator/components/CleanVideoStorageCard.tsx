import React, { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Colors, Radius, Spacing } from '@/shared/constants/theme';
import {
  CLEAN_SUCCESS_MESSAGE,
  fetchCleanPreview,
  runCleanVideoStorage,
} from '../lib/cleanVideoStorage';
import type { StorageCleanPreviewResponse, StorageCleanRun } from '../types/contracts';

type Phase =
  | { name: 'idle' }
  | { name: 'loading_preview' }
  | { name: 'confirm'; preview: StorageCleanPreviewResponse | null; previewError: string | null }
  | { name: 'running'; run: StorageCleanRun | null }
  | { name: 'success'; run: StorageCleanRun }
  | { name: 'failed'; run: StorageCleanRun }
  | { name: 'interrupted'; runId: string | null; error: string };

export function CleanVideoStorageCard() {
  const [phase, setPhase] = useState<Phase>({ name: 'idle' });
  const [understood, setUnderstood] = useState(false);
  const inFlight = useRef(false); // hard double-submit guard (state updates are async)

  const open = useCallback(async () => {
    setUnderstood(false);
    setPhase({ name: 'loading_preview' });
    try {
      setPhase({ name: 'confirm', preview: await fetchCleanPreview(), previewError: null });
    } catch (e) {
      setPhase({ name: 'confirm', preview: null, previewError: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const start = useCallback(async (resumeRunId?: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPhase({ name: 'running', run: null });
    try {
      const outcome = await runCleanVideoStorage((run) => setPhase({ name: 'running', run }), undefined, resumeRunId);
      if (outcome.kind === 'success') setPhase({ name: 'success', run: outcome.run });
      else if (outcome.kind === 'failed') setPhase({ name: 'failed', run: outcome.run });
      else setPhase({ name: 'interrupted', runId: outcome.runId, error: outcome.error });
    } finally {
      inFlight.current = false;
    }
  }, []);

  const close = () => { if (phase.name !== 'running') setPhase({ name: 'idle' }); };
  const modalVisible = phase.name !== 'idle';
  const inv = phase.name === 'confirm' ? phase.preview?.inventory : null;

  return (
    <Card bordered style={{ gap: Spacing.sm }}>
      <Text variant="title">Clean Video Storage / נקה חומר וידאו</Text>
      <Text variant="caption" color={Colors.textSecondary}>
        Start a new game/batch with a clean video environment. Removes the previous job's video files.
      </Text>
      <Button
        testID="clean-video-storage-open"
        label="Clean Video Storage / נקה חומר וידאו"
        variant="danger"
        onPress={open}
        disabled={phase.name === 'running' || phase.name === 'loading_preview'}
        style={{ height: 44 }}
      />

      <Modal visible={modalVisible} transparent animationType="fade" onRequestClose={close}>
        <View style={styles.backdrop}>
          <View style={styles.sheet} testID="clean-video-storage-modal">
            <ScrollView contentContainerStyle={{ gap: Spacing.sm }}>
              {phase.name === 'loading_preview' && <ActivityIndicator color={Colors.accent} />}

              {phase.name === 'confirm' && (
                <>
                  <Text variant="title">Clean video storage?</Text>
                  <Text variant="body">• The video files of the previous job will be deleted.</Text>
                  <Text variant="body">
                    • Users, profiles, athlete photos, auth/config and everything not related to the video material are NOT deleted.
                  </Text>
                  <Text variant="body" color={Colors.danger}>• This action is irreversible.</Text>
                  {inv && (
                    <Text testID="clean-video-storage-preview" variant="caption" color={Colors.textSecondary}>
                      {`Will remove: ${inv.r2_video_objects} video file(s), ${inv.r2_incomplete_multipart} incomplete upload(s), ${inv.supabase_reels_videos} reel file(s).`}
                    </Text>
                  )}
                  {phase.previewError && (
                    <Text variant="caption" color={Colors.danger}>Could not load inventory: {phase.previewError}</Text>
                  )}
                  {(phase.preview?.active_state.paid_reels ?? 0) > 0 && (
                    <Text variant="caption" color={Colors.danger}>
                      Warning: {phase.preview?.active_state.paid_reels} paid reel(s) exist; their files will be removed.
                    </Text>
                  )}
                  <Pressable
                    testID="clean-video-storage-understand"
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: understood }}
                    onPress={() => setUnderstood((v) => !v)}
                    style={styles.checkRow}
                  >
                    <View style={[styles.box, understood && styles.boxOn]} />
                    <Text variant="body">I understand the video files will be permanently deleted</Text>
                  </Pressable>
                  <Button
                    testID="clean-video-storage-confirm"
                    label="Delete video files"
                    variant="danger"
                    disabled={!understood}
                    onPress={() => start()}
                  />
                  <Button testID="clean-video-storage-cancel" label="Cancel" variant="secondary" onPress={close} />
                </>
              )}

              {phase.name === 'running' && (
                <>
                  <Text variant="title">Cleaning…</Text>
                  <ActivityIndicator color={Colors.accent} />
                  <Text testID="clean-video-storage-progress" variant="body">
                    {phase.run
                      ? `${phase.run.progress.deleted} of ${phase.run.progress.initial_total} removed (${phase.run.phase})`
                      : 'Starting…'}
                  </Text>
                  <Text variant="caption" color={Colors.textSecondary}>Please keep the app open.</Text>
                </>
              )}

              {phase.name === 'success' && (
                <>
                  <Text testID="clean-video-storage-success" variant="title" color={Colors.success}>
                    {CLEAN_SUCCESS_MESSAGE}
                  </Text>
                  <Text variant="caption" color={Colors.textSecondary}>
                    {`Removed ${phase.run.totals.r2_deleted} video file(s), ${phase.run.totals.multipart_aborted} incomplete upload(s), ${phase.run.totals.reels_removed} reel file(s).`}
                  </Text>
                  <Button testID="clean-video-storage-done" label="Done" onPress={close} />
                </>
              )}

              {phase.name === 'failed' && (
                <>
                  <Text testID="clean-video-storage-failed" variant="title" color={Colors.danger}>
                    Cleanup failed — storage is NOT confirmed clean
                  </Text>
                  <Text variant="body">{phase.run.error ?? 'Verification failed.'}</Text>
                  {phase.run.failures.map((f) => (
                    <Text key={f} variant="caption" color={Colors.danger}>• {f}</Text>
                  ))}
                  {phase.run.after && (
                    <Text variant="caption" color={Colors.textSecondary}>
                      {`Remaining: ${phase.run.after.r2_video_objects} video file(s), ${phase.run.after.r2_incomplete_multipart} incomplete upload(s), ${phase.run.after.supabase_reels_videos} reel file(s).`}
                    </Text>
                  )}
                  <Button testID="clean-video-storage-retry" label="Retry cleanup" variant="danger" onPress={() => start()} />
                  <Button testID="clean-video-storage-close" label="Close" variant="secondary" onPress={close} />
                </>
              )}

              {phase.name === 'interrupted' && (
                <>
                  <Text testID="clean-video-storage-interrupted" variant="title" color={Colors.danger}>
                    Cleanup interrupted — storage is NOT confirmed clean
                  </Text>
                  <Text variant="caption" color={Colors.textSecondary}>{phase.error}</Text>
                  <Button
                    testID="clean-video-storage-resume"
                    label="Retry cleanup"
                    variant="danger"
                    onPress={() => start(phase.runId ?? undefined)}
                  />
                  <Button testID="clean-video-storage-close" label="Close" variant="secondary" onPress={close} />
                </>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </Card>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: Colors.overlay, justifyContent: 'center', padding: Spacing.lg },
  sheet: {
    backgroundColor: Colors.card, borderRadius: Radius.lg, padding: Spacing.lg,
    borderWidth: 1, borderColor: Colors.cardBorder, maxHeight: '90%',
  },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, paddingVertical: Spacing.sm },
  box: { width: 22, height: 22, borderRadius: 4, borderWidth: 2, borderColor: Colors.accent },
  boxOn: { backgroundColor: Colors.accent },
});
