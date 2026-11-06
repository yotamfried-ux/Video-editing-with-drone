// End-to-end simulation through the real Studio UI on a synthetic drone surf clip (scripts/sim-surf.py):
// the operator draws ONE box, the Studio tracks the athlete over the whole video; wherever the box is off the surfer,
// the "operator" drags it onto the surfer once (a correction), and the Studio re-tracks before and after.
// Reports accuracy after each correction. Exit code 1 if the video is not fully on-target within MAX_FIX corrections.
//   python3 scripts/sim-surf.py /tmp/surf && node tests/sim/surf-ui.mjs /tmp/surf [anchorFrame]
// The box must always hold the whole athlete + board, also while the camera zooms (--zoomrate 0.2: closing in fast) and
// the surfer turns and comes closer, without becoming much looser than drawn.
import path from 'node:path'; import { mkdirSync, copyFileSync, readFileSync, rmSync } from 'node:fs'; import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createContext } from '../../server/context.mjs';
import { reconcile } from '../../server/ingest.mjs';
import * as A from '../../server/annotations.mjs';
import { createApp } from '../../server/app.mjs';
const require = createRequire(import.meta.url); const { chromium } = require('playwright');
const here = path.dirname(fileURLToPath(import.meta.url));
const [clip, anchorArg = '30'] = process.argv.slice(2);
const MAX_FIX = 3, meta = JSON.parse(readFileSync(clip + '.json')), T = meta.truth;
const home = path.resolve(here, '../../.sim-home'); rmSync(home, { recursive: true, force: true });
const ctx = createContext(home, { token: 'demo-token' });
const raw = path.join(home, 'operational', 'raw'); mkdirSync(raw, { recursive: true });
copyFileSync(clip + '.mp4', path.join(raw, 'SIM_SURF.mp4'));
await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }], batchLabel: 'sim' });
const src = ctx.db.prepare('select * from sources').get();
const ath = A.createAthlete(ctx.db, 'גולש מדומה');
const c = A.emptyContent();
c.segments.push({ id: 'ride', start_frame: 0, end_frame: src.frame_count, athlete_id: ath.id, event_type: 'wave_ride', decision: 'include', usability: 'usable', reason_codes: [], key_moments: {} });
A.saveDraft(ctx.db, src.id, 0, c);
const server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const b = await chromium.launch(); const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
const errors = []; page.on('pageerror', e => errors.push(e.message));
await page.goto(`${base}/?t=demo-token`);
await page.goto(`${base}/#/annotate/${src.id}`); await page.waitForSelector('[data-testid=segform]');
const draft = () => JSON.parse(ctx.db.prepare('select content from annotation_drafts where source_id=?').get(src.id).content);
const fr = async () => Number((await page.textContent('[data-testid=framenum]')).match(/frame (\d+)/)[1]);
const go = async n => { await page.evaluate(n => { const v = document.querySelector('#vid'); v.pause(); }, n); while (await fr() !== n) { const d = n - await fr(); await page.keyboard.press(Math.abs(d) >= 10 ? (d > 0 ? 'Shift+ArrowRight' : 'Shift+ArrowLeft') : (d > 0 ? 'ArrowRight' : 'ArrowLeft')); } };
const ov = async () => page.locator('#ov').boundingBox();
const pad = (g, p) => ({ x: g.x - g.w * p, y: g.y - g.h * p, w: g.w * (1 + 2 * p), h: g.h * (1 + 2 * p) });
const idle = async () => { await page.waitForTimeout(400); await page.waitForFunction(() => { const h = document.querySelector('#hudtrack'); return h && h.style.display === 'none'; }, undefined, { timeout: 240000 }); await page.waitForSelector('[data-testid=savepill][data-state=saved]', { timeout: 30000 }); };
const err = p => { const t = T[p.frame]; return Math.hypot((p.bbox.x + p.bbox.w / 2 - t.x - t.w / 2) * meta.w, (p.bbox.y + p.bbox.h / 2 - t.y - t.h / 2) * meta.h) / Math.hypot(t.w * meta.w, t.h * meta.h); };
// size: as the camera zooms and the athlete turns / comes closer, the box follows the athlete + equipment. Holding them
// whole comes first, so a box drawn around a surfer lying flat stays that wide when they stand up and grows in height:
// it may get looser than drawn, but not without bound (loose = box size / truth size, relative to the drawn box's).
const sizeOf = b => Math.sqrt(b.w * meta.w * b.h * meta.h);
const loose = pts => { const a = pts.find(p => p.origin === 'manual') ?? pts[0]; const r0 = sizeOf(a.bbox) / sizeOf(T[a.frame]);
  return Math.max(...pts.map(p => sizeOf(p.bbox) / sizeOf(T[p.frame]) / r0)); };
