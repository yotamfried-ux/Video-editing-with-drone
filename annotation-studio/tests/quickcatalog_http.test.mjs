// Quick catalog over the real HTTP API: the queue reports every catalog field per video and per event, writes go through
// the same stores as the workbench (owner OCC, sport, draft OCC), and "no events" is an explicit, checked statement.
// Negative cases assert the specific error code, not just "it failed".
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg, kf } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import { createApp } from '../server/app.mjs';

async function boot() {
  const ctx = newCtx();
  const raw = path.join(tmp('qc-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'), { tag: 'a' }); makeVideo(path.join(raw, 'b.mp4'), { tag: 'b', y: 20 });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = async (p, body, method = body ? 'POST' : 'GET') => {
    const r = await fetch(base + p, { method, body: body ? JSON.stringify(body) : undefined, headers: { authorization: 'Bearer test-token', 'content-type': 'application/json' } });
    return { status: r.status, json: await r.json() };
  };
  const ids = ctx.db.prepare('select id from sources order by display_name').all().map(r => r.id);
  return { ctx, call, ids, base, close: () => { server.closeAllConnections(); server.close(); } };
}
const item = (q, id) => q.items.find(i => i.source_id === id);
const check = (list, key) => list.find(i => i.key === key);

test('queue: a fresh video lists owner, sport and "are there events" as missing; nothing is complete', async () => {
  const b = await boot();
  try {
    const q = (await b.call('/api/catalog/queue')).json;
    assert.equal(q.totals.all, 2); assert.equal(q.totals.complete, 0);
    const a = item(q, b.ids[0]);
    assert.deepEqual(a.video.map(i => [i.key, i.ok]), [['owner', false], ['sport', false], ['triage', false]]);
    assert.equal(a.triage, 'not_started'); assert.equal(a.complete, false);
  } finally { b.close(); }
});

test('"no events": needs the watched-all statement, marks the full video reviewed, completes the video with owner+sport', async () => {
  const b = await boot();
  try {
    const id = b.ids[0];
    const ath = (await b.call('/api/athletes', { label: 'גולש א' })).json;
    assert.equal((await b.call(`/api/sources/${id}/catalog-owner`, { owner_athlete_id: ath.id, expected_version: 0 })).status, 200);
    assert.equal((await b.call(`/api/sources/${id}/sport`, { sport_id: 'surfing', reason: 'catalog' }, 'PATCH')).status, 200);
    const refused = await b.call(`/api/catalog/sources/${id}/triage`, { result: 'no_events', expected_version: 0 });
    assert.equal(refused.status, 400); assert.equal(refused.json.code, 'INVALID_INPUT'); assert.match(refused.json.detail, /צפית בכל הסרטון/);
    const stale = await b.call(`/api/catalog/sources/${id}/triage`, { result: 'no_events', expected_version: 7, watched_all: true });
    assert.equal(stale.status, 409); assert.equal(stale.json.code, 'VERSION_CONFLICT');
    assert.equal((await b.call(`/api/catalog/sources/${id}/triage`, { result: 'no_events', expected_version: 0, watched_all: true })).status, 200);
    const st = (await b.call(`/api/catalog/sources/${id}`)).json;
    assert.equal(st.triage, 'no_events'); assert.equal(st.complete, true, JSON.stringify(st.video));
    const d = (await b.call(`/api/sources/${id}/draft`)).json;
    const fc = b.ctx.db.prepare('select frame_count from sources where id=?').get(id).frame_count;
    assert.deepEqual(d.content.reviewed_ranges, [{ start_frame: 0, end_frame: fc }]);
    assert.equal((await b.call('/api/catalog/queue')).json.totals.complete, 1);
  } finally { b.close(); }
});

