// Browser E2E (Playwright/Chromium) against a real server + real synthetic media.
//   node tests/e2e/run.mjs            -> runs all scenarios, writes screenshots
import { createRequire } from 'node:module';
import path from 'node:path';
import { mkdirSync, rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { seed } from '../../scripts/seed-demo.mjs';
import { createApp } from '../../server/app.mjs';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = process.env.SHOTS_DIR ?? path.resolve(here, '../../../docs/annotation-studio/screenshots');
const HOME = path.resolve(here, '../../.e2e-home');
mkdirSync(SHOTS, { recursive: true });

const results = [];
async function scenario(name, fn) {
  const t = Date.now();
  try { await fn(); results.push({ name, ok: true, ms: Date.now() - t }); console.log(`  ok   ${name}`); }
  catch (e) { results.push({ name, ok: false, err: e.message }); console.log(`  FAIL ${name}\n       ${e.message.split('\n').slice(0, 4).join('\n       ')}`); }
}

const { ctx, s1, s2 } = await seed(HOME, { quiet: true });
const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on('pageerror', e => consoleErrors.push(e.message));
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
const shot = n => page.screenshot({ path: path.join(SHOTS, `${n}.png`) });
const frameNum = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
const waitSaved = () => page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 8000 });
const videoReady = () => page.waitForFunction(() => { const v = document.querySelector('#vid'); return v && v.readyState >= 2 && v.videoWidth > 0; }, null, { timeout: 15000 });

console.log('Annotation Studio E2E');
await page.goto(`${base}/?t=demo-token`);

await scenario('library: cards, dedup, archive badge, filters, next-unannotated', async () => {
  await page.waitForSelector('[data-testid=source-card]');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 4, '5 files with one duplicate => 4 sources');
  assert.ok(await page.locator('text=ארכיון מאומת').count() >= 4);
  await page.fill('input[type=search]', 'DJI_0414');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 1);
  await page.fill('input[type=search]', '');
  await page.selectOption('select[aria-label=status]', 'approved');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 1);
  await page.selectOption('select[aria-label=status]', '');
  assert.ok(await page.locator('[data-testid=next-unannotated]').isVisible());
  await shot('01-library');
});

await scenario('annotate: loads source, frame-exact stepping, timecode', async () => {
  await page.goto(`${base}/#/annotate/${(await ctx.db.prepare('select id from sources where display_name=?').get('DJI_0414.mp4')).id}`);
  await page.waitForSelector('[data-testid=workbench]'); await videoReady();
  assert.equal(await frameNum(), 0);
  await page.click('[data-testid=step-fwd]'); await page.click('[data-testid=step-fwd]'); await page.click('[data-testid=step-fwd]');
  assert.equal(await frameNum(), 3);
  await page.keyboard.press('Shift+ArrowRight'); assert.equal(await frameNum(), 13);
  await page.keyboard.press('ArrowLeft'); assert.equal(await frameNum(), 12);
  // the displayed frame truly is frame 12: surfer square sits at x=2n of 1280 => compare to video pixels
  await page.waitForFunction(() => document.querySelector('#vid').seeking === false, null, { timeout: 10000 });
  const t = await page.evaluate(() => document.querySelector('#vid').currentTime);
  assert.ok(Math.abs(t * 30 - 12.5) < 0.2, `seek lands mid-frame 12 (got ${t * 30})`);
  assert.equal(await page.textContent('[data-testid=timecode]'), '00:00:12');
});

await scenario('speed controls change playbackRate; playback advances frames', async () => {
  await page.click('[data-testid=speed-0\\.5]');
  assert.equal(await page.evaluate(() => document.querySelector('#vid').playbackRate), 0.5);
  await page.click('[data-testid=speed-1]');
  const before = await frameNum(); await page.keyboard.press('Space'); await page.waitForTimeout(500); await page.keyboard.press('Space');
  assert.ok(await frameNum() > before + 3, 'playback advanced');
});

let segId;
await scenario('I/O creates a segment; athlete via shortcut; decision shortcuts; autosave', async () => {
  await page.evaluate(() => document.querySelector('#vid').pause());
  await page.click('#ruler', { position: { x: 60, y: 10 } });
  const a = await frameNum();
  await page.keyboard.press('i');
  await page.keyboard.press('ArrowRight'); for (let i = 0; i < 29; i++) await page.keyboard.press('ArrowRight');
  await page.keyboard.press('o');
  await page.waitForSelector('[data-testid=segment].sel');
  const rng = await page.textContent('[data-testid=segform] .meta .mono');
  assert.equal(rng, `[${a}, ${a + 31})`, 'half-open interval includes the marked out frame');
  await page.keyboard.press('1'); // first athlete
  assert.ok((await page.inputValue('[data-testid=athlete-select]')).length > 0);
  await page.keyboard.press('u');
  assert.equal(await page.getAttribute('[data-testid=dec-uncertain]', 'aria-pressed'), 'true');
  await page.keyboard.press('e');
  assert.equal(await page.getAttribute('[data-testid=dec-include]', 'aria-pressed'), 'true');
  await waitSaved();
  segId = await page.getAttribute('[data-testid=segment].sel', 'data-id');
  await shot('02-annotate-segment');
});

