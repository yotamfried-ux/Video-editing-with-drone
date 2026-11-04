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

await scenario('BOX strip: thumbnails along the event (incl. estimated frames); ✓ on an estimated frame binds an exact box', async () => {
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
  await est.locator('[data-testid=tile-ok]').click();
  await saved();
  const d = draft(s.id);
  const k = d.keyframes.find(x => x.segment_id === 'seg-wave1' && x.frame === f);
  assert.ok(k, 'exact-frame box created for the checked estimated frame'); assert.equal(k.origin, 'interpolated');
  const v = d.box_verifications.filter(x => x.segment_id === 'seg-wave1' && x.frame === f).at(-1);
  assert.equal(v.status, 'verified_correct'); assert.deepEqual(v.bbox, k.bbox); assert.ok(v.athlete_id);
  await page.waitForSelector(`[data-testid=strip-tile][data-frame="${f}"][data-status=verified_correct]`);
  await shot('04-box-strip');
});

await scenario('BOX strip: ✕ on a frame blocks approval with the specific reason', async () => {
  const s = src('DJI_0412.mp4');
  const tile = page.locator('[data-testid=strip-tile][data-status=unreviewed]').first();
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
  await page.click('[data-testid=reviewed-clear]').catch(async () => { await page.click('[data-testid=insp-panel-event] details.more summary >> nth=-1'); await page.click('[data-testid=reviewed-clear]'); });
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

await scenario('a drawn BOX follows the athlete through the whole event (auto-tracking, marked as estimate)', async () => {
  const s = src('DJI_0414.mp4');   // synthetic: red 40x40 "surfer" at x=2n, y=330 on 1280x720; event [30,91) from the marking scenario
  const seg = draft(s.id).segments[0];
  const fr = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
  await page.locator('[data-testid=segment]').first().click();
  await page.waitForSelector('[data-testid=segform]');
  while (await fr() < 60) await page.keyboard.press('ArrowRight');
  while (await fr() > 60) await page.keyboard.press('ArrowLeft');
  const f = await fr();
  await page.keyboard.press('b');
  const ov = await page.locator('#ov').boundingBox();
  const px = (x, y) => [ov.x + ov.width * x / 1280, ov.y + ov.height * y / 720];
  await page.mouse.move(...px(2 * f - 4, 326)); await page.mouse.down(); await page.mouse.move(...px(2 * f + 44, 374), { steps: 5 }); await page.mouse.up();
  await page.keyboard.press('b');
  await until(() => !!document.querySelector('[data-testid=track-auto]') && !document.querySelector('[data-testid=track-running]'), undefined, 60000);
  await saved();
  const kf = draft(s.id).keyframes.filter(k => k.segment_id === seg.id);
  const tr = kf.filter(k => k.origin === 'suggested');
  assert.ok(tr.length >= 10, `tracked boxes along the event (${tr.length})`);
  assert.equal(Math.min(...kf.map(k => k.frame)), seg.start_frame, 'reaches the start of the event');
  assert.equal(Math.max(...kf.map(k => k.frame)), seg.end_frame - 1, 'reaches the end of the event');
  for (const k of tr) {
    const cx = (k.bbox.x + k.bbox.w / 2) * 1280, truth = 2 * k.frame + 20;
    assert.ok(Math.abs(cx - truth) < 10, `frame ${k.frame}: box centre ${cx.toFixed(1)} follows the athlete at ${truth}`);
    assert.equal(k.verification_status, 'unreviewed', 'tracked = estimate, never verified');
  }
  // the box is visible on frames where nothing was drawn by hand
  while (await fr() < 85) await page.keyboard.press('ArrowRight');
  assert.ok(await page.locator('[data-testid=bbox]').count() >= 1, 'box shown at a frame far from the drawn one');
  await shot('07-auto-track');
  // A box drawn BEFORE tracking existed (only a hand-drawn box, no tracked ones) starts tracking when the event is opened.
  const cur = await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: { authorization: 'Bearer demo-token' } })).json();
  const old = structuredClone(cur.content); old.keyframes = old.keyframes.filter(k => k.origin !== 'suggested');
  const put = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: { authorization: 'Bearer demo-token', 'content-type': 'application/json' }, body: JSON.stringify({ expected_version: cur.version, content: old }) });
  assert.equal(put.status, 200);
  await page.reload();
  await page.waitForSelector('[data-testid=workbench]');
  if (!await page.locator('[data-testid=segform]').count()) await page.locator('[data-testid=segment]').first().click();
  await until(id => true, null);
  await until(() => /מעקב אוטומטי: \d+ נקודות/.test(document.querySelector('[data-testid=segform]')?.textContent ?? ''), undefined, 60000);
  await saved();
  assert.ok(draft(s.id).keyframes.filter(k => k.origin === 'suggested').length >= 10, 'existing box tracked on open');
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