const MAX_LOOSE = 2.5;
// containment: the box must hold the whole athlete AND their equipment (surfer + board): share of the truth box inside it
const cover = p => { const t = T[p.frame], b = p.bbox, ix = Math.max(0, Math.min(b.x + b.w, t.x + t.w) - Math.max(b.x, t.x)), iy = Math.max(0, Math.min(b.y + b.h, t.y + t.h) - Math.max(b.y, t.y)); return ix * iy / (t.w * t.h); };
// The box grows to hold the athlete + equipment only modestly (real footage: the colour blob also catches wake and foam,
// which made the box pump). A 90-degree turn plus 1.6x growth (this clip) is beyond that: the operator resizes once.
const MIN_COVER = 0.45;
// steadiness: the box must not pump in size from one sample to the next (live 0115: around each correction the height
// swung 0.28 -> 0.73 -> 0.33). Worst |log(area ratio)| between neighbouring samples.
const sizeStep = pts => Math.max(0, ...pts.slice(1).map((p, i) => Math.abs(Math.log((p.bbox.w * p.bbox.h) / (pts[i].bbox.w * pts[i].bbox.h)))));
const MAX_SIZE_STEP = 0.35;
const report = label => {
  const pts = draft().tracks?.[0]?.points ?? [];
  const bad = pts.filter(p => err(p) >= 0.5).map(p => p.frame);
  const fs = pts.map(p => p.frame);
  const r = { label, points: pts.length, from: Math.min(...fs), to: Math.max(...fs), offTarget: bad.length, firstBad: bad[0] ?? null, maxErr: +Math.max(...pts.map(err)).toFixed(2), maxLoose: +loose(pts).toFixed(2), maxSizeStep: +sizeStep(pts).toFixed(2), minCover: +Math.min(...pts.map(cover)).toFixed(2), worstCoverAt: pts.reduce((a, p) => cover(p) < cover(a) ? p : a, pts[0])?.frame };
  if (process.env.SIM_DUMP) console.log(pts.map(p => `${p.frame}:${(sizeOf(p.bbox) / sizeOf(T[p.frame])).toFixed(2)}/${err(p).toFixed(2)}/c${cover(p).toFixed(2)}`).join(" "));
  console.log(JSON.stringify(r)); return r;
};
// 1) the operator draws one (loose) box
const a0 = +anchorArg; await go(a0);
await page.keyboard.press('b');
let o = await ov(); const g = pad(T[a0], 0.3);
await page.mouse.move(o.x + g.x * o.width, o.y + g.y * o.height); await page.mouse.down();
await page.mouse.move(o.x + (g.x + g.w) * o.width, o.y + (g.y + g.h) * o.height, { steps: 6 }); await page.mouse.up();
await idle();
let r = report(`one box at f${a0}`), fixes = 0;
// 2) corrections: where the box is off the surfer, drag it onto the surfer (one drag per correction)
const last = src.frame_count - 1;
const drawAt = async f => {                       // "the tracker lost the athlete here": jump there and draw a box
  await go(f); await page.keyboard.press('b'); const o2 = await ov(), q = pad(T[f], 0.3);
  await page.mouse.move(o2.x + q.x * o2.width, o2.y + q.y * o2.height); await page.mouse.down();
  await page.mouse.move(o2.x + (q.x + q.w) * o2.width, o2.y + (q.y + q.h) * o2.height, { steps: 6 }); await page.mouse.up();
  await idle(); fixes++; r = report(`after drawing a box at f${f} (where tracking stopped)`);
};
while ((r.firstBad != null || r.from > 0 || r.to < last) && fixes < MAX_FIX) {
  if (r.firstBad == null) { await drawAt(r.from > 0 ? 0 : last); continue; }
  const f = r.firstBad; await go(f);
  const sel = await page.locator('[data-testid=track-box], [data-testid=bbox]').first(); const bb = await sel.boundingBox();
  o = await ov(); const t = T[f], want = { x: o.x + (t.x + t.w / 2) * o.width, y: o.y + (t.y + t.h / 2) * o.height };
  await page.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); await page.mouse.down();
  await page.mouse.move(want.x, want.y, { steps: 6 }); await page.mouse.up();
  await idle(); fixes++;
  r = report(`after correction ${fixes} at f${f}`);
}
await page.screenshot({ path: path.join(path.dirname(clip), 'sim-ui.png') });
const pass = r.offTarget === 0 && r.from === 0 && r.to === src.frame_count - 1 && r.maxLoose <= MAX_LOOSE && r.maxSizeStep <= MAX_SIZE_STEP && r.minCover >= MIN_COVER;
console.log(JSON.stringify({ result: pass ? 'PASS' : 'FAIL', corrections: fixes, pageErrors: errors }));
await b.close(); server.close();
process.exit(pass && !errors.length ? 0 : 1);
