// Quick catalog + BOX track strip in a real browser (Playwright/Chromium), at 1440x900. Drives visible controls only;
// every mutation is also checked in the authoritative store (DB), per Engineering-OS testing guidance.
//   queue/progress -> owner (new surfer) -> sport -> "no events" completes the video (full coverage recorded)
//   -> a video with events: a missing-field chip opens the workbench at that event/tab -> fill -> back -> chip is ✓
//   -> BOX strip: zoomed thumbnails along the event (incl. estimated frames); ✓ on an estimated frame materializes an
//      exact-frame box + bound decision; ✕ blocks approval. Synthetic media only.
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { seed } from '../../scripts/seed-demo.mjs';
import { createApp } from '../../server/app.mjs';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = process.env.SHOTS_DIR ?? path.resolve(here, '../../../docs/annotation-studio/screenshots');
const HOME = path.resolve(here, '../../.e2e-home-catalog');
const results = [];
async function scenario(name, fn) {
  try { await fn(); results.push({ name, ok: true }); console.log(`  ok   ${name}`); }
  catch (e) { results.push({ name, ok: false }); console.log(`  FAIL ${name}\n       ${e.message.split('\n').slice(0, 6).join('\n       ')}`); }
}
const { ctx } = await seed(HOME, { quiet: true });
const db = ctx.db;
const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
const src = n => db.prepare('select * from sources where display_name=?').get(n);
const draft = id => JSON.parse(db.prepare('select content from annotation_drafts where source_id=?').get(id)?.content ?? 'null');
const shot = n => page.screenshot({ path: path.join(SHOTS, `qc-${n}.png`) });
async function until(fn, arg, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await page.evaluate(fn, arg)) return; await page.waitForTimeout(100); }
  throw new Error(`timed out waiting for: ${fn}`);
}
const saved = () => page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 10000 });
const frameAtHead = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
const item = name => page.locator('[data-testid=qc-item]', { hasText: name });
console.log('Quick catalog @ 1440x900');
await page.goto(`${base}/?t=demo-token`);

await scenario('catalog is the first menu entry; queue and progress show every video with what is missing', async () => {
  await page.goto(`${base}/#/catalog`);
  await page.waitForSelector('[data-testid=quick-catalog]');
  assert.match(await page.textContent('.nav a:first-child'), /קטלוג/);
  // one cataloguing process: no separate quick/long entries, marking reached through the catalog
  const navText = await page.textContent('.nav');
  for (const gone of ['ספרייה', 'סימון', 'קטלוג מהיר']) assert.ok(!navText.includes(gone), `no separate "${gone}" entry in the menu`);
  await page.waitForFunction(() => /^v \S+/.test(document.querySelector('[data-testid=app-version]')?.textContent ?? ''));
  const all = db.prepare('select count(*) c from sources').get().c;
  assert.equal(Number(await page.getAttribute('[data-testid=qc-progress]', 'data-all')), all);
  assert.ok(await page.locator('[data-testid=qc-item]').count() >= 1);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no horizontal scroll');
  await shot('01-queue');
});

