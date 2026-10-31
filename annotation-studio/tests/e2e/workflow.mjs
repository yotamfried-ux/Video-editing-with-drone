// Full operator journey in a real browser against a real server and SYNTHETIC footage (no real data):
//   Import Video -> Sport Classification -> Athlete Annotation -> Event Annotation -> Ground Truth Save -> (close & reopen)
//   -> Pipeline Predictions Import -> EDL Import -> Evaluation -> Report -> Backup -> Restore.
//   node tests/e2e/workflow.mjs
import { createRequire } from 'node:module';
import path from 'node:path';
import { mkdirSync, rmSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createContext } from '../../server/context.mjs';
import { createApp } from '../../server/app.mjs';
import { makeVideo } from '../../scripts/synthetic.mjs';
import { runOffsiteBackup, verifyOffsite, restoreFromOffsite, backupStatus, BackupError } from '../../server/offsite.mjs';
import * as A from '../../server/annotations.mjs';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = process.env.SHOTS_DIR ?? path.resolve(here, '../../../docs/annotation-studio/screenshots');
const HOME = path.resolve(here, '../../.e2e-workflow-home');
const OPS = path.resolve(here, '../../.e2e-workflow-ops');
const BACKUP = path.resolve(here, '../../.e2e-workflow-backup');
const RESTORED = path.resolve(here, '../../.e2e-workflow-restored');
for (const d of [HOME, OPS, BACKUP, RESTORED]) rmSync(d, { recursive: true, force: true });
mkdirSync(SHOTS, { recursive: true });

const results = [];
async function scenario(name, fn) {
  const t = Date.now();
  try { await fn(); results.push({ name, ok: true, ms: Date.now() - t }); console.log(`  ok   ${name}`); }
  catch (e) { results.push({ name, ok: false, err: e.message }); console.log(`  FAIL ${name}\n       ${e.message.split('\n').slice(0, 5).join('\n       ')}`); }
}

// ---- synthetic footage: two real clips + one unclassified clip + an exact duplicate under another name ----
const raw = path.join(OPS, 'raw'); mkdirSync(raw, { recursive: true });
makeVideo(path.join(raw, 'surf_session_a.mp4'), { seconds: 6, w: 1280, h: 720, y: 70, tag: 'wf-surf' });
makeVideo(path.join(raw, 'football_match_b.mp4'), { seconds: 6, w: 1280, h: 720, y: 200, tag: 'wf-foot' });
makeVideo(path.join(raw, 'mystery_c.mp4'), { seconds: 6, w: 1280, h: 720, y: 330, tag: 'wf-unk' });
makeVideo(path.join(raw, 'surf_session_a_copy.mp4'), { seconds: 6, w: 1280, h: 720, y: 70, tag: 'wf-surf' });
const roots = [{ dir: raw, prefix: 'raw/' }];

let ctx, server, base, browser, page;
const consoleErrors = [];
async function boot() {
  ctx = createContext(HOME, { token: 'wf-token', roots });
  ctx.roots = roots;
  server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch();
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('pageerror', e => consoleErrors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await page.goto(`${base}/?t=wf-token`);
}
async function shutdown() {           // simulates closing the program: browser, HTTP server and database handle all go away
  await browser.close(); server.closeAllConnections(); await new Promise(r => server.close(r)); ctx.db.close();
}
const shot = n => page.screenshot({ path: path.join(SHOTS, `wf-${n}.png`) });
const waitSaved = () => page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 8000 });
async function until(fn, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await page.evaluate(fn)) return; await page.waitForTimeout(100); }
  throw new Error(`timed out waiting for: ${fn}`);
}
const videoReady = () => until(() => { const v = document.querySelector('#vid'); return !!v && v.readyState >= 2 && v.videoWidth > 0; });
const frameNum = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
const api = async (p, o = {}) => {
  const r = await fetch(`${base}${p}`, { method: o.method ?? 'GET', headers: { authorization: o.noauth ? '' : 'Bearer wf-token', 'content-type': 'application/json' }, body: o.body ? JSON.stringify(o.body) : undefined });
  return { status: r.status, body: await r.json().catch(() => null) };
};
const src = name => ctx.db.prepare('select * from sources where display_name=?').get(name);
const goAnnotate = async name => { await page.goto(`${base}/#/annotate/${src(name).id}`); await page.waitForSelector('[data-testid=workbench]'); await videoReady(); };
async function markSegment(len = 30) {
  await page.evaluate(() => document.querySelector('#vid').pause());
  await page.click('#ruler', { position: { x: 60, y: 10 } });
  const a = await frameNum();
  await page.keyboard.press('i');
  for (let i = 0; i < len; i++) await page.keyboard.press('ArrowRight');
  await page.keyboard.press('o');
  await page.waitForSelector('[data-testid=segment].sel');
  return a;
}

