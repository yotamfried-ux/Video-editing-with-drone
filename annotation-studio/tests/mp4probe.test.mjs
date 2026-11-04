// The dependency-free MP4 probe used by the hosted Studio must agree with ffprobe on the fields the Studio stores —
// for faststart and moov-at-end files, H.264 and HEVC 10-bit 4K, NTSC rates (30000/1001, 60000/1001) and rotation —
// while reading only a tiny part of the file. Non-MP4 input is refused with NOT_VIDEO.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { tmp } from './helpers.mjs';
import { probe } from '../server/media.mjs';
import { probeMp4 } from '../server/mp4probe.mjs';

const dir = tmp('mp4p-');
function make(name, args) {
  const f = path.join(dir, name);
  const r = spawnSync('ffmpeg', ['-y', '-v', 'error', ...args, f], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(r.stderr.slice(-400));
  return f;
}
function reader(file) {
  const buf = readFileSync(file); let bytes = 0;
  const read = async (s, e) => { const b = buf.subarray(s, e + 1); bytes += b.length; return Buffer.from(b); };
  return { read, size: buf.length, bytesRead: () => bytes };
}
const CASES = [
  ['h264_faststart.mp4', ['-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=30000/1001:d=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-movflags', '+faststart']],
  ['h264_moov_end_5994.mp4', ['-f', 'lavfi', '-i', 'testsrc2=s=1280x720:r=60000/1001:d=2', '-f', 'lavfi', '-i', 'sine=d=2', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest']],
  ['hevc10_4k_moov_end.mp4', ['-f', 'lavfi', '-i', 'testsrc2=s=3840x2160:r=60000/1001:d=1', '-c:v', 'libx265', '-preset', 'ultrafast', '-crf', '35', '-pix_fmt', 'yuv420p10le', '-tag:v', 'hvc1', '-x265-params', 'log-level=error']],
  ['rotated90.mp4', ['-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=25:d=1', '-c:v', 'libx264', '-preset', 'ultrafast', '-metadata:s:v', 'rotate=90']],
  ['dated.mov', ['-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=24:d=1', '-c:v', 'libx264', '-preset', 'ultrafast', '-metadata', 'creation_time=2026-07-24T10:37:51Z']],
];

for (const [name, args] of CASES) {
  test(`mp4 probe matches ffprobe: ${name}`, { timeout: 120000 }, async () => {
    const f = make(name, args);
    const want = await probe(f);
    const r = reader(f);
    const got = await probeMp4(r.read, r.size);
    for (const k of ['codec', 'width', 'height', 'rotation', 'frame_count']) assert.equal(got[k], want[k], `${k}: ${got[k]} vs ffprobe ${want[k]}`);
    assert.equal(got.fps_num / got.fps_den, want.fps_num / want.fps_den, `fps ${got.fps_num}/${got.fps_den} vs ${want.fps_num}/${want.fps_den}`);
    assert.ok(Math.abs(got.duration_ms - want.duration_ms) <= 60, `duration ${got.duration_ms} vs ${want.duration_ms}`);
    if (want.captured_at) assert.equal(got.captured_at.slice(0, 19), want.captured_at.slice(0, 19));
    assert.ok(r.bytesRead() < Math.max(200000, r.size * 0.2), `read only the headers (${r.bytesRead()} of ${r.size} bytes)`);
  });
}

test('mp4 probe refuses non-MP4 and truncated files with NOT_VIDEO', async () => {
  const junk = path.join(dir, 'junk.mp4'); writeFileSync(junk, Buffer.from('this is not a video file at all, just text'));
  const r = reader(junk);
  await assert.rejects(probeMp4(r.read, r.size), e => e.code === 'NOT_VIDEO');
  const f = make('cut.mp4', ['-f', 'lavfi', '-i', 'testsrc2=s=320x240:r=24:d=1', '-c:v', 'libx264', '-preset', 'ultrafast']);   // moov at end
  const whole = readFileSync(f); const cut = path.join(dir, 'cut_trunc.mp4'); writeFileSync(cut, whole.subarray(0, Math.floor(whole.length / 2)));
  const t = reader(cut);
  await assert.rejects(probeMp4(t.read, t.size), e => e.code === 'NOT_VIDEO');
});
