// Catalog ownership over the real HTTP API (spec §21.1, §22.3 CATALOG_GO): OCC under genuinely concurrent requests,
// bulk conflicts with atomic rollback, explicit reassignment confirmation, malformed versions, restart persistence,
// and the Surfer Workspace listing videos with zero events.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, BACKEND } from './helpers.mjs';
import { createContext } from '../server/context.mjs';
import { reconcile } from '../server/ingest.mjs';
import { createApp } from '../server/app.mjs';

async function boot(ctx0) {
  const ctx = ctx0 ?? newCtx();
  if (!ctx0) {
    const raw = path.join(tmp('ops-'), 'raw');
    makeVideo(path.join(raw, 'a.mp4'), { tag: 'a' }); makeVideo(path.join(raw, 'b.mp4'), { tag: 'b', y: 20 }); makeVideo(path.join(raw, 'c.mp4'), { tag: 'c', y: 120 });
    await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  }
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = async (p, body, method = body ? 'POST' : 'GET') => {
    const r = await fetch(base + p, { method, body: body ? JSON.stringify(body) : undefined, headers: { authorization: 'Bearer test-token', 'content-type': 'application/json' } });
    return { status: r.status, json: await r.json() };
  };
  const ids = ctx.db.prepare('select id from sources order by display_name').all().map(r => r.id);
  return { ctx, call, ids, close: () => { server.closeAllConnections(); server.close(); } };
}
const owner = (b, id, body) => b.call(`/api/sources/${id}/catalog-owner`, body);
const historyCount = (db, id) => db.prepare('select count(*) c from source_owner_history where source_id=?').get(id).c;

test('two parallel assignments with the same expected_version: exactly one wins, the other gets 409, history has one row', async () => {
  const b = await boot();
  try {
    const A = (await b.call('/api/athletes', { label: 'A' })).json, B = (await b.call('/api/athletes', { label: 'B' })).json;
    const [r1, r2] = await Promise.all([
      owner(b, b.ids[0], { owner_athlete_id: A.id, expected_version: 0 }),
      owner(b, b.ids[0], { owner_athlete_id: B.id, expected_version: 0 }),
    ]);
    const statuses = [r1.status, r2.status].sort();
    assert.deepEqual(statuses, [200, 409]);
    const loser = r1.status === 409 ? r1 : r2, winner = r1.status === 200 ? r1 : r2;
    assert.equal(loser.json.code, 'VERSION_CONFLICT');
    assert.match(loser.json.message, /עודכנ/);
    const cur = (await owner(b, b.ids[0])).json;
    assert.equal(cur.owner_athlete_id, winner.json.owner_athlete_id);
    assert.equal(cur.owner_version, 1);
    assert.equal(historyCount(b.ctx.db, b.ids[0]), 1);
  } finally { b.close(); }
});

test('malformed or missing expected_version is rejected with 400 and changes nothing', async () => {
  const b = await boot();
  try {
    const A = (await b.call('/api/athletes', { label: 'A' })).json;
    for (const v of [undefined, null, '0', -1, 1.5, 'abc', {}, []]) {
      const r = await owner(b, b.ids[0], { owner_athlete_id: A.id, ...(v === undefined ? {} : { expected_version: v }) });
      assert.equal(r.status, 400, JSON.stringify(v)); assert.equal(r.json.code, 'INVALID_INPUT');
    }
    assert.equal((await owner(b, b.ids[0])).json.owner_version, 0);
    assert.equal(historyCount(b.ctx.db, b.ids[0]), 0);
    // Unknown surfer / unknown video
    assert.equal((await owner(b, b.ids[0], { owner_athlete_id: 'nope', expected_version: 0 })).status, 404);
    assert.equal((await owner(b, 'nope', { owner_athlete_id: A.id, expected_version: 0 })).status, 404);
  } finally { b.close(); }
});