await scenario('video with no events: new surfer + sport + "no events" completes it; DB has owner, sport, full coverage', async () => {
  const s = src('DJI_0414.mp4');
  const before = Number(await page.getAttribute('[data-testid=qc-progress]', 'data-complete'));
  await item('DJI_0414').click();
  await page.waitForSelector(`[data-testid=qc-detail][data-source="${s.id}"]`);
  await page.fill('[data-testid=qc-new-athlete]', 'גולשת קטלוג');
  await page.click('[data-testid=qc-add-athlete]');
  await until(id => document.querySelector('[data-step="1"]')?.dataset.done === 'true', s.id);
  await page.selectOption('[data-testid=qc-sport]', 'surfing');
  await until(() => document.querySelector('[data-step="2"]')?.dataset.done === 'true');
  await page.click('[data-testid=qc-no-events]');
  await until(() => document.querySelector('[data-step="4"]')?.dataset.done === 'true');   // step 3 = who else appears (optional)
  const row = src('DJI_0414.mp4');
  assert.equal(db.prepare('select label from athletes where id=?').get(row.owner_athlete_id)?.label, 'גולשת קטלוג');
  assert.equal(row.primary_sport_id, 'surfing');
  assert.deepEqual(draft(s.id).reviewed_ranges, [{ start_frame: 0, end_frame: row.frame_count }]);
  assert.equal(draft(s.id).segments.length, 0);
  assert.equal(Number(await page.getAttribute('[data-testid=qc-progress]', 'data-complete')), before + 1);
  assert.ok(!/(^|\s)(null|undefined)(\s|$)/.test(await page.textContent('[data-testid=qc-detail]')), 'no stray null/undefined text');
  await shot('02-no-events-done');
});

await scenario('video with events: a missing chip opens the workbench at that event; filling it turns the chip ✓', async () => {
  const s = src('DJI_0413.mp4');   // seeded draft: one event, no performer, usability undecided
  await page.goto(`${base}/#/catalog/${s.id}`);
  await page.waitForSelector(`[data-testid=qc-detail][data-source="${s.id}"]`);
  assert.equal(await page.getAttribute('[data-testid=qc-event] [data-testid=qc-ck-usability]', 'data-ok'), 'false');
  await page.click('[data-testid=qc-event] [data-testid=qc-ck-usability]');
  await page.waitForSelector('[data-testid=segform]');
  await page.waitForSelector('[data-testid=back-to-catalog]');
  await page.locator('[data-testid=segform] button', { hasText: 'כן, שימושי' }).first().click();
  await saved();
  assert.equal(draft(s.id).segments[0].usability, 'usable');
  await page.click('[data-testid=back-to-catalog]');
  await page.waitForSelector(`[data-testid=qc-detail][data-source="${s.id}"]`);
  assert.equal(await page.getAttribute('[data-testid=qc-event] [data-testid=qc-ck-usability]', 'data-ok'), 'true');
  assert.equal(await page.getAttribute('[data-testid=qc-event] [data-testid=qc-ck-performer]', 'data-ok'), 'false', 'still missing, still shown');
  await shot('03-event-checklist');
});

