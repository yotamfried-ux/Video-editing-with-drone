import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createContext } from '../server/context.mjs';

/** Synthetic clip: a red 40x40 "surfer" at x=2n, y=`y` on blue. Bbox truth is analytic. */
export function makeVideo(file, { seconds = 4, fps = 30, w = 320, h = 180, y = 70, tag = 'a', ext } = {}) {
  mkdirSync(path.dirname(file), { recursive: true });
  const fc = `color=c=blue:s=${w}x${h}:r=${fps}:d=${seconds}[bg];color=c=red:s=40x40:r=${fps}:d=${seconds}[fg];[bg][fg]overlay=x='n*2':y=${y}:eval=frame:shortest=1`;
  const r = spawnSync('ffmpeg', ['-y', '-v', 'error', '-filter_complex', fc, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '10',
    '-metadata', `title=${tag}`, file], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(r.stderr);
  return file;
}

export function tmp(prefix = 'studio-test-') { return mkdtempSync(path.join(os.tmpdir(), prefix)); }
export function newCtx(opts) { const home = tmp(); return createContext(home, { token: 'test-token', ...opts }); }
export const seg = (id, s, e, o = {}) => ({ id, start_frame: s, end_frame: e, athlete_id: null, event_type: 'wave_ride', decision: 'include', reason_code: null, notes: '', framing_mode: null, target: null, ...o });
export const kf = (id, segment_id, frame, bbox, o = {}) => ({ id, segment_id, frame, bbox, visibility: 'visible', origin: 'manual', ...o });
export { writeFileSync };