console.log('Annotation Studio — full workflow E2E');
await boot();

await scenario('1. Import Video: reconcile from the UI ingests 3 sources and detects the exact duplicate', async () => {
  await page.waitForSelector('text=עדיין אין סרטונים');
  await page.click('text=סנכרון קליטה');
  await page.waitForSelector('.toast:has-text("סנכרון הושלם")', { timeout: 60000 });
  assert.equal(Number(ctx.db.prepare('select count(*) n from sources').get().n), 3, '4 files, one byte-identical duplicate => 3 sources');
  assert.equal(Number(ctx.db.prepare('select count(*) n from upload_occurrences').get().n), 4, 'the duplicate is recorded as another occurrence');
  assert.ok(ctx.db.prepare("select count(*) n from sources where ingest_state='ready'").get().n >= 3);
  await page.reload(); await page.waitForSelector('[data-testid=source-card]');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 3);
  await shot('01-imported');
});

await scenario('2. Sport classification: unclassified queue, filter, bulk assign (confirmed), badges, audit', async () => {
  assert.equal(await page.locator('[data-testid=sport-badge]').filter({ hasText: 'לא מסווג' }).count(), 3, 'nothing is assumed to be surfing');
  assert.match(await page.textContent('[data-testid=unknown-count]'), /3/);
  await page.selectOption('select[aria-label=sport]', 'unknown');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 3);
  // bulk assign the whole queue to surfing, then correct the football clip individually
  await page.selectOption('[data-testid=bulk-sport]', 'surfing');
  await page.click('[data-testid=bulk-apply]');
  await page.waitForSelector('dialog[open]');
  await page.click('[data-testid=bulk-confirm]');
  await page.waitForSelector('.toast');
  await page.selectOption('select[aria-label=sport]', 'surfing');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 3);
  await page.selectOption('select[aria-label=sport]', 'unknown');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 0, 'queue is empty after bulk assign');
  await shot('02-bulk-classified');
  const log = ctx.db.prepare("select detail from audit_log where action='source_sport_set'").all();
  assert.equal(log.length, 3, 'every assignment is audited');
});

await scenario('3. Sport change on a source (football), with the confirmation step and cancel keeping the old value', async () => {
  await goAnnotate('football_match_b.mp4');
  await page.selectOption('[data-testid=source-sport]', 'football');
  await page.waitForSelector('[data-testid=source-sport]');
  await until(() => document.querySelector('[data-testid=source-sport]')?.value === 'football');
  assert.equal(src('football_match_b.mp4').primary_sport_id, 'football');
  // sport change on a source that has no approved revisions needs no extra dialog; mystery_c gets a cancelled change
  await goAnnotate('mystery_c.mp4');
  await page.selectOption('[data-testid=source-sport]', '');
  await page.waitForSelector('dialog[open]');
  await page.click('text=ביטול');
  await until(() => document.querySelector('[data-testid=source-sport]')?.value === 'surfing');
  assert.equal(src('mystery_c.mp4').primary_sport_id, 'surfing', 'cancel kept the previous sport');
});

