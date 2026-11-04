// Precision Studio V2 operator journey in a real browser (Playwright/Chromium), at 1440x900 and 1920x1080.
// Drives the UI only through visible controls (mouse + keyboard), never through private JS state:
//   library -> "assign to surfer" on a video with no events -> surfer workspace -> open workbench -> I/O event ->
//   new event starts usability=uncertain/decision=uncertain -> choose performer -> draw a box (drawing != verifying) ->
//   verify on the exact frame -> drag the box (verification invalidated) -> re-verify -> mark wrong surfer (approval
//   blocked) -> fix -> reload (persistence) -> undo/redo -> RTL/layout checks. Synthetic media only.
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
const HOME = path.resolve(here, '../../.e2e-home-v2');
mkdirSync(SHOTS, { recursive: true });
const results = [];
async function scenario(name, fn) {
  const t = Date.now();
  try { await fn(); results.push({ name, ok: true, ms: Date.now() - t }); console.log(`  ok   ${name}`); }
  catch (e) { results.push({ name, ok: false, err: e.message }); console.log(`  FAIL ${name}\n       ${e.message.split('\n').slice(0, 6).join('\n       ')}`); }
}

const { ctx } = await seed(HOME, { quiet: true });
const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const errors = [];
const db = ctx.db;
const srcByName = n => db.prepare('select * from sources where display_name=?').get(n);

