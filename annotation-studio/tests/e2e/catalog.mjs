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
  await until(() => document.querySelector('[data-step="3"]')?.dataset.done === 'true');
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
  await page.locator('.insp-tabs button', { hasText: 'תיוג אירוע' }).click().catch(() => {});
  await page.waitForSelector('[data-testid=approval-blocking]', { timeout: 8000 });
  const r = await fetch(`${base}/api/sources/${s.id}/approve`, { method: 'POST', headers: { authorization: 'Bearer demo-token', 'content-type': 'application/json' }, body: JSON.stringify({ expected_version: db.prepare('select version from annotation_drafts where source_id=?').get(s.id).version, acknowledge_unresolved: true }) });
  const j = await r.json();
  assert.equal(r.status, 409); assert.equal(j.code, 'BLOCKING_ITEMS');
  assert.ok(j.unresolved?.blocking?.boxes_needing_correction >= 1, `blocked because of the wrong surfer: ${JSON.stringify(j.unresolved)}`);
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
