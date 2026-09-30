import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  isInScopeR2VideoKey, runCleanupStep, summarize, takeInventory, verifyClean,
  type ActiveStateCounts, type CleanupDatabase, type CleanupStorage,
} from '../src/lib/video-storage-cleanup';

const ZERO: ActiveStateCounts = {
  source_uploads_active: 0, upload_batches_active: 0, reprocess_requests_active: 0, reels_active: 0,
  live_pipeline_runs: 0, live_running_batches: 0, paid_reels: 0,
};

function fake(opts: { failDeleteOn?: string; failReels?: boolean; leakKey?: string } = {}) {
  const r2 = new Map<string, number>([
    ['raw/b1/a.mp4', 10], ['raw/b1/b.MOV', 20], ['processed/x.mp4', 5], ['review/d.mp4', 7],
    ['approved/e.mp4', 1], ['pending_payment/f.mp4', 1], ['pending_uploads/g.mp4', 1], ['previews/h.mp4', 1],
    ['previews/h.jpg', 1], ['raw/readme.txt', 1], ['metadata/processed.json', 1], ['metadata/keep.mp4', 1],
    ['assets/logo.mp4', 1], ['config/x.json', 1],
  ]);
  const multipart = [{ key: 'raw/b1/big.mp4', uploadId: 'U1' }];
  const reels = new Set(['a/1.mp4', 'a/2.mp4', 'thumb.jpg']);
  const photos = new Set(['p/1.jpg']);
  const deleted: string[] = [];
  const state = { neutralized: 0, counts: { ...ZERO, source_uploads_active: 3, reels_active: 2 } };
  const storage: CleanupStorage = {
    listR2All: async () => [...r2].map(([key, size]) => ({ key, name: key, size, created_at: '' })),
    listR2Multipart: async () => [...multipart],
    deleteR2Object: async (key) => {
      if (key === opts.failDeleteOn) throw new Error('boom');
      deleted.push(key);
      if (key !== opts.leakKey) r2.delete(key);
    },
    abortR2Multipart: async () => { multipart.length = 0; },
    listSupabaseFiles: async (bucket) => [...(bucket === 'reels' ? reels : photos)].map((path) => ({ path, size: 1 })),
    removeSupabaseFiles: async (_b, paths) => {
      if (opts.failReels) throw new Error('reels down');
      paths.forEach((p) => reels.delete(p));
    },
  };
  const db: CleanupDatabase = {
    activeCounts: async () => state.counts,
    neutralize: async () => { state.neutralized += 1; state.counts = { ...ZERO }; return { source_uploads_aborted: 3 }; },
  };
  return { storage, db, r2, reels, photos, deleted, state };
}

test('scope gate rejects protected, unknown-prefix, non-video and traversal keys', () => {
  for (const k of ['metadata/keep.mp4', 'assets/logo.mp4', 'raw/x.txt', 'previews/h.jpg', 'raw/../x.mp4', 'rawx/a.mp4', '../raw/a.mp4']) {
    assert.equal(isInScopeR2VideoKey(k), false, k);
  }
  for (const k of ['raw/b/a.MP4', 'processed/a.mov', 'review/a.mkv', 'previews/a.m4v']) assert.equal(isInScopeR2VideoKey(k), true, k);
});

test('populated -> clean deletes only in-scope videos and verifies', async () => {
  const f = fake();
  const before = summarize(await takeInventory(f.storage));
  assert.equal(before.r2_video_objects, 8);
  assert.equal(before.r2_unscoped_video_objects, 1);
  const r = await runCleanupStep({ storage: f.storage, db: f.db, runId: 'r', before });
  assert.equal(r.phase, 'succeeded');
  assert.equal(r.totals.r2_deleted, 8);
  assert.equal(r.totals.multipart_aborted, 1);
  assert.equal(r.totals.reels_removed, 2);
  assert.ok(f.r2.has('assets/logo.mp4') && f.r2.has('metadata/keep.mp4') && f.r2.has('raw/readme.txt') && f.r2.has('previews/h.jpg'));
  assert.ok(f.reels.has('thumb.jpg'));
  assert.equal(f.photos.size, 1);
  assert.equal(f.state.neutralized, 1);
  assert.ok(f.deleted.every(isInScopeR2VideoKey));
});

test('clean -> clean is idempotent with zero deleted', async () => {
  const f = fake();
  const before = summarize(await takeInventory(f.storage));
  await runCleanupStep({ storage: f.storage, db: f.db, runId: 'r', before });
  const r2 = await runCleanupStep({ storage: f.storage, db: f.db, runId: 'r2', before: summarize(await takeInventory(f.storage)) });
  assert.equal(r2.phase, 'succeeded');
  assert.deepEqual(r2.totals, { r2_deleted: 0, multipart_aborted: 0, reels_removed: 0 });
});

test('storage failure throws and is never reported as clean; retry succeeds', async () => {
  const f = fake({ failDeleteOn: 'processed/x.mp4' });
  const before = summarize(await takeInventory(f.storage));
  await assert.rejects(runCleanupStep({ storage: f.storage, db: f.db, runId: 'r', before }), /boom/);
  assert.equal(f.state.neutralized, 0);
  const ok = fake();
  const b2 = summarize(await takeInventory(ok.storage));
  assert.equal((await runCleanupStep({ storage: ok.storage, db: ok.db, runId: 'r', before: b2 })).phase, 'succeeded');
});

test('supabase reels failure is a failure', async () => {
  const f = fake({ failReels: true });
  const before = summarize(await takeInventory(f.storage));
  await assert.rejects(runCleanupStep({ storage: f.storage, db: f.db, runId: 'r', before }), /reels down/);
});

test('verification failure (object survives delete) is phase failed, not success', async () => {
  const f = fake({ leakKey: 'review/d.mp4' });
  const before = summarize(await takeInventory(f.storage));
  const r = await runCleanupStep({ storage: f.storage, db: f.db, runId: 'r', before });
  assert.equal(r.phase, 'failed');
  assert.match(r.verification!.failures.join(), /R2 video object/);
});

test('DB neutralize failure propagates (storage clean but DB not => not clean)', async () => {
  const f = fake();
  f.db.neutralize = async () => { throw new Error('pipeline_active'); };
  const before = summarize(await takeInventory(f.storage));
  await assert.rejects(runCleanupStep({ storage: f.storage, db: f.db, runId: 'r', before }), /pipeline_active/);
});

test('verifyClean fails when active DB references remain or protected data is lost', async () => {
  const f = fake();
  const before = summarize(await takeInventory(f.storage));
  const v = await verifyClean(f.storage, f.db, before);
  assert.equal(v.ok, false);
  const lossy = { ...before, protected_bucket_counts: { athlete_photos: 5 } };
  const v2 = await verifyClean(f.storage, { activeCounts: async () => ZERO, neutralize: f.db.neutralize }, lossy);
  assert.ok(v2.failures.some((m) => /athlete_photos/.test(m)));
});

test('time budget yields a resumable partial step', async () => {
  const f = fake();
  const before = summarize(await takeInventory(f.storage));
  let t = 0;
  const r = await runCleanupStep({ storage: f.storage, db: f.db, runId: 'r', before, budgetMs: 0, now: () => t++ });
  assert.equal(r.done, false);
  assert.equal(f.state.neutralized, 0);
});
