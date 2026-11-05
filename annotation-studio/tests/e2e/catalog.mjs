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
// tracking is done only when the progress pill stays hidden for a while (it hides briefly between queued passes)
async function trackingIdle(timeout = 180000) {
  const end = Date.now() + timeout; let quiet = 0;
  while (Date.now() < end && quiet < 5) { quiet = await page.evaluate(() => document.querySelector('#hudtrack')?.style.display === 'none') ? quiet + 1 : 0; await page.waitForTimeout(400); }
}
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
  { const g = await fr(); await page.mouse.move(...px(Math.min(2 * g, 1236) - 8, 320)); await page.mouse.down(); await page.mouse.move(...px(Math.min(2 * g, 1236) + 48, 382), { steps: 3 }); await page.mouse.up(); }   // drawn a bit larger, like a real correction
  await trackingIdle();
  await saved();
  { const t = draft(s.id).tracks[0], fs = t.points.map(p => p.frame).sort((a, b) => a - b);
    assert.ok([140, 220].every(f => t.points.some(p => p.frame === f && p.origin === 'manual')), 'both quick boxes are anchors');
    assert.equal(fs[0], 0); assert.equal(fs.at(-1), s.frame_count - 1);
    for (let i = 1; i < fs.length; i++) assert.ok(fs[i] - fs[i - 1] <= 12, `no hole in the track between ${fs[i - 1]} and ${fs[i]}`);
    // no shaking: between two consecutive drawn boxes the box moves smoothly (no back-and-forth between estimates).
    // Measured as the second difference of the centre, in px, sample to sample (the old two-grid merge gave ~40 px).
    const man = t.points.filter(p => p.origin === 'manual').map(p => p.frame).sort((a, b) => a - b);
    for (let a = 0; a < man.length - 1; a++) {
      const mid = t.points.filter(p => p.frame > man[a] && p.frame < man[a + 1]).sort((x, y) => x.frame - y.frame);
      const cx = mid.map(p => (p.bbox.x + p.bbox.w / 2) * 1280), cy = mid.map(p => (p.bbox.y + p.bbox.h / 2) * 720);
      for (let i = 2; i < mid.length; i++) {
        const j = Math.hypot(cx[i] - 2 * cx[i - 1] + cx[i - 2], cy[i] - 2 * cy[i - 1] + cy[i - 2]);
        assert.ok(j < 9, `box shakes at frame ${mid[i].frame} (between drawn boxes ${man[a]} and ${man[a + 1]}): ${j.toFixed(1)} px | ${mid.map((p, k) => `${p.frame}:${cx[k].toFixed(0)}`).join(' ')}`);
      }
    } }
  // incomplete track (only anchors, as if the page was closed mid-way) -> completed on open
  { const cur = await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: { authorization: 'Bearer demo-token' } })).json();
    const c2 = structuredClone(cur.content); c2.tracks[0].points = c2.tracks[0].points.filter(p => p.origin === 'manual');
    const put = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: { authorization: 'Bearer demo-token', 'content-type': 'application/json' }, body: JSON.stringify({ expected_version: cur.version, content: c2 }) });
    assert.equal(put.status, 200);
    await page.reload(); await page.waitForSelector('[data-testid=workbench]'); const t0 = Date.now();
    for (let i = 0; i < 240 && !(draft(s.id).tracks[0].points.length > 30); i++) await page.waitForTimeout(500);
    const why = await page.evaluate(() => ['#hudtrack', '[data-testid=track-failed]', '[data-testid=savepill]', '.banner'].map(q => `${q}=${(document.querySelector(q)?.textContent ?? '-').trim().slice(0, 160)}`).join(' | '));
    assert.ok(draft(s.id).tracks[0].points.length > 30, `unfinished track completed on open (after ${Date.now() - t0} ms; points ${draft(s.id).tracks.map(t => t.points.length)}; ${why})`); }
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