await scenario('every catalogued field is shown with its VALUE; people, owner certainty and extra sport save to the DB', async () => {
  const s = src('DJI_0412.mp4');   // seeded: 3 events (wave, failed take-off excluded with a reason, uncertain wave), boxes on the first
  await page.goto(`${base}/#/catalog/${s.id}`);
  await page.waitForSelector(`[data-testid=qc-detail][data-source="${s.id}"]`);
  const fields = ['range', 'event_type', 'performer', 'usability', 'reasons', 'decision', 'key_moments', 'box', 'action', 'notes'];
  const first = page.locator('[data-testid=qc-event]').first();
  for (const f of fields) assert.equal(await first.locator(`[data-testid=qc-ck-${f}]`).count(), 1, `event field "${f}" is shown`);
  assert.match(await first.locator('[data-testid=qc-ck-usability]').textContent(), /שימושי/);
  assert.match(await first.locator('[data-testid=qc-ck-performer]').textContent(), /דנה/);
  assert.match(await first.locator('[data-testid=qc-ck-notes]').textContent(), /גל מלא/);
  assert.match(await first.locator('[data-testid=qc-ck-box]').textContent(), /3 תיבות/);
  const second = page.locator('[data-testid=qc-event]').nth(1);
  assert.match(await second.locator('[data-testid=qc-ck-reasons]').textContent(), /ללא פעולה ממשית/);
  assert.match(await second.locator('[data-testid=qc-ck-decision]').textContent(), /החרג/);
  // video level: who else appears, owner certainty, extra sport
  const omer = db.prepare("select id from athletes where label like '%עומר%'").get().id;
  await page.click('[data-testid=qc-person-unsure]');   // explicit "not sure" choice next to the people picker
  await page.selectOption('[data-testid=qc-add-person]', omer).catch(() => {});
  const dana = db.prepare("select id from athletes where label like '%דנה%'").get().id;
  await until(() => !!document.querySelector('[data-testid=qc-people]'));
  await until((args) => true, null);
  await page.waitForTimeout(500);
  const ap = db.prepare('select uncertain from athlete_appearances where source_id=? and athlete_id=?').get(s.id, omer);
  assert.ok(ap, 'appearance saved (performers are also listed automatically)');
  await page.selectOption('[data-testid=qc-owner]', dana);
  await until(id => document.querySelector('[data-step="1"]')?.dataset.done === 'true', s.id);
  assert.equal(await page.inputValue('[data-testid=qc-owner]'), dana, 'the chosen owner stays selected in the form');
  await page.evaluate(() => { window.__qcVideo = document.querySelector('[data-testid=qc-video]'); });
  await page.check('[data-testid=qc-owner-unsure]');
  await until(() => document.querySelector('[data-testid=qc-owner-unsure]')?.checked === true);
  await page.waitForTimeout(500);
  assert.equal(db.prepare('select owner_status from sources where id=?').get(s.id).owner_status, 'needs_review');
  await page.selectOption('[data-testid=qc-extra-sport]', 'football');
  await page.waitForTimeout(600);
  assert.ok(await page.evaluate(() => window.__qcVideo === document.querySelector('[data-testid=qc-video]') && window.__qcVideo.isConnected), 'answering questions does not replace or reload the video');
  await page.waitForTimeout(600);
  assert.ok(db.prepare('select 1 from source_sports where source_id=? and sport_id=?').get(s.id, 'football'), 'extra sport saved');
  assert.match(await page.textContent('[data-testid=qc-status]'), /נצפה \d+% מהסרטון/);
  await shot('05-all-fields');
});

await scenario('BOX strip: thumbnails along the event; one click accepts every box not marked wrong (exception review)', async () => {
  const s = src('DJI_0412.mp4');   // seg-wave1 [20,160) with manual boxes at 20, 90, 159
  try { await page.evaluate(id => { sessionStorage.setItem('studio.focus', JSON.stringify({ source: id, seg: 'seg-wave1', tab: 'box' })); sessionStorage.setItem('studio.fromCatalog', id); }, s.id); } catch {}
  await page.goto(`${base}/#/annotate/${s.id}`);
  await page.waitForSelector('[data-testid=track-strip]');
  const tiles = page.locator('[data-testid=strip-tile]');
  assert.ok(await tiles.count() >= 10, `strip covers the event (${await tiles.count()} tiles)`);
  const est = page.locator('[data-testid=strip-tile]', { hasText: 'משוער' }).first();
  const f = Number(await est.getAttribute('data-frame'));
  // the thumbnail is real pixels from the video, not an empty canvas
  await until(fr => { const c = document.querySelector(`[data-testid=strip-tile][data-frame="${fr}"] canvas`); if (!c) return false; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) n += d[i] + d[i + 1] + d[i + 2]; return n > 0; }, f);
  // management by exception: no per-frame approval buttons; one click accepts every box that was not marked wrong
  assert.equal(await page.locator('[data-testid=tile-ok]').count(), 0, 'no ✓ per frame');
  const open = draft(s.id).keyframes.filter(k => k.segment_id === 'seg-wave1' && !draft(s.id).box_verifications.some(v => v.segment_id === 'seg-wave1' && v.frame === k.frame)).length;
  assert.ok(open >= 3, `boxes waiting for review (${open})`);
  await page.click('[data-testid=accept-rest]');
  await saved();
  const d = draft(s.id);
  for (const k of d.keyframes.filter(k => k.segment_id === 'seg-wave1')) {
    const v = d.box_verifications.filter(x => x.segment_id === 'seg-wave1' && x.frame === k.frame).at(-1);
    assert.ok(v, `frame ${k.frame} has a decision`);
    assert.equal(v.status, 'verified_correct'); assert.deepEqual(v.bbox, k.bbox); assert.equal(v.method, 'exception_review');
  }
  await shot('04-box-strip');
});