let surfStart;
await scenario('4. Athlete + event annotation (surfing): create athlete, mark event, bbox, type from the sport taxonomy, autosave', async () => {
  await page.goto(`${base}/#/athletes`); await page.waitForSelector('[data-testid=add-athlete]');
  await page.fill('#newath', 'דנה (סינתטי)'); await page.click('[data-testid=add-athlete]'); await page.waitForSelector('[data-testid=athlete-card]');
  await goAnnotate('surf_session_a.mp4');
  surfStart = await markSegment(30);
  await page.keyboard.press('1');
  const types = await page.$$eval('[data-testid=event-type] option', os => os.map(o => o.value));
  assert.deepEqual(types.sort(), ['failed_takeoff', 'other', 'paddle_out', 'wave_ride', 'wipeout'], 'picker offers exactly the surfing taxonomy');
  await page.selectOption('[data-testid=event-type]', 'wave_ride');
  await page.keyboard.press('b');
  const ov = await page.locator('#ov').boundingBox();
  await page.mouse.move(ov.x + ov.width * 0.1, ov.y + ov.height * 0.2); await page.mouse.down();
  await page.mouse.move(ov.x + ov.width * 0.16, ov.y + ov.height * 0.34, { steps: 4 }); await page.mouse.up();
  await page.keyboard.press('b');
  await page.keyboard.press('e');
  await waitSaved();
  assert.equal(await page.locator('[data-testid=kflist] li').count(), 1);
  await shot('04-surf-annotated');
});

await scenario('5. Event annotation (football) uses ITS taxonomy; sport/event mismatch is blocked in UI and rejected by the server', async () => {
  await goAnnotate('football_match_b.mp4');
  const a = await markSegment(24);
  const types = await page.$$eval('[data-testid=event-type] option', os => os.map(o => o.value));
  assert.deepEqual(types.sort(), ['goal', 'other', 'pass', 'shot'], 'football taxonomy, not surfing');
  await page.selectOption('[data-testid=event-type]', 'goal');
  await page.keyboard.press('e');
  await waitSaved();
  // server-side rejection of a cross-sport event (independent of the UI)
  const d = (await api(`/api/sources/${src('football_match_b.mp4').id}/draft`)).body;
  const bad = structuredClone(d.content); bad.segments[0].event_type = 'wave_ride';
  const r = await api(`/api/sources/${src('football_match_b.mp4').id}/draft`, { method: 'PUT', body: { expected_version: d.version, content: bad } });
  assert.equal(r.status, 400); assert.equal(r.body.code, 'SPORT_EVENT_MISMATCH');
  // mixed-sport footage: override the sport of one segment; the picker follows
  await page.selectOption('[data-testid=seg-sport]', 'tennis');
  const t2 = await page.$$eval('[data-testid=event-type] option', os => os.map(o => o.value));
  assert.ok(t2.includes('serve') && !t2.includes('goal'));
  assert.ok(await page.locator('[data-testid=event-mismatch]').isVisible(), 'current event "goal" is flagged as not belonging to tennis');
  await page.selectOption('[data-testid=event-type]', 'serve');
  await waitSaved();
  assert.equal(await page.locator('[data-testid=event-mismatch]').count(), 0);
  await shot('05-football-mixed');
  void a;
});