await scenario('saved catalogs repair themselves on open: events with no boxes get them from the track; boxes drawn before choosing a surfer join that surfer', async () => {
  const s = src('DJI_0414.mp4'), x = src('DJI_0414.mp4').owner_athlete_id;
  const H = { authorization: 'Bearer demo-token', 'content-type': 'application/json' };
  const getD = async () => (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: H })).json();
  const putD = async (cur, content) => { const r = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: H, body: JSON.stringify({ expected_version: cur.version, content }) }); assert.equal(r.status, 200, await r.text()); };
  const open = async () => { await page.goto(`${base}/#/catalog`); await page.goto(`${base}/#/annotate/${s.id}`); await page.waitForSelector('[data-testid=workbench]'); };
  await open(); await page.waitForTimeout(500); await trackingIdle();
  await saved();
  // (a) like live video 0165: a whole-video track of the event's surfer, but the events were saved with no boxes
  { const cur = await getD(), c = structuredClone(cur.content);
    assert.ok(c.tracks?.length && c.segments.length);
    for (const t of c.tracks) t.athlete_id = x; c.tracks = c.tracks.slice(0, 1);
    for (const g of c.segments) g.athlete_id = x;
    c.keyframes = []; c.box_verifications = [];
    await putD(cur, c); }
  await open();
  for (let i = 0; i < 40 && !draft(s.id).keyframes.length; i++) await page.waitForTimeout(250);
  await saved();
  { const d = draft(s.id);
    for (const g of d.segments) {
      const n = d.keyframes.filter(k => k.segment_id === g.id).length;
      assert.ok(n >= 3, `event ${g.start_frame}-${g.end_frame} got ${n} boxes from the track on open (no click needed)`);
      for (const k of d.keyframes.filter(k => k.segment_id === g.id)) assert.ok(k.frame >= g.start_frame && k.frame < g.end_frame);
    } }
  // round trip: opening again changes nothing (what was saved is exactly what is shown and kept)
  { const v = (await getD()).version; await open(); await page.waitForTimeout(1500); assert.equal((await getD()).version, v, 'reopening a complete catalog does not rewrite it');
    await page.goto(`${base}/#/annotate/${s.id}`); }
  // (b) like live video 0163: boxes drawn before a surfer was chosen sit on a track with no surfer
  { const cur = await getD(), c = structuredClone(cur.content), t = c.tracks[0];
    const orphan = { id: 'orphan-track', athlete_id: null, points: t.points.filter(p => p.origin === 'manual').map(p => ({ ...p, frame: Math.min(p.frame + 5, s.frame_count - 1) })) };
    t.points = t.points.filter(p => p.origin === 'manual'); c.tracks = [t, orphan]; c.keyframes = []; c.box_verifications = [];
    await putD(cur, c); }
  await open();
  for (let i = 0; i < 240 && !(draft(s.id).tracks.length === 1 && draft(s.id).tracks[0].points.length > 30 && draft(s.id).keyframes.length); i++) await page.waitForTimeout(500);
  await saved();
  { const d = draft(s.id);
    assert.equal(d.tracks.length, 1, 'no track without a surfer is left');
    assert.equal(d.tracks[0].athlete_id, x, 'the boxes now belong to the surfer of the events');
    assert.ok(d.tracks[0].points.filter(p => p.origin === 'manual').length >= 2, 'its hand-drawn boxes were kept as anchors');
    assert.ok(d.tracks[0].points.length > 30, 'and the surfer is tracked through the video again');
    for (const g of d.segments) assert.ok(d.keyframes.filter(k => k.segment_id === g.id).length >= 3, 'events have boxes'); }
});