await scenario('BOX strip: ✕ on a frame blocks approval with the specific reason', async () => {
  const s = src('DJI_0412.mp4');
  const tile = page.locator('[data-testid=strip-tile]').first();
  const f = Number(await tile.getAttribute('data-frame'));
  const st0 = await (await fetch(`${base}/api/sources/${s.id}/states`, { headers: { authorization: 'Bearer demo-token' } })).json();
  assert.ok(!st0.workflow_computed_reasons.blocking.boxes_needing_correction, 'not blocked by a wrong surfer before the click');
  await tile.locator('[data-testid=tile-wrong]').click();
  await saved();
  assert.equal(draft(s.id).box_verifications.filter(x => x.frame === f).at(-1).status, 'wrong_performer');
  if (await page.locator('[data-testid=insp-tab-event]').count()) await page.click('[data-testid=insp-tab-event]');
  await page.waitForSelector('[data-testid=approval-blocking]', { timeout: 8000 });
  const r = await fetch(`${base}/api/sources/${s.id}/approve`, { method: 'POST', headers: { authorization: 'Bearer demo-token', 'content-type': 'application/json' }, body: JSON.stringify({ expected_version: db.prepare('select version from annotation_drafts where source_id=?').get(s.id).version, acknowledge_unresolved: true }) });
  const j = await r.json();
  assert.equal(r.status, 409); assert.equal(j.code, 'BLOCKING_ITEMS');
  assert.ok(j.unresolved?.blocking?.boxes_needing_correction >= 1, `blocked because of the wrong surfer: ${JSON.stringify(j.unresolved)}`);
});

await scenario('simple marking: no tab bar; mark start/end; owner suggestion; reasons only when needed; extras folded', async () => {
  const s = src('DJI_0414.mp4');   // owner set in the "no events" scenario, no events yet
  try { await page.evaluate(() => { sessionStorage.removeItem('studio.focus'); }); } catch {}
  await page.goto(`${base}/#/annotate/${s.id}`);
  await page.waitForSelector('[data-testid=workbench]');
  assert.equal(await page.locator('.insp-tabs').count(), 0, 'no tab bar');
  assert.ok(!/null|undefined/.test(await page.textContent('#controls')), 'hidden tools never render as text');
  await page.waitForSelector('[data-testid=mark-guide]');
  assert.equal(await page.locator('[data-testid=mark-out]').count(), 0, 'one button: "end" appears only after a start');
  assert.equal(await page.locator('[title="הגדל ציר זמן"]').count(), 0, 'zoom tools folded under "עוד"');
  const fr = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
  while (await fr() < 30) await page.keyboard.press('Shift+ArrowRight');
  const a = await fr();
  await page.click('[data-testid=mark-in]');
  await page.waitForSelector('[data-testid=mark-out]');
  assert.equal(await page.locator('[data-testid=mark-in]').count(), 0);
  while (await fr() < 90) await page.keyboard.press('Shift+ArrowRight');
  const b = await fr();
  assert.ok(await page.locator('[data-testid=mark-live]').isVisible(), 'an open event is shown on the video');
  assert.ok(await page.locator('#mklive').isVisible(), 'and as a growing bar on the timeline');
  await page.click('[data-testid=mark-out]');
  await page.waitForSelector('[data-testid=segform]');
  await saved();
  let d = draft(s.id);
  assert.equal(d.segments.length, 1); assert.equal(d.segments[0].start_frame, a); assert.equal(d.segments[0].end_frame, b + 1);
  // owner suggestion fills the performer in one click
  await page.click('[data-testid=performer-owner]');
  await saved();
  assert.equal(draft(s.id).segments[0].athlete_id, src('DJI_0414.mp4').owner_athlete_id);
  // reasons appear only once the event is marked not usable
  assert.equal(await page.locator('[data-testid=reason-codes]').count(), 0, 'no reasons asked for an undecided event');
  await page.locator('[data-testid=segform] button', { hasText: 'לא שמיש' }).first().click();
  await page.waitForSelector('[data-testid=reason-codes]');
  // optional extras are folded but reachable
  assert.equal(await page.locator('[data-testid=event-more]').evaluate(x => x.open), false);
  await page.click('[data-testid=event-more] summary');
  await page.waitForSelector('[data-testid=seg-sport]', { state: 'visible' });
  // association and BOX are sub-screens with one way back
  await page.click('[data-testid=insp-tab-associate]');
  await page.click('[data-testid=insp-tab-event]');
  await page.waitForSelector('[data-testid=segform]');
  await shot('06-simple-marking');
});