await scenario('6. Reclassifying a draft warns, never deletes, remaps explicitly; approved history unaffected', async () => {
  // approve the surfing source first so history exists, then reclassify it as basketball through the UI
  await goAnnotate('surf_session_a.mp4');
  await page.click('[data-testid=segment]'); await page.waitForSelector('[data-testid=segform]');
  await page.fill('#ap-reason', 'GT v1'); await page.click('[data-testid=approve]');
  await page.waitForSelector('[data-testid=revlist] li b');
  const rev1 = ctx.db.prepare('select digest from annotation_revisions where source_id=?').get(src('surf_session_a.mp4').id).digest;
  await page.selectOption('[data-testid=source-sport]', 'basketball');
  await page.waitForSelector('dialog[open]'); await page.click('[data-testid=confirm-sport]');
  await page.waitForSelector('[data-testid=apply-remap]');
  assert.match(await page.textContent('dialog[open]'), /שום מקטע לא יימחק/);
  await page.selectOption('[data-testid=remap-wave_ride]', 'shot');
  await page.click('[data-testid=apply-remap]');
  await until(() => document.querySelector('[data-testid=source-sport]')?.value === 'basketball');
  await page.waitForSelector('[data-testid=segment]');
  assert.equal(await page.locator('[data-testid=segment]').count(), 1, 'segment kept');
  assert.equal(JSON.parse(ctx.db.prepare('select content from annotation_drafts where source_id=?').get(src('surf_session_a.mp4').id).content).segments[0].event_type, 'shot');
  assert.equal(ctx.db.prepare('select digest from annotation_revisions where source_id=?').get(src('surf_session_a.mp4').id).digest, rev1, 'approved revision untouched');
  // put it back to surfing (explicit remap again) and approve v2 so the evaluation below has surfing GT
  await page.selectOption('[data-testid=source-sport]', 'surfing');
  await page.click('[data-testid=confirm-sport]');
  await page.waitForSelector('[data-testid=apply-remap]'); await page.selectOption('[data-testid=remap-shot]', 'wave_ride'); await page.click('[data-testid=apply-remap]');
  await until(() => document.querySelector('[data-testid=source-sport]')?.value === 'surfing');
  await page.click('[data-testid=segment]'); await page.waitForSelector('[data-testid=segform]');
  await page.fill('#f-notes', 'גל מלא'); await page.locator('#f-notes').blur(); await waitSaved();   // a real content change => a new revision (identical content is deliberately a no-op)
  await page.fill('#ap-reason', 'GT v2'); await page.click('[data-testid=approve]');
  await until(() => document.querySelectorAll('[data-testid=revlist] li').length === 2);
  assert.equal(Number(ctx.db.prepare('select count(*) n from annotation_revisions where source_id=?').get(src('surf_session_a.mp4').id).n), 2);
  // the football/tennis source gets approved too (mixed sport)
  await goAnnotate('football_match_b.mp4'); await page.click('[data-testid=segment]'); await page.fill('#ap-reason', 'GT football');
  await page.check('[data-testid=ack]');      // no athlete assigned to the included event => explicit acknowledgement is required
  await page.click('[data-testid=approve]');
  await page.waitForSelector('[data-testid=revlist] li b');
  await shot('06-approved');
});

await scenario('7. Settings: add a new sport + event type with required attribute, with no code change', async () => {
  await page.goto(`${base}/#/settings`); await page.waitForSelector('[data-testid=sport-card]');
  await page.fill('#ns-id', 'volleyball'); await page.fill('#ns-he', 'כדורעף'); await page.fill('#ns-en', 'Volleyball'); await page.click('[data-testid=add-sport]');
  await page.waitForSelector('[data-sport=volleyball]');
  await page.fill('#et-key-volleyball', 'spike'); await page.fill('#et-he-volleyball', 'הנחתה'); await page.fill('#et-en-volleyball', 'Spike'); await page.fill('#et-req-volleyball', 'rotation');
  await page.click('[data-testid=add-event-volleyball]');
  await page.waitForSelector('[data-sport=volleyball] [data-event=spike]');
  assert.match(await page.textContent('[data-sport=volleyball]'), /v2/);
  await page.fill('#ns-id', 'Bad Id'); await page.fill('#ns-he', 'x'); await page.fill('#ns-en', 'x'); await page.click('[data-testid=add-sport]');
  await page.waitForSelector('.toast.bad');
  await shot('07-settings');
});