await scenario('a track saved by the old merge (two interleaved grids = shaking box) is re-tracked smoothly when opened', async () => {
  const s = src('DJI_0414.mp4');
  const H = { authorization: 'Bearer demo-token', 'content-type': 'application/json' };
  const cur = await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: H })).json(), c = structuredClone(cur.content);
  const t = c.tracks[0], B = (x, y) => ({ x: x / 1280, y: y / 720, w: 48 / 1280, h: 48 / 720 });
  // anchors at 60 and 150; inside: forward samples on 60+3k, backward samples on 150-3k shifted by 20 px (as the old code saved them)
  t.points = [{ frame: 60, bbox: B(2 * 60 - 4, 326), origin: 'manual' }, { frame: 150, bbox: B(2 * 150 - 4, 326), origin: 'manual' }];
  for (let f = 63; f < 150; f += 3) t.points.push({ frame: f, bbox: B(2 * f - 4, 326), origin: 'suggested' });
  for (let f = 148; f > 60; f -= 3) if (!t.points.some(p => p.frame === f)) t.points.push({ frame: f, bbox: B(2 * f + 16, 326), origin: 'suggested' });
  t.points.sort((a, b) => a.frame - b.frame);
  // the event's boxes copied from that track, and the whole thing APPROVED (as happened live with 0163 v4)
  const ev = c.segments[0]; Object.assign(ev, { start_frame: 30, end_frame: 200, athlete_id: t.athlete_id, usability: 'usable', decision: 'include' });
  c.segments = [ev]; c.reviewed_ranges = [{ start_frame: 0, end_frame: s.frame_count }];
  c.tracks = [t]; c.box_verifications = [];
  c.keyframes = t.points.filter(p => p.frame >= 30 && p.frame < 200).map((p, i) => ({ id: `mk${i}`, segment_id: ev.id, frame: p.frame, bbox: { ...p.bbox }, visibility: 'visible', origin: 'suggested', verification_status: 'unreviewed' }));
  const put = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: H, body: JSON.stringify({ expected_version: cur.version, content: c }) });
  assert.equal(put.status, 200, await put.text());
  const v = (await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: H })).json()).version;
  const ap = await fetch(`${base}/api/sources/${s.id}/approve`, { method: 'POST', headers: H, body: JSON.stringify({ expected_version: v, accept_by_exception: true, acknowledge_unresolved: true }) });
  assert.equal(ap.status, 200, await ap.text());
  assert.equal((await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: H })).json()).approved_current, true);
  await page.goto(`${base}/#/catalog`); await page.goto(`${base}/#/annotate/${s.id}`); await page.waitForSelector('[data-testid=workbench]');
  const offGrid = () => draft(s.id).tracks[0].points.filter(p => p.origin !== 'manual' && p.frame > 60 && p.frame < 150 && (p.frame - 60) % 3 !== 0 && p.frame !== 149).length;
  for (let i = 0; i < 240 && offGrid() > 0; i++) await page.waitForTimeout(500);
  await trackingIdle(); await saved();
  assert.equal(offGrid(), 0, 'one grid between the two drawn boxes after opening');
  // the event's boxes follow the repaired track: no box from the old second grid is left, and checks made on the
  // old geometry no longer count (the video now needs approving again)
  { const d = draft(s.id), ev = d.segments[0];
    const evOff = d.keyframes.filter(k => k.segment_id === ev.id && k.origin === 'suggested' && k.frame > 60 && k.frame < 150 && (k.frame - 60) % 3 !== 0 && k.frame !== 149);
    assert.equal(evOff.length, 0, `event boxes from the old grid left: ${evOff.map(k => k.frame)}`);
    const tr = new Map(d.tracks[0].points.map(p => [p.frame, p.bbox]));
    for (const k of d.keyframes.filter(k => k.segment_id === ev.id && k.origin === 'suggested')) { const p = tr.get(k.frame); assert.ok(p && ['x', 'y', 'w', 'h'].every(q => Math.abs(p[q] - k.bbox[q]) < 1e-4), `event box at ${k.frame} = track: ${JSON.stringify(k.bbox)} vs ${JSON.stringify(p)}`); }
    const latest = new Map(); for (const x of d.box_verifications) latest.set(`${x.segment_id}:${x.frame}`, x);
    const stale = d.keyframes.filter(k => k.segment_id === ev.id && latest.get(`${ev.id}:${k.frame}`)?.status === 'verified_correct' && ['x', 'y', 'w', 'h'].some(q => Math.abs(latest.get(`${ev.id}:${k.frame}`).bbox[q] - k.bbox[q]) > 1e-4));
    assert.equal(stale.length, 0, 'no check left on a geometry that changed'); }
  { const it = (await (await fetch(`${base}/api/catalog/queue`, { headers: H })).json()).items.find(i => i.source_id === s.id);
    assert.equal(it.approved_current, false, 'shown as changed since approval -> approve the clean track'); }
  const mid = draft(s.id).tracks[0].points.filter(p => p.frame > 60 && p.frame < 150).sort((a, b) => a.frame - b.frame);
  const cx = mid.map(p => (p.bbox.x + p.bbox.w / 2) * 1280);
  for (let i = 2; i < cx.length; i++) assert.ok(Math.abs(cx[i] - 2 * cx[i - 1] + cx[i - 2]) < 9, `smooth at ${mid[i].frame}`);
});