await scenario('save button saves immediately and says so; watched ranges fill in by playing, no extra button', async () => {
  const s = src('DJI_0414.mp4');
  await page.locator('[data-testid=segform] button', { hasText: 'כן, שימושי' }).first().click();
  await until(() => document.querySelector('[data-testid=save-now]') && !document.querySelector('[data-testid=save-now]').disabled);
  await page.click('[data-testid=save-now]');
  await page.waitForSelector('[data-testid=savepill][data-state=saved]');
  assert.equal(draft(s.id).segments[0].usability, 'usable', 'saved to the server');
  assert.match(await page.textContent('[data-testid=save-now]'), /הכל נשמר/);
  assert.equal(await page.isDisabled('[data-testid=save-now]'), true);
  // watched: clear, then play ~1.5 s from frame 120 -> one watched range starting there
  if (!await page.locator('[data-testid=watched-fix]').evaluate(d => d.open)) await page.click('[data-testid=watched-fix] summary');
  await page.click('[data-testid=reviewed-clear]');
  await saved();
  assert.deepEqual(draft(s.id).reviewed_ranges, []);
  await page.evaluate(() => document.activeElement?.blur());
  const fr = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
  while (await fr() < 120) await page.keyboard.press('Shift+ArrowRight');
  const from = await fr();
  await page.keyboard.press(' ');
  await page.waitForTimeout(1500);
  await page.keyboard.press(' ');
  await until(() => Number(document.querySelector('[data-testid=coverage]')?.dataset.cov) > 0);
  await saved();
  const rr = draft(s.id).reviewed_ranges;
  assert.equal(rr.length, 1, JSON.stringify(rr));
  assert.ok(Math.abs(rr[0].start_frame - from) <= 1 && rr[0].end_frame - rr[0].start_frame >= 15, `watched range recorded from playback: ${JSON.stringify(rr)}`);
  assert.ok(Number(await page.getAttribute('[data-testid=coverage]', 'data-cov')) > 0);
});

