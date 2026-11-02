// Cloud catalog in a real browser: existing videos in an (in-memory) R2 bucket are listed, opened in place, viewed with
// seeking, annotated, saved and restored after closing the program. The bucket is verified to be untouched.
//   node tests/e2e/cloud.mjs
import { createRequire } from 'node:module';
import path from 'node:path';
import { mkdirSync, rmSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createContext } from '../../server/context.mjs';
import { createApp } from '../../server/app.mjs';
import { CloudBucket, waitForProxies } from '../../server/cloud.mjs';
import { makeVideo } from '../../scripts/synthetic.mjs';
import { startS3Stub } from '../s3stub.mjs';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = process.env.SHOTS_DIR ?? path.resolve(here, '../../../docs/annotation-studio/screenshots');
const HOME = path.resolve(here, '../../.e2e-cloud-home'), VID = path.resolve(here, '../../.e2e-cloud-vid');
for (const d of [HOME, VID]) rmSync(d, { recursive: true, force: true });
mkdirSync(SHOTS, { recursive: true });
const sha = b => createHash('sha256').update(b).digest('hex'), md5 = b => createHash('md5').update(b).digest('hex');

const results = [];
async function scenario(name, fn) {
  const t = Date.now();
  try { await fn(); results.push({ name, ok: true, ms: Date.now() - t }); console.log(`  ok   ${name}`); }
  catch (e) { results.push({ name, ok: false, err: e.message }); console.log(`  FAIL ${name}\n       ${e.message.split('\n').slice(0, 5).join('\n       ')}`); }
}

// ---- an in-memory R2 with real (synthetic) videos in SportReel's layout ----
const stub = await startS3Stub({ bucket: 'sportreel' });
const clip = (n, y) => readFileSync(makeVideo(path.join(VID, `${n}.mp4`), { seconds: 5, w: 640, h: 360, y, tag: n }));
const KEYS = { A: 'raw/2026-10-06T17-37-55_1000000018.mp4', B: 'raw/2026-10-06T17-46-01_1000000018.mp4', C: 'raw/2026-10-12T09-00-00_1000000016.mp4' };
const files = { A: clip('A', 30), B: clip('B', 120), C: clip('C', 220) };
for (const k of Object.keys(KEYS)) stub.objects.set(KEYS[k], { data: files[k] });
stub.objects.set('processed/2026-09-01T08-00-00_old.mp4', { data: clip('L', 300) });
stub.objects.set('review/draft.mp4', { data: Buffer.from('derived output') });
mkdirSync(HOME, { recursive: true });
const metaFile = path.join(HOME, 'cloud-metadata.json');
writeFileSync(metaFile, JSON.stringify(Object.entries(KEYS).map(([n, k], i) => ({ id: `u${i}`, status: 'verified', storage_key: k, verified_size_bytes: files[n].length, content_sha256: sha(files[n]), created_at: `2026-10-0${i + 6}T10:00:00Z`, batch_id: 'b1' }))));
const snapshot = () => new Map([...stub.objects].map(([k, v]) => [k, md5(v.data)]));
const before = snapshot();

let ctx, server, base, browser, page;
const consoleErrors = [];
const cloud = () => new CloudBucket({ endpoint: stub.url, bucket: 'sportreel', accessKeyId: stub.accessKeyId, secretAccessKey: stub.secretAccessKey, retries: 0 });
async function boot() {
  ctx = createContext(HOME, { token: 'cloud-e2e', cloud: cloud() }); ctx.cloudMetadata = metaFile;
  server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch(); page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('pageerror', e => consoleErrors.push(e.message)); page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await page.goto(`${base}/?t=cloud-e2e`);
}
async function shutdown() { await browser.close(); server.closeAllConnections(); await new Promise(r => server.close(r)); ctx.db.close(); }
const shot = n => page.screenshot({ path: path.join(SHOTS, `cloud-${n}.png`) });
async function until(fn, timeout = 20000) { const end = Date.now() + timeout; while (Date.now() < end) { if (await page.evaluate(fn)) return; await page.waitForTimeout(100); } throw new Error(`timed out waiting for: ${fn}`); }
const videoReady = () => until(() => { const v = document.querySelector('#vid'); return !!v && v.readyState >= 2 && v.videoWidth > 0; });
const frameNum = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
const waitSaved = () => page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 8000 });

console.log('Annotation Studio — cloud catalog E2E');
await boot();