await scenario('a page left open learns about a newer deployment: banner now, reload on the next page change', async () => {
  await page.goto(`${base}/#/catalog`); await page.reload(); await page.waitForSelector('[data-testid=qc-item]');
  await page.route('**/api/version', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ commit: 'f00dbab' }) }));
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await page.waitForSelector('[data-testid=new-version]');
  assert.match(await page.textContent('[data-testid=new-version]'), /גרסה חדשה.*f00dbab/);
  await page.unroute('**/api/version');
  const nav = page.waitForEvent('load');
  await page.evaluate(() => { location.hash = '#/athletes'; });
  await nav;   // moving to another page reloads into the new code
  await page.waitForSelector('#main, main');
});

await scenario('the video is downloaded ONCE into the browser (with progress); playback, tracking and thumbnails then use that copy', async () => {
  const s = src('DJI_0414.mp4');
  const hits = []; const count = r => { if (r.url().includes(`/media/${s.id}/`)) hits.push(r.url()); };
  // a slow connection: the download takes a moment, so the progress pill is visible
  await page.route(`**/media/${s.id}/**`, async route => { await new Promise(r => setTimeout(r, 1500)); await route.continue(); });
  page.on('request', count);
  await page.goto(`${base}/#/catalog`); await page.goto(`${base}/#/annotate/${s.id}`); await page.waitForSelector('[data-testid=workbench]');
  await page.waitForSelector('[data-testid=local-copy]', { state: 'visible', timeout: 5000 });
  assert.match(await page.textContent('[data-testid=local-copy]'), /מוריד את הסרטון לדפדפן/);
  await until(() => document.querySelector('#vid').src.startsWith('blob:'), null, 30000);
  await page.waitForSelector('[data-testid=local-copy]', { state: 'hidden' });
  await page.unroute(`**/media/${s.id}/**`);
  // tracking now reads the copy: re-track the whole video and check no new download of the video is made
  const before = hits.length;
  await page.evaluate(() => { const v = document.querySelector('#vid'); v.currentTime = 1; });
  await page.locator('[data-testid=segment]').first().click(); await page.waitForSelector('[data-testid=segform]');
  const n0 = draft(s.id).tracks[0].points.length;
  await page.keyboard.press('b');
  const ov = await page.locator('#ov').boundingBox(), fr = Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
  const px = (x, y) => [ov.x + ov.width * x / 1280, ov.y + ov.height * y / 720];
  await page.mouse.move(...px(2 * fr - 4, 326)); await page.mouse.down(); await page.mouse.move(...px(2 * fr + 44, 374), { steps: 3 }); await page.mouse.up();
  await trackingIdle(); await saved();
  assert.ok(draft(s.id).tracks[0].points.length >= Math.min(n0, 30), 'tracking ran');
  page.off('request', count);
  assert.equal(hits.length - before, 0, `no extra video downloads after the copy (saw ${hits.slice(before).join(', ')})`);
});

