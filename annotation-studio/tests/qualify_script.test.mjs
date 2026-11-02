// The operator's real-footage qualification script, executed end-to-end against an S3-compatible stub holding real
// (synthetic) H.264 media. Proves the script's automated checks work and that it never writes to the bucket; the real
// DJI run happens on the operator workstation (R2 read-only credentials are not available to CI).
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { makeVideo, tmp, BACKEND } from './helpers.mjs';
import { startS3Stub } from './s3stub.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const script = path.resolve(here, '../scripts/qualify-real-footage.mjs');

test('qualify-real-footage.mjs: automated CATALOG_GO checks pass on real media; bucket never written; refuses evidence inside the repo', { skip: BACKEND === 'postgres' ? 'script runs on the local SQLite workstation backend' : false, timeout: 600000 }, async () => {
  const stub = await startS3Stub({ bucket: 'sportreel' });
  try {
    const dir = tmp('qvid-');
    stub.objects.set('raw/single.mp4', { data: readFileSync(makeVideo(path.join(dir, 'single.mp4'), { seconds: 3, w: 640, h: 360, tag: 's' })) });
    stub.objects.set('raw/empty.mp4', { data: readFileSync(makeVideo(path.join(dir, 'empty.mp4'), { seconds: 2, w: 640, h: 360, y: 20, tag: 'e' })) });
    const env = { ...process.env, STUDIO_HOME: '', STUDIO_DB_URL: '', STUDIO_CLOUD_R2_BUCKET: 'sportreel', STUDIO_CLOUD_R2_ENDPOINT: stub.url, STUDIO_CLOUD_R2_ACCESS_KEY_ID: stub.accessKeyId, STUDIO_CLOUD_R2_SECRET_ACCESS_KEY: stub.secretAccessKey };
    const run = args => new Promise(res => {
      const p = spawn(process.execPath, ['--disable-warning=ExperimentalWarning', script, ...args], { env });
      let out = ''; p.stdout.on('data', d => { out += d; }); p.stderr.on('data', d => { out += d; });
      p.on('close', code => res({ code, out }));
    });
    // evidence inside the repository is refused (private frames must never be committed)
    const bad = await run(['--evidence', path.resolve(here, '..', 'qual-evidence'), '--case', 'single=raw/single.mp4']);
    assert.equal(bad.code, 2); assert.match(bad.out, /OUTSIDE the Git repository/);
    const ev = tmp('qual-evidence-');
    const r = await run(['--evidence', ev, '--case', 'single=raw/single.mp4', '--case', 'no_events=raw/empty.mp4']);
    const reportFile = readdirSync(ev).find(n => n.startsWith('qualification-') && n.endsWith('.json'));
    assert.ok(reportFile, r.out);
    const rep = JSON.parse(readFileSync(path.join(ev, reportFile), 'utf8'));
    const fails = rep.steps.filter(s => s.status === 'FAIL');
    assert.deepEqual(fails, [], r.out);
    const passed = rep.steps.filter(s => s.status === 'PASS').map(s => `${s.scope}:${s.name}`);
    for (const must of ['single:identity: SHA-256 recomputed from the R2 bytes', 'single:restart: owner persisted, no event created', 'single:hostile verify at a frame without a box is refused',
      'single:geometry change without re-check is refused (stale)', 'single:wrong-surfer flag blocks approval even with acknowledgement', 'single:proxy frame N maps to original frame N (pixel similarity vs N±1)',
      'no_events:assign owner with no events; listed in Surfer Workspace']) assert.ok(passed.includes(must), `missing PASS: ${must}`);
    // human judgements are never auto-passed
    assert.ok(rep.steps.some(s => s.name.startsWith('HUMAN:') && s.status === 'NOT_TESTED'));
    assert.equal(rep.automated_verdict, 'PASS_AUTOMATED_PART_ONLY');
    assert.ok(existsSync(path.join(ev, readdirSync(ev).find(n => n.startsWith('frames-')), 'single')), 'review frames kept privately in the evidence folder');
    // read-only: the script never sent a write to the bucket
    assert.deepEqual(stub.log.filter(e => !['GET', 'HEAD'].includes(e.method)), []);
  } finally { stub.close(); }
});
