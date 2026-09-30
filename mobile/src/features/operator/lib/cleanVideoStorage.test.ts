jest.mock('./operatorApi', () => ({ operatorFetch: jest.fn() }));
import { CLEAN_CONFIRMATION, isVerifiedClean, runCleanVideoStorage } from './cleanVideoStorage';
import type { StorageCleanRun } from '../types/contracts';

const inv = { r2_video_objects: 0, r2_video_bytes: 0, r2_video_by_prefix: {}, r2_non_video_objects: 3,
  r2_unscoped_video_objects: 0, r2_incomplete_multipart: 0, supabase_reels_videos: 0,
  supabase_reels_non_video: 0, protected_bucket_counts: {}, total_removable: 0 };
const run = (o: Partial<StorageCleanRun>): StorageCleanRun => ({
  run_id: 'r1', status: 'running', phase: 'deleting', progress: { initial_total: 4, deleted: 2, remaining: 2 },
  totals: { r2_deleted: 2, multipart_aborted: 0, reels_removed: 0 }, before: inv, after: null,
  active_state_before: null, active_state_after: null, neutralized: null, failures: [], error: null, message: '', ...o,
});

test('starts once with the explicit confirmation, then continues the same run to verified success', async () => {
  const post = jest.fn()
    .mockResolvedValueOnce(run({}))
    .mockResolvedValueOnce(run({ status: 'succeeded', after: inv }));
  const seen: string[] = [];
  const out = await runCleanVideoStorage((r) => seen.push(r.status), post);
  expect(out.kind).toBe('success');
  expect(post.mock.calls[0][0]).toEqual({ confirmation: CLEAN_CONFIRMATION });
  expect(post.mock.calls[1][0]).toEqual({ run_id: 'r1' });
  expect(seen).toEqual(['running', 'succeeded']);
});

test('server failure is never success', async () => {
  const post = jest.fn().mockResolvedValueOnce(run({ status: 'failed', failures: ['1 R2 video object(s) remain'], error: 'x' }));
  expect((await runCleanVideoStorage(() => undefined, post)).kind).toBe('failed');
});

test('succeeded without verification evidence is downgraded to failed', async () => {
  const post = jest.fn().mockResolvedValueOnce(run({ status: 'succeeded', after: null }));
  expect((await runCleanVideoStorage(() => undefined, post)).kind).toBe('failed');
  expect(isVerifiedClean(run({ status: 'succeeded', after: { ...inv, supabase_reels_videos: 1, total_removable: 1 } }))).toBe(false);
});

test('network error mid-run is interrupted (resumable), not success', async () => {
  const post = jest.fn().mockResolvedValueOnce(run({})).mockRejectedValueOnce(new Error('offline'));
  const out = await runCleanVideoStorage(() => undefined, post);
  expect(out).toEqual({ kind: 'interrupted', runId: 'r1', error: 'offline' });
});