test('reassigning an owned video requires explicit confirmation; confirmed change is audited with reason', async () => {
  const b = await boot();
  try {
    const A = (await b.call('/api/athletes', { label: 'A' })).json, B = (await b.call('/api/athletes', { label: 'B' })).json;
    assert.equal((await owner(b, b.ids[0], { owner_athlete_id: A.id, expected_version: 0 })).status, 200);
    let r = await owner(b, b.ids[0], { owner_athlete_id: B.id, expected_version: 1 });
    assert.equal(r.status, 409); assert.equal(r.json.code, 'REASSIGN_CONFIRMATION_REQUIRED');
    r = await owner(b, b.ids[0], { owner_athlete_id: null, expected_version: 1 });
    assert.equal(r.status, 409, 'removing an owner is also a change that needs confirmation');
    r = await owner(b, b.ids[0], { owner_athlete_id: B.id, expected_version: 1, confirm_reassign: true, reason: 'wrong surfer' });
    assert.equal(r.status, 200); assert.equal(r.json.owner_version, 2);
    const h = b.ctx.db.prepare('select * from source_owner_history where source_id=? order by id').all(b.ids[0]);
    assert.deepEqual(h.map(x => [x.old_owner_id, x.new_owner_id, x.version]), [[null, A.id, 1], [A.id, B.id, 2]]);
    assert.equal(h[1].reason, 'wrong surfer');
    // Undo = compensating action (history is never rewritten)
    r = await owner(b, b.ids[0], { owner_athlete_id: A.id, expected_version: 2, confirm_reassign: true, reason: 'undo' });
    assert.equal(r.status, 200); assert.equal(historyCount(b.ctx.db, b.ids[0]), 3);
  } finally { b.close(); }
});

test('bulk: preview, stale version -> 409 with full rollback; conflicts need confirm_overwrite; success is atomic', async () => {
  const b = await boot();
  try {
    const A = (await b.call('/api/athletes', { label: 'A' })).json, B = (await b.call('/api/athletes', { label: 'B' })).json;
    await owner(b, b.ids[2], { owner_athlete_id: B.id, expected_version: 0 });
    const prev = (await b.call('/api/sources/catalog-owners/bulk', { source_ids: b.ids, owner_athlete_id: A.id, preview: true })).json;
    assert.equal(prev.conflicts_count, 1);
    const exp = Object.fromEntries(prev.items.map(i => [i.source_id, i.owner_version]));
    // Missing versions
    let r = await b.call('/api/sources/catalog-owners/bulk', { source_ids: b.ids, owner_athlete_id: A.id });
    assert.equal(r.status, 400);
    // Someone changes video 1 after the preview -> whole batch refused, nothing changed.
    await owner(b, b.ids[1], { owner_athlete_id: B.id, expected_version: 0 });
    const before = b.ids.map(id => historyCount(b.ctx.db, id));
    r = await b.call('/api/sources/catalog-owners/bulk', { source_ids: b.ids, owner_athlete_id: A.id, expected_versions: exp, confirm_overwrite: true });
    assert.equal(r.status, 409); assert.equal(r.json.code, 'VERSION_CONFLICT');
    assert.deepEqual(b.ids.map(id => historyCount(b.ctx.db, id)), before);
    assert.equal((await owner(b, b.ids[0])).json.owner_athlete_id, null);
    // Fresh preview, but overwriting existing owners without confirmation is refused.
    const prev2 = (await b.call('/api/sources/catalog-owners/bulk', { source_ids: b.ids, owner_athlete_id: A.id, preview: true })).json;
    const exp2 = Object.fromEntries(prev2.items.map(i => [i.source_id, i.owner_version]));
    r = await b.call('/api/sources/catalog-owners/bulk', { source_ids: b.ids, owner_athlete_id: A.id, expected_versions: exp2 });
    assert.equal(r.status, 409); assert.equal(r.json.code, 'REASSIGN_CONFIRMATION_REQUIRED'); assert.equal(r.json.conflicts.length, 2);
    r = await b.call('/api/sources/catalog-owners/bulk', { source_ids: b.ids, owner_athlete_id: A.id, expected_versions: exp2, confirm_overwrite: true, reason: 'heat 2' });
    assert.equal(r.status, 200);
    for (const id of b.ids) assert.equal((await owner(b, id)).json.owner_athlete_id, A.id);
  } finally { b.close(); }
});