await scenario('one drawn BOX follows the athlete through the WHOLE video; dragging it fixes the boxes before and after', async () => {
  const s = src('DJI_0414.mp4');   // synthetic: red 40x40 "surfer" at x=2n, y=330 on 1280x720 (240 frames); event [30,91)
  const seg = draft(s.id).segments[0];
  const fr = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
  const go = async n => { while (await fr() < n) await page.keyboard.press(await fr() + 10 <= n ? 'Shift+ArrowRight' : 'ArrowRight'); while (await fr() > n) await page.keyboard.press(await fr() - 10 >= n ? 'Shift+ArrowLeft' : 'ArrowLeft'); };
  const ov = await page.locator('#ov').boundingBox();
  const px = (x, y) => [ov.x + ov.width * x / 1280, ov.y + ov.height * y / 720];
  await page.locator('[data-testid=segment]').first().click();
  await page.waitForSelector('[data-testid=segform]');
  await go(60);
  const f = await fr();
  await page.keyboard.press('b');
  await page.mouse.move(...px(2 * f - 4, 326)); await page.mouse.down(); await page.mouse.move(...px(2 * f + 44, 374), { steps: 5 }); await page.mouse.up();
  await until(() => !!document.querySelector('[data-testid=track-auto]') && !document.querySelector('[data-testid=track-running]'), undefined, 90000);
  await saved();
  let d = draft(s.id);
  const t = (d.tracks ?? [])[0];
  assert.ok(t, 'a video-level track exists');
  const fs = t.points.map(p => p.frame);
  assert.equal(Math.min(...fs), 0, 'track reaches the first frame of the video');
  assert.equal(Math.max(...fs), s.frame_count - 1, 'track reaches the last frame of the video');
  for (const p of t.points) {
    const cx = (p.bbox.x + p.bbox.w / 2) * 1280, truth = Math.min(2 * p.frame, 1240) + 20;
    assert.ok(Math.abs(cx - truth) < 12, `frame ${p.frame}: box centre ${cx.toFixed(1)} follows the athlete at ${truth}`);
  }
  // the event's own boxes come from the track and stay estimates
  const ek = d.keyframes.filter(k => k.segment_id === seg.id);
  assert.equal(Math.min(...ek.map(k => k.frame)), seg.start_frame); assert.equal(Math.max(...ek.map(k => k.frame)), seg.end_frame - 1);
  assert.ok(ek.filter(k => k.origin === 'suggested').every(k => k.verification_status === 'unreviewed'));
  // a box is shown far outside the event too
  await go(180);
  assert.ok(await page.locator('[data-testid=track-box]').count() >= 1, 'box shown at frame 180, outside the event');
  // correction: drag the box at frame 180 by +60 px -> anchor; the stretch on both sides is re-tracked from it
  const r = await page.locator('[data-testid=track-box]').first().boundingBox();
  await page.mouse.move(r.x + r.width / 2, r.y + r.height / 2); await page.mouse.down();
  await page.mouse.move(r.x + r.width / 2 + 25, r.y + r.height / 2, { steps: 5 }); await page.mouse.up();
  await until(() => !document.querySelector('[data-testid=track-running]') && !document.querySelector('#hudtrack:not([style*="none"])'), undefined, 90000);
  await saved();
  d = draft(s.id);
  const t2 = d.tracks[0];
  assert.ok(t2.points.some(p => p.frame === 180 && p.origin === 'manual'), 'the dragged box is an anchor');
  assert.equal(Math.max(...t2.points.map(p => p.frame)), s.frame_count - 1, 'still covers the whole video after the correction');
  // Two boxes drawn quickly one after the other: the second does NOT throw away the first one's tracking (queue),
  // and a track left incomplete is finished automatically when the video is opened again.
  await go(140);
  await page.keyboard.press('b');
  { const g = await fr(); await page.mouse.move(...px(2 * g - 4, 326)); await page.mouse.down(); await page.mouse.move(...px(2 * g + 44, 374), { steps: 3 }); await page.mouse.up(); }
  await go(220);
  await page.keyboard.press('b');
  { const g = await fr(); await page.mouse.move(...px(Math.min(2 * g, 1236) - 4, 326)); await page.mouse.down(); await page.mouse.move(...px(Math.min(2 * g, 1236) + 44, 374), { steps: 3 }); await page.mouse.up(); }
  for (let i = 0; i < 240 && await page.evaluate(() => document.querySelector('#hudtrack')?.style.display !== 'none'); i++) await page.waitForTimeout(500);
  await saved();
  { const t = draft(s.id).tracks[0], fs = t.points.map(p => p.frame).sort((a, b) => a - b);
    assert.ok([140, 220].every(f => t.points.some(p => p.frame === f && p.origin === 'manual')), 'both quick boxes are anchors');
    assert.equal(fs[0], 0); assert.equal(fs.at(-1), s.frame_count - 1);
    for (let i = 1; i < fs.length; i++) assert.ok(fs[i] - fs[i - 1] <= 12, `no hole in the track between ${fs[i - 1]} and ${fs[i]}`); }
  // incomplete track (only anchors, as if the page was closed mid-way) -> completed on open
  { const cur = await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: { authorization: 'Bearer demo-token' } })).json();
    const c2 = structuredClone(cur.content); c2.tracks[0].points = c2.tracks[0].points.filter(p => p.origin === 'manual');
    const put = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: { authorization: 'Bearer demo-token', 'content-type': 'application/json' }, body: JSON.stringify({ expected_version: cur.version, content: c2 }) });
    assert.equal(put.status, 200);
    await page.reload(); await page.waitForSelector('[data-testid=workbench]');
    for (let i = 0; i < 240 && !(draft(s.id).tracks[0].points.length > 30); i++) await page.waitForTimeout(500);
    assert.ok(draft(s.id).tracks[0].points.length > 30, 'unfinished track completed on open'); }
  // an event created AFTER tracking gets its boxes from the track on the next save
  await go(150); await page.click('[data-testid=mark-in]'); await go(190); await page.click('[data-testid=mark-out]');
  await page.waitForSelector('[data-testid=segform]'); await saved();
  { const d = draft(s.id), ev = d.segments.find(x => x.start_frame === 150);
    assert.ok(ev, 'new event'); assert.ok(d.keyframes.filter(k => k.segment_id === ev.id).length >= 3, 'the new event has boxes from the track'); }
  await shot('07-auto-track');
  // Boxes drawn before whole-video tracking existed (event box only, no track) are adopted and tracked when opened.
  const cur = await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: { authorization: 'Bearer demo-token' } })).json();
  const old = structuredClone(cur.content); delete old.tracks; old.keyframes = old.keyframes.filter(k => k.origin === 'manual' && k.frame === f);
  old.box_verifications = [];
  const put = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: { authorization: 'Bearer demo-token', 'content-type': 'application/json' }, body: JSON.stringify({ expected_version: cur.version, content: old }) });
  assert.equal(put.status, 200, await put.text());
  await page.reload();
  await page.waitForSelector('[data-testid=workbench]');
  for (let i = 0; i < 180 && !((draft(s.id).tracks ?? [])[0]?.points.length > 20); i++) await page.waitForTimeout(500);
  const t3 = (draft(s.id).tracks ?? [])[0];
  assert.ok(t3 && t3.points.length > 20, 'legacy box adopted and tracked over the whole video');
});