await scenario('8. CLOSE the program and reopen: sports, athletes, segments, bbox and approvals are all still there', async () => {
  const before = {
    segs: JSON.stringify(A.getDraft(ctx.db, src('surf_session_a.mp4').id).content),
    revs: ctx.db.prepare('select count(*) n from annotation_revisions').get().n,
  };
  await shutdown(); await boot();
  await page.goto(`${base}/#/library`); await page.waitForSelector('[data-testid=source-card]');
  assert.equal(await page.locator('[data-testid=source-card]').count(), 3);
  assert.equal(await page.locator('[data-testid=sport-badge]').filter({ hasText: 'גלישה' }).count(), 2, 'surf_session_a + mystery_c');
  assert.equal(await page.locator('[data-testid=sport-badge]').filter({ hasText: 'כדורגל' }).count(), 1);
  assert.equal(JSON.stringify(A.getDraft(ctx.db, src('surf_session_a.mp4').id).content), before.segs, 'draft content identical');
  assert.equal(ctx.db.prepare('select count(*) n from annotation_revisions').get().n, before.revs);
  await goAnnotate('surf_session_a.mp4');
  assert.equal(await page.locator('[data-testid=segment]').count(), 1);
  assert.equal(await page.inputValue('[data-testid=source-sport]'), 'surfing');
  assert.equal(await page.locator('[data-testid=revlist] li').count(), 2);
  await page.goto(`${base}/#/settings`); await page.waitForSelector('[data-sport=volleyball]');
  await shot('08-reopened');
});

let ds, predId;
await scenario('9. Pipeline Predictions Import (predictions/v1) + EDL Import, then frozen dataset', async () => {
  const surf = src('surf_session_a.mp4'), foot = src('football_match_b.mp4');
  const sdraft = (await api(`/api/sources/${surf.id}/draft`)).body.content.segments[0];
  const fdraft = (await api(`/api/sources/${foot.id}/draft`)).body.content.segments[0];
  const pv1 = { schema: 'predictions/v1', run_id: 'wf-run-1', pipeline_commit: 'c'.repeat(40), digest: 'wfdigest', sources: [
    { source_sha256: surf.sha256, sport_id: 'surfing', events: [
      { candidate_id: 'c1', decision: 'selected', start_frame: sdraft.start_frame + 2, end_frame: sdraft.end_frame - 2, event_type: 'wave_ride', athlete_key: 'T1', score: 0.9 },
      { candidate_id: 'c2', decision: 'selected', start_frame: 120, end_frame: 150, event_type: 'wave_ride', athlete_key: 'T1', score: 0.4 }] },
    { source_sha256: foot.sha256, sport_id: 'football', events: [
      { candidate_id: 'c3', decision: 'selected', start_frame: fdraft.start_frame, end_frame: fdraft.end_frame, event_type: 'goal', athlete_key: 'T9', score: 0.8 }] }] };
  const p = await api('/api/imports/predictions', { method: 'POST', body: pv1 });
  assert.equal(p.status, 201, JSON.stringify(p.body)); predId = p.body.id;
  const bad = await api('/api/imports/predictions', { method: 'POST', body: { ...pv1, run_id: 'x', pipeline_commit: 'unknown' } });
  assert.equal(bad.status, 400, 'traceability is mandatory: unknown commit rejected');
  const edl = { schema: 'edl/v1', output_id: 'wf-out-1', run_id: 'wf-run-1', source_sha256: surf.sha256, source: { width: 1280, height: 720 }, output: { width: 360, height: 640, fps: 30 },
    mode: 'tracked_crop', rotation: 0, shots: [{ out_start: 0, out_end: 30, src_start: sdraft.start_frame, speed: 1, crop_start: { cx: 180, cy: 360, w: 360, h: 640 } }] };
  const e = await api('/api/imports/edl', { method: 'POST', body: { edl } });
  assert.equal(e.status, 201, JSON.stringify(e.body)); assert.deepEqual(e.body.unresolved_sources, []);
  const dup = await api('/api/imports/edl', { method: 'POST', body: { edl } });
  assert.equal(dup.body.duplicate, true, 're-import is idempotent');
  const unk = await api('/api/imports/edl', { method: 'POST', body: { edl: { ...edl, output_id: 'wf-out-2', source_sha256: 'f'.repeat(64) } } });
  assert.equal(unk.status, 201); assert.equal(unk.body.unresolved_sources.length, 1, 'unknown source is reported, never silently mapped');
  // freeze everything into the held-out split so the UI-triggered evaluation has data
  const f = await api('/api/datasets', { method: 'POST', body: { name: 'wf-GT', source_ids: [surf.id, foot.id], policy: { seed: 'wf', ratios: { train: 0, validation: 0, test: 1 } } } });
  assert.equal(f.status, 201, JSON.stringify(f.body)); ds = f.body;
});

