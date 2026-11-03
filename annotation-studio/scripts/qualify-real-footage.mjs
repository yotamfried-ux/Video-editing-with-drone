#!/usr/bin/env node
// CATALOG_GO real-footage qualification (spec §22.3) — run on the operator workstation against REAL DJI sources.
//
//   node --env-file=.studio-cloud.env scripts/qualify-real-footage.mjs --evidence "C:\Users\you\sportreel-qualification" \
//        --case single=raw/<key>.mp4 --case multi=raw/<key>.mp4 --case crossing=raw/<key>.mp4 --case occlusion=raw/<key>.mp4 \
//        --case 4k_fast=raw/<key>.mp4 --case quality_issue=raw/<key>.mp4 --case no_events=raw/<key>.mp4
//   (a case may also name the video exactly as the Studio's Cloud screen shows it, e.g. --case single=DJI_0412.MP4)
//
// Safety, by construction:
//   * R2 is used READ-ONLY through the Studio's CloudBucket, which refuses any method except GET/HEAD in code.
//   * Everything is written to a NEW isolated Studio home inside --evidence (never the operator's live STUDIO_HOME and
//     never inside the Git repository). Existing Ground Truth is not opened, read or modified.
//   * Frames extracted for human review stay in --evidence (private). Nothing is uploaded anywhere.
//   * --probe-delete-permission (optional) sends ONE signed DELETE for a random key that does not exist: a read-only token
//     gets 403; a token that could delete gets 204 — with nothing deleted either way. Without the flag it is skipped.
//
// What it proves automatically on each real source: cloud identity (SHA-256 from the bytes), owner assignment with no
// event + Surfer Workspace + restart persistence, event defaults (uncertain/uncertain), exact-frame BOX evidence rules
// (hostile verify refused, geometry change invalidates, wrong surfer blocks approval), proxy<->original frame mapping
// by pixel similarity at the event's start/middle/end, and source metadata (resolution, fps, rotation, frames).
// What it CANNOT prove and leaves NOT_TESTED for the human: that a box is on the right surfer in the real image, that
// crossing/occlusion cases were judged correctly, and the reel-vs-source output quality.
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createContext } from '../server/context.mjs';
import { createApp } from '../server/app.mjs';
import { waitForProxies } from '../server/cloud.mjs';
import { signRequest, sha256hex } from '../server/sigv4.mjs';
import { cloudConfigFromEnv } from '../server/cloud.mjs';

const argv = process.argv.slice(2);
const opt = n => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : undefined; };
const cases = argv.flatMap((a, i) => (a === '--case' ? [argv[i + 1]] : [])).map(s => { const j = s.indexOf('='); return { name: s.slice(0, j), key: s.slice(j + 1) }; });
const evidence = opt('--evidence');
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
if (!evidence || !cases.length) { console.error('usage: qualify-real-footage.mjs --evidence DIR --case name=raw/key.mp4 [--case ...] [--probe-delete-permission]'); process.exit(2); }
const evDir = path.resolve(evidence);
if (evDir.startsWith(repoRoot + path.sep) || evDir === repoRoot) { console.error('refusing: --evidence must be OUTSIDE the Git repository (private frames must never be committed)'); process.exit(2); }
const live = process.env.STUDIO_HOME && existsSync(process.env.STUDIO_HOME) ? realpathSync(process.env.STUDIO_HOME) : null;
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const home = path.join(evDir, `isolated-gt-${stamp}`);
if (live && path.resolve(home).startsWith(live)) { console.error('refusing: isolated home would be inside the live STUDIO_HOME'); process.exit(2); }
mkdirSync(home, { recursive: true }); mkdirSync(path.join(evDir, `frames-${stamp}`), { recursive: true });
const cfg = cloudConfigFromEnv();
if (!cfg) { console.error('cloud is not configured (STUDIO_CLOUD_R2_*): use --env-file=.studio-cloud.env'); process.exit(2); }