test('assignment without events appears in the Surfer Workspace immediately and survives a restart; no draft/event is created', { skip: BACKEND === 'postgres' ? 'restart is covered by the PG suite with a fresh connection' : false }, async () => {
  const b = await boot();
  const home = b.ctx.home;
  let A;
  try {
    A = (await b.call('/api/athletes', { label: 'Owner' })).json;
    assert.equal((await owner(b, b.ids[0], { owner_athlete_id: A.id, expected_version: 0 })).status, 200);
    const ws = (await b.call(`/api/athletes/${A.id}/sources`)).json;
    const items = ws.items ?? ws.sources ?? ws;
    assert.ok(JSON.stringify(items).includes(b.ids[0]), 'video listed in workspace');
    assert.equal(b.ctx.db.prepare('select count(*) c from annotation_drafts').get().c, 0, 'no draft/event was created');
  } finally { b.close(); b.ctx.db.close?.(); }
  // Restart: a fresh process context on the same home.
  const ctx2 = createContext(home, { token: 'test-token' });
  const b2 = await boot(ctx2);
  try {
    const cur = (await owner(b2, b2.ids[0])).json;
    assert.equal(cur.owner_athlete_id, A.id); assert.equal(cur.owner_version, 1);
    assert.equal(ctx2.db.prepare('select count(*) c from annotation_drafts').get().c, 0);
    const ws = (await b2.call(`/api/athletes/${A.id}/sources`)).json;
    assert.ok(JSON.stringify(ws).includes(b2.ids[0]));
    // Ownership does not leak into the event performer or the source identity.
    const src = ctx2.db.prepare('select sha256 from sources where id=?').get(b2.ids[0]);
    assert.equal(src.sha256.length, 64);
  } finally { b2.close(); }
});

test('three independent roles over HTTP: owner A, performer B, visible-only C — none propagates to another', async () => {
  const b = await boot();
  try {
    const [A, B, C] = await Promise.all(['A', 'B', 'C'].map(async l => (await b.call('/api/athletes', { label: l })).json));
    assert.equal((await owner(b, b.ids[0], { owner_athlete_id: A.id, expected_version: 0 })).status, 200);
    const vis = await b.call(`/api/sources/${b.ids[0]}/appearances`, { athlete_id: C.id, uncertain: true });
    assert.equal(vis.status, 201); assert.equal(vis.json.uncertain, 1);
    const content = { schema: 1, segments: [{ id: 's1', start_frame: 0, end_frame: 30, athlete_id: B.id, event_type: 'wave_ride', decision: 'include', usability: 'usable' }], keyframes: [], reviewed_ranges: [], box_verifications: [] };
    assert.equal((await b.call(`/api/sources/${b.ids[0]}/draft`, { expected_version: 0, content }, 'PUT')).status, 200);
    const apps = (await b.call(`/api/sources/${b.ids[0]}/appearances`)).json.items;
    assert.deepEqual(apps.map(a => a.athlete_id).sort(), [B.id, C.id].sort(), 'performer recorded as visible; C visible without an event; owner A not implied');
    const own = (await owner(b, b.ids[0])).json; assert.equal(own.owner_athlete_id, A.id, 'owner unchanged by performer/appearance');
    const d = (await b.call(`/api/sources/${b.ids[0]}/draft`)).json; assert.equal(d.content.segments[0].athlete_id, B.id, 'performer unchanged by owner');
    assert.equal((await b.call(`/api/sources/${b.ids[0]}/appearances`, { athlete_id: 'nope' })).status, 404);
  } finally { b.close(); }
});

test('review#4: assigning through a cloud row cannot silently replace the linked source owner', async () => {
  const b = await boot();
  try {
    const Catalog = await import('../server/catalog_owner.mjs');
    const [O1, O2] = await Promise.all(['O1', 'O2'].map(async l => (await b.call('/api/athletes', { label: l })).json));
    await owner(b, b.ids[0], { owner_athlete_id: O1.id, expected_version: 0 });
    b.ctx.db.prepare("insert into cloud_objects(id,key,prefix,size,pipeline_state,available,source_id,seen_at) values('co1','raw/x.mp4','raw/',1,'new',1,?,?)").run(b.ids[0], new Date().toISOString());
    assert.throws(() => Catalog.setCloudObjectCatalogOwner(b.ctx.db, 'co1', { owner_athlete_id: O2.id, expected_version: 0 }), e => e.code === 'REASSIGN_CONFIRMATION_REQUIRED');
    assert.equal((await owner(b, b.ids[0])).json.owner_athlete_id, O1.id);
    Catalog.setCloudObjectCatalogOwner(b.ctx.db, 'co1', { owner_athlete_id: O2.id, expected_version: 0, confirm_reassign: true });
    assert.equal((await owner(b, b.ids[0])).json.owner_athlete_id, O2.id);
  } finally { b.close(); }
});
