import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

/** Synthetic clip: a red 40x40 "surfer" at x=2n, y=`y` on blue. Bbox truth is analytic. */
export function makeVideo(file, { seconds = 4, fps = 30, w = 320, h = 180, y = 70, tag = 'a', ext } = {}) {
  mkdirSync(path.dirname(file), { recursive: true });
  const fc = `color=c=blue:s=${w}x${h}:r=${fps}:d=${seconds}[bg];color=c=red:s=40x40:r=${fps}:d=${seconds}[fg];[bg][fg]overlay=x='n*2':y=${y}:eval=frame:shortest=1`;
  const r = spawnSync('ffmpeg', ['-y', '-v', 'error', '-filter_complex', fc, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '10',
    '-metadata', `title=${tag}`, file], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(r.stderr);
  return file;
}