await scenario('10. Evaluation + Report in the UI: sport-separated, no cross-sport matching, deterministic', async () => {
  await page.goto(`${base}/#/evaluations`); await page.waitForSelector('[data-testid=run-eval]');
  await page.click('[data-testid=run-eval]');
  await page.waitForSelector('[data-testid=by-sport]');
  const rows = await page.$$eval('[data-testid=by-sport] tbody tr', trs => Object.fromEntries(trs.map(tr => [tr.dataset.sport, [...tr.children].map(td => td.textContent)])));
  assert.deepEqual(Object.keys(rows).sort(), ['football', 'surfing', 'tennis']);
  assert.equal(rows.surfing[3], '1', 'surfing: 1 matched'); assert.equal(rows.surfing[2], '2', 'surfing: both predictions counted'); assert.equal(rows.surfing[5], '0', 'a prediction outside any reviewed range is reported as unreviewed, never as a false positive');
  assert.equal(rows.tennis[1], '1', 'tennis GT exists'); assert.equal(rows.tennis[3], '0', 'the football-declared prediction can NOT match the tennis GT');
  await shot('10-eval-report');
  const a = await api('/api/evaluations', { method: 'POST', body: { dataset_id: ds.id, prediction_id: predId } });
  const b = await api('/api/evaluations', { method: 'POST', body: { dataset_id: ds.id, prediction_id: predId } });
  const ra = (await api(`/api/evaluations/${a.body.id}`)).body, rb = (await api(`/api/evaluations/${b.body.id}`)).body;
  assert.equal(ra.digest, rb.digest, 'same inputs => identical report digest');
});

await scenario('11. Editing quality of the final reel: tracked-crop EDL is scored; contain-first EDL is never penalised for centring', async () => {
  const surf = src('surf_session_a.mp4');
  const o = (await api('/api/outputs')).body.items.find(x => x.output_id === 'wf-out-1');
  await page.goto(`${base}/#/editing/${o.id}`); await page.waitForSelector('[data-testid=editmeta], .banner, h1');
  const tracked = (await api('/api/editing/evaluate', { method: 'POST', body: { edl_id: o.id } })).body.report;
  assert.ok(tracked.evaluator_version && tracked.centering, 'tracked-crop reel has a centring evaluation');
  // contain-first (SportReel default): the full 16:9 frame letterboxed in 9:16 — correct by policy, must not be scored as a crop failure
  const edl = { schema: 'edl/v1', output_id: 'wf-out-contain', run_id: 'wf-run-1', source_sha256: surf.sha256, source: { width: 1280, height: 720 }, output: { width: 1080, height: 1920, fps: 30 },
    mode: 'contain', rotation: 0, shots: [{ out_start: 0, out_end: 30, src_start: 5, speed: 1, crop_start: { cx: 640, cy: 360, w: 1280, h: 720 } }] };
  const imp = await api('/api/imports/edl', { method: 'POST', body: { edl } }); assert.equal(imp.status, 201, JSON.stringify(imp.body));
  const outs = (await api('/api/outputs')).body.items; const c = outs.find(x => x.output_id === 'wf-out-contain');
  const rep = (await api('/api/editing/evaluate', { method: 'POST', body: { edl_id: c.id } })).body.report;
  assert.equal(rep.centering.scored_frames, 0, 'contain frames are not scored against centre');
  assert.match(rep.centering.note, /contain/);
  await shot('11-editing');
});

