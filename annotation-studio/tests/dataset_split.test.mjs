// Leak-free dataset split (operator, 2026-11-06): the pipeline must never be evaluated on what it saw in training.
// With policy.group_by = 'athlete' every athlete (and anyone sharing a video with them) lands in ONE split, and
// policy.test_sessions holds whole recording days out as the test set.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import { freezeDataset, DEFAULT_POLICY } from '../server/datasets.mjs';

async function library(n) {
  const ctx = newCtx(), raw = path.join(tmp('split-'), 'raw');
  for (let i = 0; i < n; i++) makeVideo(path.join(raw, `v${String(i).padStart(2, '0')}.mp4`), { y: 20 + i * 5, tag: `v${i}`, seconds: 1 });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  return { ctx, db: ctx.db, srcs: ctx.db.prepare('select * from sources order by display_name').all() };
}
function catalog(db, src, session, owner, performers = [owner]) {
  db.prepare('update sources set session_key=?, owner_athlete_id=?, owner_status=? where id=?').run(session, owner, 'assigned', src.id);
  const c = A.emptyContent();
  performers.forEach((a, i) => c.segments.push(seg(`s${i}`, i * 10, i * 10 + 8, { athlete_id: a })));
  A.saveDraft(db, src.id, 0, c);
  A.approve(db, src.id, { expectedVersion: A.getDraft(db, src.id).version, acknowledgeUnresolved: true });
}

test('athlete split: no athlete in two splits, the held-out day is the test set, a shared video ties two athletes', async () => {
  const { db, srcs } = await library(12);
  const ath = Array.from({ length: 7 }, (_, i) => A.createAthlete(db, `ath${i}`).id);
  // day 1: athletes 0-4 (athlete 0 in 3 videos; video 5 has athletes 3 AND 4 together); day 2: athletes 5 and 6
  const plan = [[0], [0], [0], [1], [1], [3, 4], [3], [4], [2], [2], [5], [6]];
  plan.forEach((p, i) => catalog(db, srcs[i], i < 10 ? 'day1' : 'day2', ath[p[0]], p.map(k => ath[k])));
  const policy = { ...DEFAULT_POLICY, group_by: 'athlete', test_sessions: ['day2'] };
  const ds = freezeDataset(db, { name: 'leak-free', sourceIds: srcs.map(s => s.id), policy });
  const split = new Map(ds.manifest.members.map(m => [m.source_id, m.split]));
  // every athlete is in exactly one split
  const byAthlete = new Map();
  srcs.forEach((s, i) => { for (const a of plan[i].map(k => ath[k])) (byAthlete.get(a) ?? byAthlete.set(a, new Set()).get(a)).add(split.get(s.id)); });
  for (const [a, sp] of byAthlete) assert.equal(sp.size, 1, `athlete ${a} appears in ${[...sp].join('+')}`);
  // the held-out day is the test set, and only it (day 1 is train/validation)
  assert.equal(split.get(srcs[10].id), 'test'); assert.equal(split.get(srcs[11].id), 'test');
  assert.ok(srcs.slice(0, 10).every(s => split.get(s.id) !== 'test'), 'no day-1 video in test');
  assert.ok(srcs.slice(0, 10).some(s => split.get(s.id) === 'train') && srcs.slice(0, 10).some(s => split.get(s.id) === 'validation'), 'day 1 has both train and validation');
  // the shared video ties athletes 3 and 4 (videos 5, 6, 7) together
  assert.equal(new Set([5, 6, 7].map(i => split.get(srcs[i].id))).size, 1);
  // deterministic: freezing again gives the same split
  const again = freezeDataset(db, { name: 'leak-free-2', sourceIds: srcs.map(s => s.id), policy });
  assert.deepEqual(again.manifest.members.map(m => m.split), ds.manifest.members.map(m => m.split));
});

test('the default policy is unchanged (session groups, existing manifests reproduce)', async () => {
  const { db, srcs } = await library(2);
  const a = A.createAthlete(db, 'x').id;
  for (const s of srcs) catalog(db, s, 'same-day', a);
  const ds = freezeDataset(db, { name: 'default', sourceIds: srcs.map(s => s.id) });
  assert.ok(ds.manifest.members.every(m => !('group' in m) && !('athletes' in m) && !('session' in m)));
  assert.equal(new Set(ds.manifest.members.map(m => m.split)).size, 1, 'one session = one split');
});