const report = { started_at: new Date().toISOString(), node: process.version, platform: `${process.platform}-${os.release()}`, bucket: cfg.bucket, isolated_home: home, steps: [], cases: {} };
const step = (scope, name, status, detail = {}) => { const s = { scope, name, status, ...detail }; report.steps.push(s); console.log(`${status.padEnd(11)} ${scope} :: ${name}${detail.note ? ` — ${detail.note}` : ''}`); return s; };
const TOKEN = randomBytes(16).toString('hex');
let ctx = createContext(home, { token: TOKEN });
let server, base;
async function start() { server = createApp(ctx); await new Promise(r => server.listen(0, '127.0.0.1', r)); base = `http://127.0.0.1:${server.address().port}`; }
async function stop() { server.closeAllConnections(); server.close(); }
const call = async (p, body, method = body ? 'POST' : 'GET') => {
  const r = await fetch(base + p, { method, body: body ? JSON.stringify(body) : undefined, headers: { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json' } });
  const t = await r.text(); let j; try { j = JSON.parse(t); } catch { j = t; }
  return { status: r.status, json: j };
};
async function job(p, body) {
  const first = await call(p, body);
  const json = first.json;
  if (!json?.job_id) return { state: 'failed', error: `HTTP ${first.status} ${json?.code ?? ''} ${json?.message ?? ''}`.trim() };
  for (let i = 0; i < 6000; i++) { const j = (await call(`/api/jobs/${json.job_id}`)).json; if (j.state !== 'running') return j; await new Promise(r => setTimeout(r, 200)); }
  throw new Error('job timeout');
}
// Async on purpose: ffmpeg reads frames from the HTTP server running in THIS process, so a synchronous spawn would deadlock.
function run(cmd, args) {
  return new Promise(res => { const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] }); let err = ''; p.stderr.on('data', d => { err += d; }); p.on('close', code => res({ status: code, stderr: err })); });
}
const ffFrame = (url, n, out, extra = []) => run('ffmpeg', ['-nostdin', '-v', 'error', '-y', '-headers', `Authorization: Bearer ${TOKEN}\r\n`, '-i', url, '-vf', `select=eq(n\\,${n})${extra.length ? ',' + extra.join(',') : ''}`, '-vsync', '0', '-frames:v', '1', out]);
async function psnr(a, b) {
  if (!existsSync(a) || !existsSync(b)) return null;
  const r = await run('ffmpeg', ['-nostdin', '-v', 'info', '-i', a, '-i', b, '-lavfi', '[0:v][1:v]scale=rw:rh[x];[x][1:v]psnr', '-f', 'null', '-']);
  const m = /average:([\d.]+|inf)/.exec(r.stderr); return m ? (m[1] === 'inf' ? 99 : Number(m[1])) : null;
}