await scenario('1. catalog: sync lists the existing cloud videos (raw/ + legacy processed/), never review/', async () => {
  await page.goto(`${base}/#/cloud`); await page.waitForSelector('[data-testid=cloud-sync]');
  await page.click('[data-testid=cloud-sync]');
  await page.waitForSelector('[data-testid=cloud-row]');
  assert.equal(await page.locator('[data-testid=cloud-row]').count(), 4, '3 in raw/ + 1 legacy in processed/');
  assert.equal(await page.locator('[data-testid=cloud-row][data-key^="review/"]').count(), 0);
  assert.match(await page.textContent('[data-testid=cloud-row][data-key^="processed/"]'), /processed\//);
  assert.match(await page.textContent('[data-testid=cloud-row][data-key$="1000000016.mp4"]'), /זמין ב-raw/);
  await shot('01-catalog');
});

await scenario('2. open one for annotation: no re-upload, no full download; view + frame-exact seeking', async () => {
  await page.click(`[data-testid=cloud-row][data-key="${KEYS.B}"] [data-testid=cloud-open]`);
  await page.waitForSelector('[data-testid=workbench]', { timeout: 60000 }); await videoReady();
  assert.equal(await frameNum(), 0);
  assert.match(await page.textContent('#topbar'), /ענן/);
  for (let i = 0; i < 5; i++) await page.click('[data-testid=step-fwd]');
  assert.equal(await frameNum(), 5);
  await page.keyboard.press('Shift+ArrowRight'); assert.equal(await frameNum(), 15);
  assert.equal(Number((await page.evaluate(() => document.querySelector('#vid').duration)).toFixed(0)), 5, 'duration shown');
  assert.equal(await page.textContent('[data-testid=timecode]'), '00:00:15');
  await waitForProxy();
  await shot('02-annotate-cloud');
});
async function waitForProxy() { await waitForProxies(); await page.reload(); await page.waitForSelector('[data-testid=workbench]'); await videoReady(); assert.ok((await page.evaluate(() => document.querySelector('#vid').currentSrc)).endsWith('/proxy'), 'plays the frame-exact proxy once built'); }

await scenario('3. label an athlete + event; autosave; Ground Truth approval is blocked until identity is verified', async () => {
  await page.goto(`${base}/#/athletes`); await page.waitForSelector('[data-testid=add-athlete]');
  await page.fill('#newath', 'סינתטי'); await page.click('[data-testid=add-athlete]'); await page.waitForSelector('[data-testid=athlete-card]');
  const sid = ctx.db.prepare("select id from sources where provider='cloud-r2'").get().id;
  await page.goto(`${base}/#/annotate/${sid}`); await page.waitForSelector('[data-testid=workbench]'); await videoReady();
  await page.evaluate(() => document.querySelector('#vid').pause());
  await page.click('#ruler', { position: { x: 60, y: 10 } });
  await page.keyboard.press('i'); for (let i = 0; i < 30; i++) await page.keyboard.press('ArrowRight'); await page.keyboard.press('o');
  await page.waitForSelector('[data-testid=segment].sel');
  await page.keyboard.press('1'); await page.keyboard.press('e'); await waitSaved();
  await page.fill('#ap-reason', 'GT cloud'); await page.click('[data-testid=approve]');
  await page.waitForSelector('.toast.bad');
  assert.match(await page.textContent('.toast.bad'), /לא אומתה|SHA-256|אומתה/);
  assert.equal(ctx.db.prepare('select count(*) n from annotation_revisions').get().n, 0);
  await shot('03-unverified-blocked');
});

await scenario('4. verify identity (SHA-256 from the bucket bytes), then approve', async () => {
  await page.click('[data-testid=verify-cloud]');
  await page.waitForSelector('text=זהות אומתה', { timeout: 60000 }); await page.waitForSelector('[data-testid=workbench]');
  await page.waitForSelector('[data-testid=segment]');
  await page.click('[data-testid=segment]'); await page.fill('#ap-reason', 'GT cloud'); await page.check('[data-testid=ack]').catch(() => {});
  await page.click('[data-testid=approve]');
  await page.waitForSelector('[data-testid=revlist] li b');
  assert.equal(ctx.db.prepare('select count(*) n from annotation_revisions').get().n, 1);
  await shot('04-approved');
});

await scenario('5. close the program and reopen: catalog, source, labels and approval are all still there', async () => {
  await shutdown(); await boot();
  await page.goto(`${base}/#/cloud`); await page.waitForSelector('[data-testid=cloud-row]');
  assert.equal(await page.locator('[data-testid=cloud-row]').count(), 4);
  assert.equal(await page.locator('[data-testid=cloud-annotate]').count(), 1, 'the opened video offers "continue"');
  await page.click('[data-testid=cloud-annotate]'); await page.waitForSelector('[data-testid=workbench]'); await videoReady();
  assert.equal(await page.locator('[data-testid=segment]').count(), 1);
  assert.equal(await page.locator('[data-testid=revlist] li').count(), 1);
  await shot('05-reopened');
});

await scenario('6. the bucket was never modified, only GET/HEAD were issued, and no secret reached the browser', async () => {
  assert.deepEqual(snapshot(), before, 'every object byte-identical');
  assert.equal(stub.log.filter(l => l.method !== 'GET' && l.method !== 'HEAD').length, 0);
  const html = await page.content();
  assert.ok(!html.includes(stub.secretAccessKey) && !html.includes(stub.accessKeyId));
  assert.ok(!(await page.evaluate(() => JSON.stringify([...Object.entries(localStorage)]))).includes(stub.secretAccessKey));
});

await scenario('no console/page errors', async () => {
  assert.deepEqual(consoleErrors.filter(e => !/aborted|net::ERR_FAILED|Failed to load resource/i.test(e)), []);
});

await shutdown(); stub.close();
const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} cloud scenarios passed`);
for (const d of [HOME, VID]) rmSync(d, { recursive: true, force: true });
process.exit(failed.length ? 1 : 0);
