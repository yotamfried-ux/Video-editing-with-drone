// Dependency-free MP4/MOV probe for the hosted Studio (no ffprobe binary on serverless hosts).
// Reads only box headers and the `moov` box through byte-range reads, so a multi-GB 4K original is probed with a few
// small requests whether `moov` sits at the start (faststart) or at the end (camera default).
// Returns the same shape as media.probe(): codec, width, height, rotation, fps_num, fps_den, frame_count, duration_ms,
// captured_at. Frame rate and count come from the video track's own sample tables (stts/stsz), i.e. the real frames.

const MAX_MOOV = 96 * 1024 * 1024;
const CONTAINERS = new Set(['moov', 'trak', 'mdia', 'minf', 'stbl', 'edts', 'dinf']);
const gcd = (a, b) => { while (b) [a, b] = [b, a % b]; return a; };
const MAC_EPOCH = Date.UTC(1904, 0, 1);

/** Top-level box walk using only 16-byte header reads; returns the moov box bytes. */
async function readMoov(read, size) {
  let off = 0;
  while (off + 8 <= size) {
    const h = await read(off, Math.min(off + 16, size) - 1);
    let len = h.readUInt32BE(0);
    const type = h.toString('latin1', 4, 8);
    let hdr = 8;
    if (len === 1) { len = Number(h.readBigUInt64BE(8)); hdr = 16; }
    else if (len === 0) len = size - off;
    if (len < hdr) throw Object.assign(new Error(`invalid MP4 box at ${off}`), { code: 'NOT_VIDEO' });
    if (type === 'moov') {
      if (len > MAX_MOOV) throw Object.assign(new Error('moov box too large'), { code: 'NOT_VIDEO' });
      return (await read(off, off + len - 1)).subarray(hdr);
    }
    if (off === 0 && !['ftyp', 'free', 'skip', 'wide', 'mdat', 'pdin', 'uuid', 'moov'].includes(type)) {
      throw Object.assign(new Error('not an MP4/MOV file'), { code: 'NOT_VIDEO' });
    }
    off += len;
  }
  throw Object.assign(new Error('no moov box (not a finished MP4/MOV file)'), { code: 'NOT_VIDEO' });
}

function* boxes(buf) {
  let off = 0;
  while (off + 8 <= buf.length) {
    let len = buf.readUInt32BE(off), hdr = 8;
    const type = buf.toString('latin1', off + 4, off + 8);
    if (len === 1) { len = Number(buf.readBigUInt64BE(off + 8)); hdr = 16; } else if (len === 0) len = buf.length - off;
    if (len < hdr || off + len > buf.length) return;
    yield { type, body: buf.subarray(off + hdr, off + len) };
    off += len;
  }
}
const find = (buf, type) => { for (const b of boxes(buf)) if (b.type === type) return b.body; return null; };

function parseTrak(trak) {
  const mdia = find(trak, 'mdia'); if (!mdia) return null;
  const hdlr = find(mdia, 'hdlr'); if (!hdlr || hdlr.toString('latin1', 8, 12) !== 'vide') return null;
  const mdhd = find(mdia, 'mdhd'); const tkhd = find(trak, 'tkhd');
  const minf = find(mdia, 'minf'); const stbl = minf && find(minf, 'stbl');
  if (!mdhd || !tkhd || !stbl) return null;
  const v1 = mdhd[0] === 1;
  const timescale = v1 ? mdhd.readUInt32BE(20) : mdhd.readUInt32BE(12);
  const duration = v1 ? Number(mdhd.readBigUInt64BE(24)) : mdhd.readUInt32BE(16);
  // tkhd: matrix (a b u / c d v / x y w) and width/height in 16.16 fixed point
  const t1 = tkhd[0] === 1, m = t1 ? 52 : 40;
  const a = tkhd.readInt32BE(m) / 65536, b = tkhd.readInt32BE(m + 4) / 65536;
  const width = Math.round(tkhd.readUInt32BE(m + 36) / 65536), height = Math.round(tkhd.readUInt32BE(m + 40) / 65536);
  const angle = Math.round(Math.atan2(b, a) * 180 / Math.PI);
  const stsd = find(stbl, 'stsd'); const fourcc = stsd && stsd.length >= 16 ? stsd.toString('latin1', 12, 16) : null;
  // coded size from the sample entry (tkhd may carry display size)
  let codedW = null, codedH = null;
  if (stsd && stsd.length >= 8 + 8 + 28) { codedW = stsd.readUInt16BE(8 + 8 + 24); codedH = stsd.readUInt16BE(8 + 8 + 26); }
  const stsz = find(stbl, 'stsz'); const frames = stsz ? stsz.readUInt32BE(8) : null;
  const stts = find(stbl, 'stts');
  let delta = null;
  if (stts) {   // dominant sample delta = the nominal frame duration (ignores a short odd first/last entry)
    const n = stts.readUInt32BE(4); let best = 0;
    for (let i = 0; i < n; i++) { const c = stts.readUInt32BE(8 + i * 8), d = stts.readUInt32BE(12 + i * 8); if (c > best) { best = c; delta = d; } }
  }
  return { timescale, duration, width: codedW || width, height: codedH || height, angle, fourcc, frames, delta };
}

const CODEC = { avc1: 'h264', avc3: 'h264', hvc1: 'hevc', hev1: 'hevc', av01: 'av1', vp09: 'vp9', mp4v: 'mpeg4', 'apcn': 'prores', 'apch': 'prores' };

/**
 * @param read async (start, endInclusive) => Buffer   byte-range reader
 * @param size total object size in bytes
 */
export async function probeMp4(read, size) {
  const moov = await readMoov(read, size);
  let track = null;
  for (const b of boxes(moov)) if (b.type === 'trak') { track = parseTrak(b.body); if (track) break; }
  if (!track || !track.timescale || !track.frames) throw Object.assign(new Error('no video track'), { code: 'NOT_VIDEO' });
  let fpsNum = track.timescale, fpsDen = track.delta || Math.max(1, Math.round(track.duration / track.frames));
  const g = gcd(fpsNum, fpsDen); fpsNum /= g; fpsDen /= g;
  const mvhd = find(moov, 'mvhd');
  let captured = null;
  if (mvhd) {
    const secs = mvhd[0] === 1 ? Number(mvhd.readBigUInt64BE(4)) : mvhd.readUInt32BE(4);
    if (secs > 0) captured = new Date(MAC_EPOCH + secs * 1000).toISOString().replace(/\.\d{3}Z$/, '.000000Z');
  }
  return {
    codec: CODEC[track.fourcc] ?? track.fourcc, width: track.width, height: track.height,
    rotation: ((track.angle % 360) + 360) % 360,
    fps_num: fpsNum, fps_den: fpsDen, frame_count: track.frames,
    duration_ms: Math.round(track.duration / track.timescale * 1000),
    captured_at: captured,
  };
}

/** Byte-range reader over the read-only R2 client (stops reading as soon as the requested bytes arrived). */
export function rangeReaderForCloud(cloud, key) {
  return async (start, end) => {
    const stream = await cloud.open(key, { start, end });
    const want = end - start + 1, chunks = []; let n = 0;
    for await (const c of stream) { chunks.push(c); n += c.length; if (n >= want) break; }
    stream.destroy?.();
    return Buffer.concat(chunks).subarray(0, want);
  };
}