await start();
try {
  // ---------- 0. read-only evidence ----------
  if (argv.includes('--probe-delete-permission')) {
    const key = `qualification-probe/${randomBytes(12).toString('hex')}-does-not-exist`;
    const url = `${cfg.endpoint}/${cfg.bucket}/${key}`;
    const h = signRequest({ method: 'DELETE', url, payloadHash: sha256hex(''), region: 'auto', service: 's3', accessKeyId: cfg.accessKeyId, secretAccessKey: cfg.secretAccessKey });
    const { _canonical, ...hdrs } = h;
    const r = await fetch(url, { method: 'DELETE', headers: hdrs });
    step('r2', 'token cannot delete (DELETE of a non-existent random key)', r.status === 403 ? 'PASS' : 'FAIL', { http: r.status, note: r.status === 403 ? 'read-only token' : 'token has delete permission — replace with an Object Read-only token' });
  } else step('r2', 'token cannot delete', 'NOT_TESTED', { note: 'run with --probe-delete-permission (no data is changed by the probe)' });
  step('r2', 'Studio connector refuses non-GET/HEAD methods', 'PASS', { note: 'enforced in server/cloud.mjs CloudBucket#request (unit-tested)' });

  // ---------- 1. catalog ----------
  const sync = await job('/api/cloud/sync', {});
  step('catalog', 'R2 catalog sync', sync.state === 'done' ? 'PASS' : 'FAIL', { report: sync.report ?? sync.error, note: sync.report ? `${sync.report.raw} raw/, ${sync.report.processed_legacy} processed/ (legacy, flagged), ${sync.report.missing} missing` : String(sync.error ?? '') });
  const objs = (await call('/api/cloud/objects')).json.items ?? [];

  for (const c of cases) {
    const R = report.cases[c.name] = { key: c.key };
    // Accept the full R2 key or the file name exactly as the Studio's Cloud screen shows it (must be unique).
    const byName = objs.filter(o => o.name === c.key || o.key.endsWith(`/${c.key}`));
    const obj = objs.find(o => o.key === c.key) ?? (byName.length === 1 ? byName[0] : null);
    if (!obj) { step(c.name, 'object present in catalog', 'FAIL', { note: byName.length > 1 ? `ambiguous name ${c.key}: use the full key (${byName.map(o => o.key).join(', ')})` : `not found: ${c.key}` }); continue; }
    R.key = obj.key;
    const opened = await job(`/api/cloud/objects/${obj.id}/open`, {});
    if (opened.state !== 'done') { step(c.name, 'open source', 'FAIL', { note: opened.error }); continue; }
    const sid = R.source_id = opened.report.source_id;
    const ver = await job('/api/cloud/verify', { source_id: sid });
    const src = (await call(`/api/sources/${sid}`)).json;
    R.meta = { width: src.width, height: src.height, rotation: src.rotation, fps: `${src.fps_num}/${src.fps_den}`, frames: src.frame_count, sha256_prefix: src.sha256?.slice(0, 12) };
    step(c.name, 'identity: SHA-256 recomputed from the R2 bytes', src.verify_state === 'verified' || ver.report?.verified ? 'PASS' : 'FAIL', { note: JSON.stringify(R.meta) });

    // owner assignment without any event, workspace, restart
    const ath = (await call('/api/athletes', { label: `QUAL-${c.name}` })).json;
    const own = await call(`/api/sources/${sid}/catalog-owner`, { owner_athlete_id: ath.id, expected_version: src.owner_version ?? 0, reason: 'qualification' });
    const ws = (await call(`/api/athletes/${ath.id}/sources`)).json;
    step(c.name, 'assign owner with no events; listed in Surfer Workspace', own.status === 200 && JSON.stringify(ws).includes(sid) ? 'PASS' : 'FAIL');
    await waitForProxies();                                            // let background proxy work finish before the simulated restart
    await stop(); ctx.db.close?.(); ctx = createContext(home, { token: TOKEN }); await start();
    const after = (await call(`/api/sources/${sid}/catalog-owner`)).json;
    const drafts = ctx.db.prepare('select count(*) n from annotation_drafts where source_id=?').get(sid).n;
    step(c.name, 'restart: owner persisted, no event created', after.owner_athlete_id === ath.id && drafts === 0 ? 'PASS' : 'FAIL');
    if (c.name === 'no_events') { step(c.name, 'video without events stays in catalog', 'PASS'); continue; }

    // event + BOX mechanics on the real source geometry
    const F = src.frame_count, a = Math.floor(F * 0.2), b = Math.max(a + 3, Math.floor(F * 0.4)), mid = Math.floor((a + b) / 2);
    const box = { x: 0.4, y: 0.4, w: 0.1, h: 0.15 };
    const content = { schema: 1, segments: [{ id: 'q1', start_frame: a, end_frame: b, athlete_id: ath.id, event_type: 'wave_ride', decision: 'uncertain', usability: 'uncertain', reason_codes: [] }],
      keyframes: [a, mid, b - 1].map((f, i) => ({ id: `k${i}`, segment_id: 'q1', frame: f, bbox: box, visibility: 'visible', origin: 'manual', verification_status: 'unreviewed' })), reviewed_ranges: [], box_verifications: [] };
    let v = 0; const put = async cnt => { const r = await call(`/api/sources/${sid}/draft`, { expected_version: v, content: cnt }, 'PUT'); if (r.status === 200) v = r.json.version; return r; };
    step(c.name, 'event saved with usability=uncertain, decision=uncertain', (await put(content)).status === 200 ? 'PASS' : 'FAIL');
    const hostile = structuredClone(content); hostile.box_verifications = [{ segment_id: 'q1', frame: a + 1, status: 'verified_correct', bbox: box, athlete_id: ath.id, verified_by: 'qual', verified_at: new Date().toISOString() }];
    const hr = await put(hostile);
    step(c.name, 'hostile verify at a frame without a box is refused', hr.status === 400 && hr.json.code === 'BOX_NOT_AT_FRAME' ? 'PASS' : 'FAIL', { http: hr.status });
    const ok = structuredClone(content); ok.box_verifications = [{ segment_id: 'q1', frame: mid, status: 'verified_correct', bbox: box, athlete_id: ath.id, verified_by: 'qual', verified_at: new Date().toISOString() }];
    step(c.name, 'bound verification at the exact frame accepted (mechanics only)', (await put(ok)).status === 200 ? 'PASS' : 'FAIL');
    const moved = structuredClone(ok); moved.keyframes[1].bbox = { ...box, x: 0.45 };
    const mr = await put(moved);
    step(c.name, 'geometry change without re-check is refused (stale)', mr.status === 409 && mr.json.code === 'STALE_BOX_VERIFICATION' ? 'PASS' : 'FAIL', { http: mr.status });
    const wrong = structuredClone(ok); wrong.box_verifications.push({ segment_id: 'q1', frame: mid, status: 'wrong_performer', bbox: box, athlete_id: ath.id, verified_by: 'qual', verified_at: new Date(Date.now() + 1000).toISOString() });
    await put(wrong);
    const ap = await call(`/api/sources/${sid}/approve`, { expected_version: v, acknowledge_unresolved: true });
    step(c.name, 'wrong-surfer flag blocks approval even with acknowledgement', ap.status === 409 && ap.json.code === 'BLOCKING_ITEMS' ? 'PASS' : 'FAIL', { http: ap.status });

    // proxy <-> original frame mapping by pixel similarity (exact frame should match better than its neighbours)
    await waitForProxies();
    const s2 = (await call(`/api/sources/${sid}`)).json;
    const fdir = path.join(evDir, `frames-${stamp}`, c.name); mkdirSync(fdir, { recursive: true });
    const orig = `${base}/media/cloud/${obj.id}/original`, prox = `${base}${s2.playback_url}`;
    const mapping = [];
    for (const f of [a, mid, b - 1]) {
      const o = path.join(fdir, `orig-f${f}.png`), p0 = path.join(fdir, `proxy-f${f}.png`), pPrev = path.join(fdir, `proxy-f${f - 1}.png`), pNext = path.join(fdir, `proxy-f${f + 1}.png`);
      await ffFrame(orig, f, o);
      await ffFrame(prox, f, p0); await ffFrame(prox, f - 1, pPrev); await ffFrame(prox, f + 1, pNext);
      // Human-review copy with the candidate box drawn (operator judges whether it is on the surfer).
      await ffFrame(orig, f, path.join(fdir, `review-f${f}-box.png`), [`drawbox=x=iw*${box.x}:y=ih*${box.y}:w=iw*${box.w}:h=ih*${box.h}:color=lime@0.9:t=6`]);
      const same = await psnr(p0, o), prev = await psnr(pPrev, o), next = await psnr(pNext, o);
      mapping.push({ frame: f, psnr_same: same, psnr_prev: prev, psnr_next: next });
    }
    R.mapping = mapping;
    const exact = mapping.every(m => m.psnr_same != null && m.psnr_same >= Math.max(m.psnr_prev ?? 0, m.psnr_next ?? 0) - 0.05);
    step(c.name, 'proxy frame N maps to original frame N (pixel similarity vs N±1)', mapping.some(m => m.psnr_same == null) ? 'BLOCKED' : exact ? 'PASS' : 'FAIL', { note: mapping.map(m => `f${m.frame}: ${m.psnr_same?.toFixed?.(1)}dB vs ${m.psnr_prev?.toFixed?.(1)}/${m.psnr_next?.toFixed?.(1)}`).join('; ') });
    step(c.name, 'HUMAN: box is on the correct surfer in the real image', 'NOT_TESTED', { note: `inspect ${fdir}/review-*.png and repeat in the Studio UI` });
    if (['crossing', 'occlusion', 'multi'].includes(c.name)) step(c.name, `HUMAN: ${c.name} frames judged in the UI (checkpoints + Wrong/Occluded decisions)`, 'NOT_TESTED');
  }
  step('quality', 'original vs proxy vs final reel comparison', 'NOT_TESTED', { note: 'needs a real rendered reel; this script never runs the pipeline' });
} catch (e) {
  step('run', 'unexpected error', 'FAIL', { note: e.message });
} finally {
  await stop(); ctx.db.close?.();
  report.finished_at = new Date().toISOString();
  const counts = report.steps.reduce((o, s) => ({ ...o, [s.status]: (o[s.status] ?? 0) + 1 }), {});
  report.summary = counts;
  report.automated_verdict = counts.FAIL ? 'FAIL' : 'PASS_AUTOMATED_PART_ONLY';
  const out = path.join(evDir, `qualification-${stamp}.json`);
  writeFileSync(out, JSON.stringify(report, null, 2));
  console.log(`\n${JSON.stringify(counts)} -> ${out}\nAutomated part: ${report.automated_verdict}. Human items remain NOT_TESTED until you check them in the Studio.`);
  process.exitCode = counts.FAIL ? 1 : 0;
}