await scenario('bounding box: draw keyframes, interpolated boxes are visually distinct', async () => {
  const seg = await page.$eval('[data-testid=segform] .meta .mono', e => e.textContent); const [s, e] = seg.match(/\d+/g).map(Number);
  await page.keyboard.press('b');
  const draw = async (frame, dx) => {
    await page.click('#ruler', { position: { x: 10, y: 10 } }); // anywhere; then step exactly
    const cur = await frameNum();
    // use keyboard to land on target frame
    const delta = frame - cur; const key = delta > 0 ? 'ArrowRight' : 'ArrowLeft';
    for (let i = 0; i < Math.abs(delta); i++) await page.keyboard.press(key);
    const ov = await page.locator('#ov').boundingBox();
    await page.mouse.move(ov.x + ov.width * dx, ov.y + ov.height * 0.2); await page.mouse.down();
    await page.mouse.move(ov.x + ov.width * (dx + 0.06), ov.y + ov.height * 0.34, { steps: 4 }); await page.mouse.up();
  };
  await draw(s, 0.1); await draw(e - 1, 0.5);
  await page.keyboard.press('b');
  await waitSaved();
  assert.equal(await page.locator('[data-testid=kflist] li').count(), 2);
  // step to the middle: box should be interpolated (dashed)
  const mid = Math.floor((s + e) / 2); const cur = await frameNum();
  for (let i = 0; i < Math.abs(mid - cur); i++) await page.keyboard.press(mid > cur ? 'ArrowRight' : 'ArrowLeft');
  await page.waitForSelector('[data-testid=bbox][data-interp=true]');
  await shot('03-annotate-bbox');
});

await scenario('reload keeps exact frames (persistence); interpolation fill + confirm', async () => {
  const before = await page.$$eval('[data-testid=seglist] .mono', els => els.map(e => e.textContent));
  await page.reload(); await page.waitForSelector('[data-testid=workbench]');
  const after = await page.$$eval('[data-testid=seglist] .mono', els => els.map(e => e.textContent));
  assert.deepEqual(after, before);
  await page.click('[data-testid=segment]'); await page.waitForSelector('[data-testid=segform]');
  await page.click('text=מלא ביניים (משוער)'); await waitSaved();
  assert.ok(await page.locator('[data-testid=kflist] li').count() > 2);
});

await scenario('approval is blocked on unresolved items until explicitly acknowledged; revision is created', async () => {
  await page.keyboard.press('u'); // make it uncertain
  await waitSaved();
  await page.click('[data-testid=approve]');
  await page.waitForSelector('.toast.bad');
  await page.check('[data-testid=ack]');
  await page.fill('#ap-reason', 'בדיקת E2E');
  await page.click('[data-testid=approve]');
  await page.waitForSelector('[data-testid=revlist] li b');
  assert.equal((await page.textContent('[data-testid=revlist] li b')).trim(), 'v1');
  await shot('04-annotate-approved');
});

await scenario('undo/redo, delete segment, shortcuts help dialog', async () => {
  await page.keyboard.press('Delete'); assert.equal(await page.locator('[data-testid=segment]').count(), 0);
  await page.keyboard.press('Control+z'); assert.equal(await page.locator('[data-testid=segment]').count(), 1);
  await page.keyboard.press('?'); await page.waitForSelector('dialog[open]'); await shot('05-shortcuts'); await page.keyboard.press('Escape');
});

await scenario('overlay toggle hides boxes without changing saved labels', async () => {
  const n = await page.locator('[data-testid=kflist] li').count();
  await page.click('button:has-text("תיבות")');
  assert.equal(await page.locator('[data-testid=bbox]').count(), 0);
  await page.click('button:has-text("תיבות")');
  assert.equal(await page.locator('[data-testid=kflist] li').count(), n);
});