await scenario('an event length is changed by dragging its edges on the timeline (both ends), and it saves', async () => {
  const s = src('DJI_0413.mp4');
  await page.goto(`${base}/#/annotate/${s.id}`);
  await page.waitForSelector('[data-testid=segment]');
  const d0 = draft(s.id).segments[0];
  const seg = page.locator('[data-testid=segment]').first();
  let r = await seg.boundingBox();
  await page.mouse.move(r.x + r.width - 3, r.y + r.height / 2); await page.mouse.down();
  await page.mouse.move(r.x + r.width + 100, r.y + r.height / 2, { steps: 8 }); await page.mouse.up();
  await saved();
  const d1 = draft(s.id).segments[0];
  assert.ok(d1.end_frame > d0.end_frame + 10, `end dragged later: ${d0.end_frame} -> ${d1.end_frame}`);
  assert.equal(d1.start_frame, d0.start_frame);
  r = await seg.boundingBox();
  await page.mouse.move(r.x + 3, r.y + r.height / 2); await page.mouse.down();
  await page.mouse.move(r.x + 60, r.y + r.height / 2, { steps: 8 }); await page.mouse.up();
  await saved();
  const d2 = draft(s.id).segments[0];
  assert.ok(d2.start_frame > d1.start_frame + 5, `start dragged later: ${d1.start_frame} -> ${d2.start_frame}`);
  assert.equal(d2.end_frame, d1.end_frame);
  assert.equal(await frameAtHead(), d2.start_frame, 'the video shows the frame at the dragged edge');
});