for (const vp of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }]) {
  const tag = `${vp.width}x${vp.height}`;
  const page = await browser.newPage({ viewport: vp });
  page.on('pageerror', e => errors.push(`${tag}: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error') errors.push(`${tag}: ${m.text()}`); });
  const shot = n => page.screenshot({ path: path.join(SHOTS, `v2-${tag}-${n}.png`) });
  async function until(fn, arg, timeout = 15000) {
    const end = Date.now() + timeout;
    while (Date.now() < end) { if (await page.evaluate(fn, arg)) return; await page.waitForTimeout(100); }
    throw new Error(`timed out waiting for: ${fn}`);
  }
  const saved = () => page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 10000 });
  const frameNum = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
  const draft = id => JSON.parse(db.prepare('select content from annotation_drafts where source_id=?').get(id)?.content ?? 'null');
  const target = tag === '1440x900' ? 'DJI_0414.mp4' : 'DJI_0415.mp4';   // a video with no events, per viewport
  const src = srcByName(target);
  const surfer = `גולש בדיקה ${tag}`;
  console.log(`V2 operator journey @ ${tag}`);
  await page.goto(`${base}/?t=demo-token`);
  await page.goto(`${base}/#/library`);

  await scenario(`${tag} layout: RTL, no horizontal scroll, library visible`, async () => {
    await page.waitForSelector('[data-testid=source-card]');
    assert.equal(await page.evaluate(() => document.documentElement.dir || getComputedStyle(document.body).direction), 'rtl');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'no horizontal page scroll');
    await shot('01-library');
  });

  await scenario(`${tag} assign a video with NO events to a new surfer from the library card`, async () => {
    const card = page.locator('[data-testid=source-card]', { hasText: target.replace('.mp4', '') });
    await card.locator('[data-testid=assign-owner-btn]').click();
    await page.fill('input[placeholder*="גולש"]', surfer).catch(() => {});
    const createBtn = page.locator('button', { hasText: 'צור גולש' }).first();
    await createBtn.click();
    await page.click('[data-testid=dlg-save-owner]');
    await page.waitForSelector(`[data-testid=owner-badge]:has-text("${surfer}")`, { timeout: 8000 }).catch(() => {});
    const row = db.prepare('select owner_athlete_id, owner_version from sources where id=?').get(src.id);
    const ath = db.prepare('select * from athletes where id=?').get(row.owner_athlete_id);
    assert.equal(ath?.label, surfer); assert.equal(row.owner_version, 1);
    assert.equal(db.prepare('select count(*) c from annotation_drafts where source_id=?').get(src.id).c, 0, 'no event/draft created by assignment');
    await shot('02-assigned');
  });

  await scenario(`${tag} surfer workspace lists the video with 0 events`, async () => {
    await page.goto(`${base}/#/athletes`);
    await page.waitForSelector('[data-testid=athlete-item]');
    await page.locator('[data-testid=athlete-item]', { hasText: surfer }).first().click();
    await page.waitForSelector('[data-testid=surfer-workspace]');
    await page.waitForSelector(`[data-testid=surfer-video-card]:has-text("${target.replace('.mp4', '')}")`, { timeout: 8000 });
    await shot('03-workspace');
  });

  await scenario(`${tag} workbench: I/O creates an event that starts uncertain/uncertain; performer picker works`, async () => {
    await page.goto(`${base}/#/annotate/${src.id}`);
    await page.waitForSelector('[data-testid=workbench]');
    await until(() => { const v = document.querySelector('#vid'); return !!v && v.readyState >= 2; });
    for (let i = 0; i < 2; i++) await page.keyboard.press('Shift+ArrowRight');           // frame 20
    await page.keyboard.press('i');
    for (let i = 0; i < 6; i++) await page.keyboard.press('Shift+ArrowRight');           // frame 80
    await page.keyboard.press('o');
    await page.waitForSelector('[data-testid=segform]');
    await saved();
    let d = draft(src.id);
    assert.equal(d.segments.length, 1);
    assert.equal(d.segments[0].usability, 'usable'); assert.equal(d.segments[0].decision, 'include');   // by exception: change only what is not OK
    // The performer select (previously threw: setSegmentAthlete was undefined).
    const ownerId = db.prepare('select owner_athlete_id from sources where id=?').get(src.id).owner_athlete_id;
    await page.selectOption('[data-testid=athlete-select]', ownerId);
    await saved();
    d = draft(src.id);
    assert.equal(d.segments[0].athlete_id, ownerId, 'performer chosen explicitly (owner is never auto-propagated)');
    await shot('04-event');
  });

  await scenario(`${tag} draw a box with the mouse: drawn != verified; verify on the exact frame; drag invalidates`, async () => {
    const seg = draft(src.id).segments[0];
    while (await frameNum() < seg.start_frame + 10) await page.keyboard.press('ArrowRight');
    const f = await frameNum();
    await page.keyboard.press('b');                                                      // box tool
    const ov = await page.locator('#ov').boundingBox();
    await page.mouse.move(ov.x + ov.width * 0.30, ov.y + ov.height * 0.30);
    await page.mouse.down(); await page.mouse.move(ov.x + ov.width * 0.40, ov.y + ov.height * 0.45, { steps: 5 }); await page.mouse.up();
    await saved();
    let d = draft(src.id);
    const kf = d.keyframes.find(k => k.frame === f);
    assert.ok(kf, `keyframe stored at the exact current frame ${f}`);
    assert.equal(kf.verification_status, 'unreviewed');
    assert.ok(Math.abs(kf.bbox.x - 0.30) < 0.02 && Math.abs(kf.bbox.w - 0.10) < 0.02, 'normalized source coordinates');
    await page.keyboard.press('b');
    await page.click('[data-testid=insp-tab-box]');
    await page.waitForSelector('[data-testid=insp-panel-box]');
    assert.match(await page.textContent('[data-testid=box-verify-banner]'), /טרם נבדק|ציור ≠ אימות/);
    await page.click('[data-testid=verify-box-confirm]');
    await saved();
    d = draft(src.id);
    const v = d.box_verifications.filter(x => x.frame === f).at(-1);
    assert.equal(v.status, 'verified_correct'); assert.deepEqual(v.bbox, kf.bbox); assert.equal(v.athlete_id, d.segments[0].athlete_id);
    await until(() => document.querySelector('[data-testid=track-qa-status]')?.dataset.status === 'partially_checked');
    await shot('05-verified-one-frame');
    // Drag the box: geometry changes -> the earlier decision no longer counts.
    const r = await page.locator('[data-testid=bbox]').first().boundingBox();
    await page.mouse.move(r.x + r.width / 2, r.y + r.height / 2); await page.mouse.down();
    await page.mouse.move(r.x + r.width / 2 + 40, r.y + r.height / 2 + 10, { steps: 5 }); await page.mouse.up();
    await saved();
    d = draft(src.id);
    const last = d.box_verifications.filter(x => x.frame === f).at(-1);
    assert.equal(last.status, 'unreviewed'); assert.equal(last.invalidation, 'geometry_changed');
    assert.equal(d.box_verifications.filter(x => x.frame === f).length >= 2, true, 'history kept');
    await page.click('[data-testid=verify-box-confirm]');
    await saved();
    assert.equal(draft(src.id).box_verifications.filter(x => x.frame === f).at(-1).status, 'verified_correct');
  });

  await scenario(`${tag} wrong surfer marked -> approval blocked; correction path visible`, async () => {
    await page.click('[data-testid=verify-box-wrong]');
    await saved();
    await until(() => document.querySelector('[data-testid=track-qa-status]')?.dataset.status === 'needs_correction');
    await page.click('[data-testid=insp-tab-event]');
    await page.waitForSelector('[data-testid=approval-blocking]');
    assert.equal(await page.isDisabled('[data-testid=approve]'), true);
    assert.equal(await page.getAttribute('[data-testid=wf-state]', 'data-state'), 'needs_review');
    await shot('06-blocked');
    // fix: re-verify the (correct) box
    await page.click('[data-testid=insp-tab-box]');
    await page.click('[data-testid=verify-box-confirm]');
    await saved();
    await page.click('[data-testid=insp-tab-event]');
    await until(() => !document.querySelector('[data-testid=approval-blocking]'));
  });

  await scenario(`${tag} undo/redo with keyboard; reload restores exactly what was saved`, async () => {
    const before = JSON.stringify(draft(src.id));
    await page.keyboard.press('Control+z'); await saved();
    assert.notEqual(JSON.stringify(draft(src.id)), before);
    await page.keyboard.press('Control+Shift+z'); await saved();
    assert.equal(JSON.stringify(draft(src.id).segments), JSON.parse(JSON.stringify(JSON.parse(before).segments)) && JSON.stringify(JSON.parse(before).segments));
    await page.reload();
    await page.waitForSelector('[data-testid=segform]');                                   // event pre-selected on open
    await page.waitForSelector('[data-testid=states-panel]');
    assert.match(await page.textContent('[data-testid=st-owner]'), new RegExp(surfer));
    assert.match(await page.textContent('[data-testid=st-gt]'), /לא אושר/);
    await shot('07-reopened-states');
  });

  await scenario(`${tag} active decisions then approval with the real button; approval never marks frames verified`, async () => {
    // usability + decision through the visible form controls
    await page.locator('[data-testid=segform] button', { hasText: 'כן, שימושי' }).first().click();
    await page.keyboard.press('e');                                                      // include
    await saved();
    await page.waitForSelector('[data-testid=approve]:not([disabled])');
    await page.click('[data-testid=approve]');
    await until(() => document.querySelector('[data-testid=wf-state]')?.dataset.state === 'approved', undefined, 10000).catch(() => {});
    const rev = db.prepare('select * from annotation_revisions where source_id=? order by seq desc limit 1').get(src.id);
    assert.ok(rev, 'immutable revision created');
    const st = await (await fetch(`${base}/api/sources/${src.id}/states`, { headers: { authorization: 'Bearer demo-token' } })).json();
    assert.equal(st.ground_truth.approved, true);
    assert.equal(st.box_qa.per_segment[0].status === 'verified_in_checked_range', false, 'one frame never verifies a track');
    await shot('08-approved');
  });

  await scenario(`${tag} inspector, player and timeline visible together; no overflow in the workbench`, async () => {
    for (const sel of ['#vid', '#insp', '#tl', '[data-testid=savepill]']) {
      const b = await page.locator(sel).first().boundingBox();
      assert.ok(b && b.width > 0 && b.height > 0 && b.x >= -1 && b.x + b.width <= vp.width + 1, `${sel} on screen`);
    }
    const vid = await page.locator('#vid').boundingBox();
    assert.ok(vid.width >= vp.width * 0.45, `central player is large (${Math.round(vid.width)}px)`);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  });
  await scenario(`${tag} key moment outside the event is refused; a stuck local draft (old bug) is repaired and saves`, async () => {
    await page.reload();
    await page.waitForSelector('[data-testid=segform]');
    for (let i = 0; i < 12 && await frameNum() > 0; i++) await page.keyboard.press('Shift+ArrowLeft');   // playhead to frame 0, outside [20,80)
    assert.equal(await frameNum(), 0);
    if (!await page.locator('[data-testid=event-more]').evaluate(d => d.open)) await page.click('[data-testid=event-more] summary');
    await page.locator('[data-testid=segform] button', { hasText: 'תחילת רכיבה' }).first().click();
    await page.waitForTimeout(900);
    assert.equal(draft(src.id).segments[0].key_moments?.takeoff_frame, undefined, 'out-of-range key moment never enters the draft');
    // The exact state from the operator report: a pending local draft holding takeoff_frame=0 for an event [20,80).
    const row = db.prepare('select version, content from annotation_drafts where source_id=?').get(src.id);
    const bad = JSON.parse(row.content); bad.segments[0].key_moments = { takeoff_frame: 0 };
    await page.evaluate(([k, v]) => localStorage.setItem(k, v), [`studio.pending.${src.id}`, JSON.stringify({ base: row.version, content: bad, at: Date.now() })]);
    await page.reload();
    await page.waitForSelector('[data-testid=segform]');
    await until(() => /תוקן אוטומטית/.test(document.querySelector('[data-testid=inspector-banner]')?.textContent ?? ''));
    await saved();
    const d = draft(src.id);
    assert.equal(d.segments[0].key_moments?.takeoff_frame, undefined, 'repaired before save');
    assert.match(await page.textContent('[data-testid=inspector-banner]'), /תוקן אוטומטית/);
    assert.equal(await page.evaluate(k => localStorage.getItem(k), `studio.pending.${src.id}`), null, 'local queue drained');
  });
  await page.close();
}

await scenario('no page/console errors during the V2 journeys', async () => {
  const real = errors.filter(e => !/aborted|net::ERR_FAILED|Failed to load resource/i.test(e));
  assert.deepEqual(real, []);
});

await browser.close(); server.closeAllConnections(); server.close();
const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} V2 scenarios passed`);
rmSync(HOME, { recursive: true, force: true });
process.exit(failed.length ? 1 : 0);