await scenario('approving accepts the boxes not marked wrong (exception review); the catalog counts it done + approved, and "changed since approval" when edited after', async () => {
  const s = src('DJI_0414.mp4'), x = s.owner_athlete_id;
  const H = { authorization: 'Bearer demo-token', 'content-type': 'application/json' };
  const getD = async () => (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: H })).json();
  const queueItem = async () => (await (await fetch(`${base}/api/catalog/queue`, { headers: H })).json()).items.find(i => i.source_id === s.id);
  { const cur = await getD(), c = structuredClone(cur.content);
    for (const g of c.segments) Object.assign(g, { athlete_id: x, usability: 'usable', decision: 'include', reason_codes: [], needs_review: false });
    c.reviewed_ranges = [{ start_frame: 0, end_frame: s.frame_count }]; c.box_verifications = [];
    for (const k of c.keyframes) k.verification_status = 'unreviewed';
    const r = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: H, body: JSON.stringify({ expected_version: cur.version, content: c }) }); assert.equal(r.status, 200, await r.text()); }
  await page.goto(`${base}/#/catalog`); await page.goto(`${base}/#/annotate/${s.id}`); await page.waitForSelector('[data-testid=workbench]');
  await trackingIdle(); await saved();
  const boxes = draft(s.id).keyframes.length; assert.ok(boxes > 5);
  await page.keyboard.press('Escape');
  await page.waitForSelector('[data-testid=approval-exception-boxes]');
  await until(n => document.querySelector('[data-testid=approval-exception-boxes]')?.dataset.toVerify === String(n), boxes);
  assert.match(await page.textContent('[data-testid=approval-exception-boxes]'), new RegExp(`${boxes} יאומתו`));
  await page.click('[data-testid=approve]');
  await page.waitForTimeout(800);
  if (!await page.locator('[data-testid=revlist] li b').count() || await page.locator('.toast.bad').count()) {
    if (await page.locator('[data-testid=ack]').count()) await page.check('[data-testid=ack]');
    await page.click('[data-testid=approve]');
  }
  await page.waitForSelector('[data-testid=revlist] li b');
  const rev = JSON.parse(db.prepare('select content from annotation_revisions where source_id=? order by seq desc').get(s.id).content);
  const ok = rev.box_verifications.filter(v => v.status === 'verified_correct' && v.method === 'exception_review');
  assert.equal(ok.length, boxes, 'every box not marked wrong is recorded as checked-correct in the approved version');
  assert.ok(rev.keyframes.every(k => k.verification_status === 'verified_correct'));
  { const it = await queueItem(); assert.equal(it.approved_current, true); assert.equal(it.complete, true, `catalog fields complete (missing ${it.missing})`); }
  // the page took the server's draft (with the approval's decisions): no stale save afterwards, and a refresh keeps the status
  await page.reload(); await page.waitForSelector('[data-testid=workbench]'); await page.waitForTimeout(1500);
  { const it = await queueItem(); assert.equal(it.approved_current, true, 'still approved after a browser refresh (nothing rewrote the draft)'); }
  // after approval, stepping through the event shows ONE steady checked box on every frame (no green box on the
  // checked frames flickering with a dashed one in between, no second track box)
  { const ev = draft(s.id).segments[0];
    const fr = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
    while (await fr() < ev.start_frame + 2) await page.keyboard.press('ArrowRight');
    for (let i = 0; i < 14; i++) {
      const f = await fr();
      const st = await page.evaluate(() => ({ n: document.querySelectorAll('[data-testid=bbox]').length, t: document.querySelectorAll('[data-testid=track-box]').length,
        v: [...document.querySelectorAll('[data-testid=bbox]')].map(e => e.getAttribute('data-verified')), dash: [...document.querySelectorAll('[data-testid=bbox]')].map(e => getComputedStyle(e).strokeDasharray) }));
      assert.equal(st.n + st.t, 1, `frame ${f}: one box on screen (${st.n} event + ${st.t} track)`);
      assert.deepEqual(st.v, ['true'], `frame ${f}: the box is shown as checked`);
      assert.ok(st.dash.every(d => d === 'none' || d === ''), `frame ${f}: solid, not dashed (${st.dash})`);
      await page.keyboard.press('ArrowRight');
    } }
  await page.goto(`${base}/#/catalog`); await page.waitForSelector('[data-testid=qc-item]');
  await page.click('button.chip:has-text("הושלמו")');
  assert.match(await page.locator('[data-testid=qc-item]', { hasText: 'DJI_0414.mp4' }).textContent(), /הושלם · מאושר v\d/);
  // edited after approval -> not done until approved again
  { const cur = await getD(), c = structuredClone(cur.content); c.segments[0].notes = 'שינוי אחרי אישור';
    await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: H, body: JSON.stringify({ expected_version: cur.version, content: c }) }); }
  { const it = await queueItem(); assert.equal(it.approved, true); assert.equal(it.approved_current, false, 'changed since approval'); }
  await page.reload();   // the catalog page was already open: load the queue again
  await page.waitForSelector('[data-testid=qc-item]');
  await page.click('button.chip:has-text("לטיפול")');
  assert.match(await page.locator('[data-testid=qc-item]', { hasText: 'DJI_0414.mp4' }).textContent(), /שונה מאז אישור v\d · נדרש אישור מחדש/);
});