await scenario('12. Errors and accidental-deletion protection', async () => {
  assert.equal((await api('/api/sources', { noauth: true })).status, 401, 'no token => 401');
  assert.equal((await api(`/api/sources/${src('surf_session_a.mp4').id}`, { method: 'DELETE' })).status, 404, 'there is no delete endpoint for sources');
  assert.equal((await api('/api/datasets/x', { method: 'DELETE' })).status, 404);
  assert.throws(() => ctx.db.prepare('delete from sources').run(), /PROTECTED/);
  assert.throws(() => ctx.db.prepare('delete from annotation_revisions').run(), /IMMUTABLE/);
  assert.throws(() => ctx.db.prepare('delete from sports').run(), /PROTECTED/);
  assert.throws(() => ctx.db.prepare("update annotation_revisions set author='x'").run(), /IMMUTABLE/);
  const conflict = await api(`/api/sources/${src('mystery_c.mp4').id}/draft`, { method: 'PUT', body: { expected_version: 99, content: { schema: 1, segments: [], keyframes: [], reviewed_ranges: [] } } });
  assert.equal(conflict.status, 409); assert.equal(conflict.body.code, 'VERSION_CONFLICT');
  assert.equal((await api(`/api/sources/${src('mystery_c.mp4').id}/sport`, { method: 'PATCH', body: { sport_id: 'curling' } })).status, 404);
  const invalid = await api(`/api/sources/${src('mystery_c.mp4').id}/draft`, { method: 'PUT', body: { expected_version: 0, content: { schema: 1, segments: [{ id: 'q', start_frame: 10, end_frame: 5, event_type: 'wave_ride', decision: 'include' }], keyframes: [], reviewed_ranges: [] } } });
  assert.equal(invalid.body.code, 'INVALID_INTERVAL');
  // original bytes are untouched by everything above
  const s = src('surf_session_a.mp4');
  assert.equal(await ctx.archive.size(s.archive_key), s.byte_size, 'archived original has its original size');
});

await scenario('13. Backup & restore drill: independent copy, integrity verified, same-device refused, restored library is complete', async () => {
  await assert.rejects(runOffsiteBackup(ctx, BACKUP), e => e instanceof BackupError && e.code === 'BACKUP_SAME_DEVICE', 'real st_dev check: a folder next to the live data is NOT a backup');
  // The sandbox has a single filesystem, so the "other disk" is simulated for the copy only (the refusal above is the real check).
  const otherDisk = { deviceOf: p => (String(p).startsWith(HOME) ? 1 : 2) };
  const r = await runOffsiteBackup(ctx, BACKUP, { ...otherDisk, scope: 'all' });
  assert.equal(r.ok, true); assert.equal(r.copied, 3);
  const v = await verifyOffsite(BACKUP); assert.equal(v.ok, true, JSON.stringify(v));
  assert.equal(backupStatus(ctx.db).state, 'ok');
  // restore into a brand-new home and compare ground truth
  const fresh = createContext(RESTORED, { token: 'r-token' });
  const rr = await restoreFromOffsite(fresh, BACKUP);
  assert.ok(rr.ok !== false, JSON.stringify(rr));
  assert.equal(Number(fresh.db.prepare('select count(*) n from annotation_revisions').get().n), Number(ctx.db.prepare('select count(*) n from annotation_revisions').get().n));
  assert.equal(Number(fresh.db.prepare('select count(*) n from sources').get().n), 3);
  assert.equal(JSON.stringify(A.getDraft(fresh.db, src('surf_session_a.mp4').id).content), JSON.stringify(A.getDraft(ctx.db, src('surf_session_a.mp4').id).content), 'restored annotations are byte-identical');
  assert.ok(fresh.db.prepare('select count(*) n from sports').get().n >= 5, 'taxonomy restored');
  for (const s of fresh.db.prepare('select * from sources').all()) assert.equal(s.ingest_state, 'ready', 'restored footage verified by hash');
  fresh.db.close();
  assert.ok(readdirSync(BACKUP).length > 0);
  await page.goto(`${base}/#/library`); await page.waitForSelector('[data-testid=source-card]');
  assert.equal(await page.locator('[data-testid=backup-banner]').count(), 0, 'banner disappears once a verified backup exists');
});

await scenario('no console/page errors across the workflow', async () => {
  const real = consoleErrors.filter(e => !/aborted|net::ERR_FAILED|Failed to load resource/i.test(e));
  assert.deepEqual(real, []);
});

await shutdown();
const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} workflow scenarios passed`);
for (const d of [HOME, OPS, BACKUP, RESTORED]) rmSync(d, { recursive: true, force: true });
process.exit(failed.length ? 1 : 0);