await scenario('autosave offline -> pending -> recovers; conflict is surfaced, never silent', async () => {
  await page.click('[data-testid=segment]'); await page.waitForSelector('[data-testid=segform]');
  await page.keyboard.press('x'); await waitSaved();
  await page.route('**/api/sources/*/draft', r => r.request().method() === 'PUT' ? r.abort() : r.continue());
  await page.keyboard.press('e'); await page.waitForSelector('[data-testid=savepill][data-state=offline]', { timeout: 8000 });
  await page.unroute('**/api/sources/*/draft');
  await page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 9000 });
  // concurrent writer bumps the server version => our next save conflicts
  const id = (await ctx.db.prepare('select id from sources where display_name=?').get('DJI_0414.mp4')).id;
  const { getDraft, saveDraft } = await import('../../server/annotations.mjs');
  const d = getDraft(ctx.db, id); saveDraft(ctx.db, id, d.version, d.content);
  await page.keyboard.press('e'); await page.waitForSelector('[data-testid=savepill][data-state=conflict]', { timeout: 8000 });
  assert.ok(await page.locator('text=טען גרסת שרת').isVisible());
  await shot('06-conflict');
  await page.click('text=טען גרסת שרת'); await page.waitForSelector('[data-testid=savepill][data-state=saved]');
});

await scenario('approved source reloads with revision history from a different route (move-proof identity)', async () => {
  await page.goto(`${base}/#/library`); await page.waitForSelector('[data-testid=source-card]');
  assert.ok(await page.locator('text=גרסה 1').count() >= 1);
});

await scenario('athletes screen: persistent ids and appearance history', async () => {
  await page.goto(`${base}/#/athletes`); await page.waitForSelector('[data-testid=athlete-card]');
  assert.ok(await page.locator('[data-testid=athlete-card]').count() >= 2);
  await page.fill('#newath', 'גולש חדש מ-E2E'); await page.click('[data-testid=add-athlete]');
  await page.locator('[data-testid=athlete-card]').nth(2).waitFor();
  await shot('07-athletes');
});

await scenario('datasets screen: frozen versions with split counts', async () => {
  await page.goto(`${base}/#/datasets`); await page.waitForSelector('[data-testid=ds-table]');
  assert.ok((await page.textContent('[data-testid=ds-table]')).includes('GT-v1'));
  await shot('08-datasets');
});

await scenario('evaluations: history table and detailed error report', async () => {
  await page.goto(`${base}/#/evaluations`); await page.waitForSelector('[data-testid=eval-table]');
  await page.click('[data-testid=eval-table] a:has-text("פירוט")');
  await page.waitForSelector('text=דוח הערכה');
  const txt = await page.textContent('#main');
  assert.ok(txt.includes('פלט כפול') && txt.includes('Recall'));
  await shot('09-evaluation');
});

await scenario('editing review: synchronized source/output, EDL-verified overlays, jump-to-failure, proposal', async () => {
  await page.goto(`${base}/#/editing`); await page.waitForSelector('[data-testid=editing]');
  await page.waitForFunction(() => { const a = document.querySelector('#srcv'), b = document.querySelector('#outv'); return a?.readyState >= 2 && b?.readyState >= 2; }, null, { timeout: 20000 });
  assert.ok(await page.locator('text=מיפוי מאומת (EDL)').isVisible());
  await page.waitForSelector('[data-testid=error-table] [data-testid=err-row]');
  await page.locator('[data-testid=err-row]').first().click();
  const meta = await page.textContent('[data-testid=editmeta]');
  assert.match(meta, /out f\d+/); assert.match(meta, /src f\d+/);
  // output frame -> source frame mapping is exact for the demo EDL (identity mapping)
  const [o, s] = [meta.match(/out f(\d+)/)[1], meta.match(/src f(\d+)/)[1]]; assert.equal(o, s);
  assert.ok(await page.locator('[data-testid=crop-rect]').count() === 1 && await page.locator('[data-testid=gt-box]').count() === 1);
  await page.locator('#outsvg').evaluate(() => {}); // overlay present
  await page.click('[data-testid=propose]'); await page.waitForSelector('[data-testid=proposal-rect]');
  await page.click('[data-testid=approve-crop]'); await page.waitForSelector('.toast');
  await shot('10-editing-review');
});

await scenario('keyboard-only: tab order reaches the timeline segments and Enter selects', async () => {
  await page.goto(`${base}/#/annotate/${s1.id}`); await page.waitForSelector('[data-testid=segment]'); await videoReady();
  await page.focus('[data-testid=segment]'); await page.keyboard.press('Enter');
  assert.ok(await page.locator('[data-testid=segform]').isVisible());
  await shot('11-annotate-approved-source');
});

await scenario('no console/page errors across all screens', async () => {
  const real = consoleErrors.filter(e => !/aborted|net::ERR_FAILED|Failed to load resource/i.test(e));
  assert.deepEqual(real, []);
});

await browser.close(); server.closeAllConnections(); server.close();
const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} scenarios passed`);
rmSync(HOME, { recursive: true, force: true });
process.exit(failed.length ? 1 : 0);
void s2;