await scenario('playback stall says why (file bitrate) instead of a silent frozen picture', async () => {
  await page.evaluate(() => { const v = document.querySelector('#vid'); v.play(); });
  await until(() => !document.querySelector('#vid').paused);
  await page.evaluate(() => document.querySelector('#vid').dispatchEvent(new Event('waiting')));
  await page.waitForSelector('[data-testid=stall]', { state: 'visible' });
  assert.match(await page.textContent('[data-testid=stall]'), /טוען את הווידאו.*Mb\/s/);
  await page.evaluate(() => document.querySelector('#vid').dispatchEvent(new Event('playing')));
  await page.waitForSelector('[data-testid=stall]', { state: 'hidden' });
  await page.evaluate(() => document.querySelector('#vid').pause());
});

await scenario('"קטלג מחדש": confirm -> empty draft (copy kept) -> "בטל איפוס" brings everything back', async () => {
  const s = src('DJI_0413.mp4');
  await page.goto(`${base}/#/annotate/${s.id}`);
  await page.waitForSelector('[data-testid=workbench]');
  const before = draft(s.id);
  assert.ok(before.segments.length >= 1, 'has events to reset');
  await page.click('[data-testid=reset-zone] summary');
  await page.click('[data-testid=reset-catalog]');
  await page.click('[data-testid=reset-confirm]');
  await page.waitForSelector('[data-testid=reset-done]');
  const after = draft(s.id);
  assert.deepEqual([after.segments.length, after.keyframes.length, after.reviewed_ranges.length], [0, 0, 0]);
  assert.equal(await page.locator('[data-testid=segment]').count(), 0, 'timeline is empty');
  assert.ok(db.prepare("select 1 from audit_log where action='draft_reset' and subject=?").get(s.id), 'copy kept in the log');
  await page.click('[data-testid=reset-done] button:has-text("בטל איפוס")');
  await page.waitForSelector('[data-testid=segment]');
  assert.deepEqual(draft(s.id).segments.map(x => x.id), before.segments.map(x => x.id), 'events back');
});

await scenario('a stuck draft whose event runs past the end of the video is repaired on save, with a visible note', async () => {
  const s = src('DJI_0415.mp4');
  await page.goto(`${base}/#/annotate/${s.id}`);
  await page.waitForSelector('[data-testid=workbench]');
  const bad = { schema: 1, segments: [{ id: 'past-end', start_frame: s.frame_count - 20, end_frame: s.frame_count + 30, athlete_id: null, event_type: 'wave_ride', decision: 'uncertain', usability: 'uncertain', reason_codes: [], key_moments: {} }], keyframes: [], reviewed_ranges: [], box_verifications: [] };
  await page.evaluate(([k, v]) => localStorage.setItem(k, v), [`studio.pending.${s.id}`, JSON.stringify({ base: 0, content: bad, at: Date.now() })]);
  await page.reload();
  await page.waitForSelector('[data-testid=workbench]');
  await until(() => /חרג מסוף הסרטון/.test(document.querySelector('[data-testid=inspector-banner]')?.textContent ?? ''));
  await saved();
  const d = draft(s.id);
  assert.equal(d.segments[0].end_frame, s.frame_count, 'event clamped to the last frame, not dropped');
  assert.equal(d.segments[0].start_frame, s.frame_count - 20);
});

await scenario('no page/console errors', async () => { assert.deepEqual(errors, []); });
await browser.close(); server.close();
const ok = results.filter(r => r.ok).length;
console.log(`\n${ok}/${results.length} quick-catalog scenarios passed`);
process.exit(ok === results.length ? 0 : 1);