await scenario('approval panel: open items are in Hebrew, say how to fix them, and a click jumps to the event', async () => {
  const s = src('DJI_0414.mp4');
  const H = { authorization: 'Bearer demo-token', 'content-type': 'application/json' };
  const cur = await (await fetch(`${base}/api/sources/${s.id}/draft`, { headers: H })).json(), c = structuredClone(cur.content);
  for (const g of c.segments) Object.assign(g, { athlete_id: null, primary_status: null, usability: 'usable', decision: 'include' });
  c.box_verifications = []; for (const k of c.keyframes) k.verification_status = 'unreviewed';
  const put = await fetch(`${base}/api/sources/${s.id}/draft`, { method: 'PUT', headers: H, body: JSON.stringify({ expected_version: cur.version, content: c }) });
  assert.equal(put.status, 200, await put.text());
  await page.goto(`${base}/#/catalog`); await page.goto(`${base}/#/annotate/${s.id}`); await page.waitForSelector('[data-testid=workbench]');
  await trackingIdle(); await saved();
  await page.keyboard.press('Escape');
  const item = page.locator('[data-testid=unresolved-item][data-key=usable_without_primary]');
  await item.waitFor();
  const txt = await item.textContent();
  assert.match(txt, /אירועים שמישים בלי גולש מבצע/); assert.match(txt, /מי ביצע את הפעולה/);
  assert.ok(!/usable_without_primary/.test(await page.textContent('[data-testid=approval-panel]')), 'no raw keys on screen');
  await item.click();
  await page.waitForSelector('[data-testid=segform]');
  const sel = await page.evaluate(() => document.querySelector('[data-testid=segment].sel')?.getAttribute('data-id') ?? document.querySelector('[data-testid=segment].sel') !== null);
  assert.ok(sel, 'the event is selected');
});

await scenario('no page/console errors', async () => { assert.deepEqual(errors, []); });
await browser.close(); server.close();
const ok = results.filter(r => r.ok).length;
console.log(`\n${ok}/${results.length} quick-catalog scenarios passed`);
process.exit(ok === results.length ? 0 : 1);