test('"no events" is refused with CATALOG_HAS_EVENTS while events exist; "unsure" raises the review request', async () => {
  const b = await boot();
  try {
    const id = b.ids[1];
    const put = await b.call(`/api/sources/${id}/draft`, { expected_version: 0, content: { schema: 1, segments: [seg('s1', 10, 40, { decision: 'uncertain', usability: 'uncertain' })], keyframes: [], reviewed_ranges: [], box_verifications: [] } }, 'PUT');
    assert.equal(put.status, 200, JSON.stringify(put.json));
    const r = await b.call(`/api/catalog/sources/${id}/triage`, { result: 'no_events', expected_version: 1, watched_all: true });
    assert.equal(r.status, 409); assert.equal(r.json.code, 'CATALOG_HAS_EVENTS');
    const st = (await b.call(`/api/catalog/sources/${id}`)).json;
    assert.equal(st.triage, 'has_events');
    const ev = st.events[0];
    assert.deepEqual(ev.checklist.filter(i => i.required && !i.ok).map(i => i.key).sort(), ['decision', 'performer', 'usability']);
    assert.equal(check(ev.checklist, 'box').state, 'none'); assert.equal(check(ev.checklist, 'box').required, false, 'BOX stays optional');
    assert.equal(check(st.video, 'watched').ok, false, 'events present: the whole video must still be watched');
    const u = await b.call(`/api/catalog/sources/${id}/triage`, { result: 'unsure', expected_version: 1 });
    assert.equal(u.status, 200);
    assert.equal((await b.call(`/api/sources/${id}/states`)).json.operator_requested_review, true);
  } finally { b.close(); }
});

test('an event is complete only when every field is decided; a drawn but unchecked BOX keeps it incomplete', async () => {
  const b = await boot();
  try {
    const id = b.ids[0];
    const ath = (await b.call('/api/athletes', { label: 'גולש ב' })).json;
    const s = seg('s1', 10, 40, { athlete_id: ath.id, decision: 'exclude', usability: 'unusable', reason_codes: [] });
    let v = (await b.call(`/api/sources/${id}/draft`, { expected_version: 0, content: { schema: 1, segments: [s], keyframes: [], reviewed_ranges: [], box_verifications: [] } }, 'PUT')).json.version;
    let ev = (await b.call(`/api/catalog/sources/${id}`)).json.events[0];
    assert.equal(check(ev.checklist, 'reasons').ok, false, 'unusable/excluded needs a reason code');
    s.reason_codes = ['missed_wave'];
    const k = kf('k1', 's1', 12, { x: 0.1, y: 0.1, w: 0.2, h: 0.3 });
    v = (await b.call(`/api/sources/${id}/draft`, { expected_version: v, content: { schema: 1, segments: [s], keyframes: [k], reviewed_ranges: [], box_verifications: [] } }, 'PUT')).json.version;
    ev = (await b.call(`/api/catalog/sources/${id}`)).json.events[0];
    assert.equal(check(ev.checklist, 'reasons').ok, true);
    const box = check(ev.checklist, 'box');
    assert.equal(box.required, true); assert.equal(box.ok, false); assert.equal(box.state, 'not_checked');
    assert.equal(ev.complete, false);
  } finally { b.close(); }
});

test('fixed address: logging in with the token sets a persistent cookie; /api/version reports the running code', async () => {
  const b = await boot();
  try {
    const port = new URL(b.base).port;
    const r = await fetch(`${b.base}/?t=test-token`, { redirect: 'manual' });
    assert.equal(r.status, 302);
    const c = r.headers.get('set-cookie');
    assert.match(c, /studio_token=/); assert.match(c, /Max-Age=31536000/); assert.match(c, /HttpOnly/); assert.match(c, /SameSite=Strict/);
    const wrong = await fetch(`${b.base}/?t=not-the-token`, { redirect: 'manual' });
    assert.notEqual(wrong.status, 302, 'a wrong token never logs in');
    const v = await b.call('/api/version');
    assert.equal(v.status, 200); assert.ok('commit' in v.json && 'version' in v.json);
    assert.ok(port);
  } finally { b.close(); }
});
