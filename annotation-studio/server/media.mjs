// ffprobe/ffmpeg wrappers. Thumbnails and proxies are disposable derivatives with their own
// provenance; they never replace the archived original.
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '', err = '';
    p.stdout.on('data', d => out += d); p.stderr.on('data', d => err += d);
    p.on('error', reject);
    p.on('close', code => code === 0 ? resolve(out) : reject(new Error(`${cmd} exited ${code}: ${err.slice(-400)}`)));
  });
}

export async function probe(file) {
  const j = JSON.parse(await run('ffprobe', ['-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', file]));
  const v = (j.streams || []).find(s => s.codec_type === 'video');
  if (!v) throw Object.assign(new Error('no video stream'), { code: 'NOT_VIDEO' });
  const [num, den] = String(v.r_frame_rate || v.avg_frame_rate).split('/').map(Number);
  const dur = Number(j.format?.duration ?? v.duration ?? 0);
  let frames = Number(v.nb_frames);
  if (!Number.isFinite(frames) || frames <= 0) frames = Math.round(dur * num / (den || 1));
  const rot = Number(v.tags?.rotate ?? (v.side_data_list || []).find(s => 'rotation' in s)?.rotation ?? 0);
  return {
    codec: v.codec_name, width: v.width, height: v.height,
    rotation: ((Math.round(-rot) % 360) + 360) % 360,
    fps_num: num, fps_den: den || 1, frame_count: frames,
    duration_ms: Math.round(dur * 1000),
    captured_at: j.format?.tags?.creation_time ?? null,
  };
}

export async function makeThumb(src, dest) {
  mkdirSync(path.dirname(dest), { recursive: true });
  await run('ffmpeg', ['-y', '-v', 'error', '-i', src, '-vf', 'scale=320:-2', '-frames:v', '1', dest]);
}

/** Frame-preserving proxy: constant frame rate equal to the source so frame N maps to frame N. */
export async function makeProxy(src, dest, { fpsNum, fpsDen, width = 640 }) {
  mkdirSync(path.dirname(dest), { recursive: true });
  await run('ffmpeg', ['-y', '-v', 'error', '-i', src, '-an', '-vf', `scale=${width}:-2,fps=${fpsNum}/${fpsDen}`,
    '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '8', '-crf', '38', '-b:v', '0', '-g', '15', dest]);
}
