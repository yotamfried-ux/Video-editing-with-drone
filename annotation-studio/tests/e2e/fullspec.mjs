// FULL_SPEC screens in a real browser: independent set (blind workbench), agreement report, physical-action linking,
// identity merge. Synthetic media only.
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
const HOME = path.resolve(here, '../../.e2e-home-fullspec');
mkdirSync(SHOTS, { recursive: true });
const results = [];
async function scenario(name, fn) {
  try { await fn(); results.push({ ok: true }); console.log(`  ok   ${name}`); }
  catch (e) { results.push({ ok: false }); console.log(`  FAIL ${name}\n       ${e.message.split('\n').slice(0, 6).join('\n       ')}`); }
}
const { ctx, s1 } = await seed(HOME, { quiet: true });
const db = ctx.db;
const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', e => errors.push(e.message));
const saved = () => page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 10000 });
await page.goto(`${base}/?t=demo-token`);
let setId;

await scenario('create a blind re-annotation set from the Sets screen and add a source', async () => {
  await page.goto(`${base}/#/sets`); await page.waitForSelector('[data-testid=sets-table]');
  await page.fill('[data-testid=set-annotator]', 'ann-2');
  await page.click('[data-testid=set-create]');
  await page.waitForSelector('[data-testid=sets-table] tr:has-text("ann-2")');
  setId = db.prepare("select id from annotation_sets where annotator_id='ann-2'").get().id;
  await page.click(`[data-set="${setId}"] [data-testid=set-open]`);
  await page.selectOption('dialog[open] select[multiple]', s1.id);
  await page.click('[data-testid=set-add-sources]');
  await page.waitForTimeout(300);
  assert.equal(db.prepare('select count(*) n from set_assignments where set_id=?').get(setId).n, 1);
  await page.screenshot({ path: path.join(SHOTS, 'fullspec-01-sets.png') });
});

await scenario('blind workbench: starts EMPTY although the primary has approved events; saves to its own stream only', async () => {
  const primaryBefore = db.prepare('select content from annotation_drafts where source_id=?').get(s1.id).content;
  await page.goto(`${base}/#/annotate/${s1.id}?set=${setId}`);
  await page.waitForSelector('[data-testid=set-panel]');
  assert.equal(await page.locator('[data-testid=segment]').count(), 0, 'no primary events visible');
  assert.equal(await page.locator('[data-testid=approve]').count(), 0, 'no primary approval in a set');
  await page.keyboard.press('i'); for (let i = 0; i < 20; i++) await page.keyboard.press('ArrowRight'); await page.keyboard.press('o');
  await saved();
  const a = db.prepare('select draft_content, queue_status from set_assignments where set_id=?').get(setId);
  assert.equal(JSON.parse(a.draft_content).segments.length, 1); assert.equal(a.queue_status, 'in_progress');
  assert.equal(db.prepare('select content from annotation_drafts where source_id=?').get(s1.id).content, primaryBefore, 'primary untouched');
  await page.click('[data-testid=usability-uncertain]'); await saved();
  await page.click('[data-testid=set-complete]');
  await page.waitForSelector('[data-testid=set-done]');
  await page.screenshot({ path: path.join(SHOTS, 'fullspec-02-blind-workbench.png') });
});

await scenario('submit the set, then the agreement report against the primary is available', async () => {
  await page.goto(`${base}/#/sets`); await page.waitForSelector('[data-testid=sets-table]');
  await page.click(`[data-set="${setId}"] [data-testid=set-submit]`);
  await page.waitForSelector(`[data-set="${setId}"]:has-text("הוגש")`);
  await page.selectOption('#agree-a', 'primary'); await page.selectOption('#agree-b', setId);
  await page.click('[data-testid=agreement-run]');
  await page.waitForSelector('[data-testid=agreement-report] table');
  assert.match(await page.textContent('[data-testid=agreement-report]'), /מקורות משותפים/);
  await page.screenshot({ path: path.join(SHOTS, 'fullspec-03-agreement.png') });
});

await scenario('physical action: create from an event, visible as linked', async () => {
  await page.goto(`${base}/#/annotate/${s1.id}`); await page.waitForSelector('[data-testid=segform]');
  await page.waitForSelector('[data-testid=action-create]');
  await page.click('[data-testid=action-create]');
  await page.waitForSelector('[data-testid=action-linked]');
  assert.equal(db.prepare('select count(*) n from action_occurrences where source_id=?').get(s1.id).n, 1);
});

await scenario('identity merge recorded on the surfers screen (append-only)', async () => {
  await page.goto(`${base}/#/athletes`); await page.waitForSelector('[data-testid=person-lineage]');
  await page.click('[data-testid=person-lineage] summary');
  const ids = db.prepare('select id from athletes order by created_at').all().map(r => r.id);
  await page.selectOption('[data-testid=lin-from]', ids[1]); await page.selectOption('[data-testid=lin-to]', ids[0]);
  await page.fill('[data-testid=lin-reason]', 'same surfer');
  page.once('dialog', d => d.accept());
  await page.click('[data-testid=lin-add]');
  await page.waitForTimeout(500);
  assert.equal(db.prepare('select count(*) n from person_lineage_relations').get().n, 1);
});

await scenario('no page errors', async () => { assert.deepEqual(errors, []); });
await browser.close(); server.closeAllConnections(); server.close();
const failed = results.filter(r => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} full-spec scenarios passed`);
rmSync(HOME, { recursive: true, force: true });
process.exit(failed ? 1 : 0);
