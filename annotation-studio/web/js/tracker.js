// Automatic BOX tracking in the browser (no server, no model): follows the box the operator drew, frame by frame,
// with template matching (zero-mean normalized cross-correlation) on a downscaled grayscale copy of the video.
// The result is an ESTIMATE: every tracked box is stored as origin 'suggested', drawn dashed, and is never "verified"
// until a person checks it. When the match gets weak the tracker stops and reports where it lost the athlete.

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/** Raised when pixels cannot be read (e.g. a cloud video served without CORS permission). */
export class TrackError extends Error { constructor(code, msg) { super(msg); this.code = code; } }

function loadVideo(src, cors = true) {
  return new Promise((resolve, reject) => {
    const v = document.createElement('video');
    v.muted = true; v.preload = 'auto'; v.playsInline = true; if (cors) v.crossOrigin = 'anonymous';
    const done = ok => { v.onloadeddata = v.onerror = null; ok ? resolve(v) : reject(new TrackError('MEDIA', 'לא ניתן לטעון את הווידאו למעקב')); };
    v.onloadeddata = () => { clearTimeout(t); done(true); }; v.onerror = () => { clearTimeout(t); done(false); };
    const t = setTimeout(() => { v.onloadeddata = v.onerror = null; v.removeAttribute('src'); v.load(); reject(new TrackError('SLOW', 'הווידאו לא נטען למעקב תוך דקה. בדוק את החיבור ונסה "↻ עקוב שוב".')); }, 60000);
    v.src = src;
  });
}
/** Load for pixel reading. If it loads only WITHOUT cross-origin mode, the server does not allow reading (CORS). */
async function loadReadable(src) {
  try { return await loadVideo(src, true); }
  catch (e) {
    const plain = await loadVideo(src, false).catch(() => null);
    if (plain) { plain.removeAttribute('src'); plain.load(); throw new TrackError('CORS', 'הדפדפן לא מורשה לקרוא את פיקסלי הווידאו (חסרה הרשאת CORS לווידאו בענן)'); }
    throw e;
  }
}
// A seek that never completes (network stall) must not hang the tracker forever.
function seek(v, t) {
  return new Promise((resolve, reject) => {
    if (Math.abs(v.currentTime - t) < 1e-4 && v.readyState >= 2) return resolve();
    const fin = () => { clearTimeout(to); v.removeEventListener('seeked', fin); resolve(); };
    const to = setTimeout(() => { v.removeEventListener('seeked', fin); reject(new TrackError('SLOW', 'הווידאו נטען לאט מדי מהענן והמעקב נעצר. נסה "↻ עקוב שוב".')); }, 20000);
    v.addEventListener('seeked', fin); v.currentTime = t;
  });
}

function grayFrame(ctx, v, W, H) {
  ctx.drawImage(v, 0, 0, W, H);
  let d;
  try { d = ctx.getImageData(0, 0, W, H).data; }
  catch { throw new TrackError('CORS', 'הדפדפן לא מורשה לקרוא את פיקסלי הווידאו (חסרה הרשאת CORS לווידאו בענן)'); }
  const g = new Float32Array(W * H);
  for (let i = 0, j = 0; i < g.length; i++, j += 4) g[i] = 0.299 * d[j] + 0.587 * d[j + 1] + 0.114 * d[j + 2];
  return g;
}

/** Template (w x h) sampled from gray image at (x,y) with size (sw,sh) -> zero-mean vector + norm. */
function sample(g, W, H, x, y, sw, sh, w, h) {
  const t = new Float32Array(w * h); let m = 0;
  for (let j = 0; j < h; j++) {
    const yy = clamp(Math.round(y + (j + 0.5) * sh / h - 0.5), 0, H - 1);
    for (let i = 0; i < w; i++) { const xx = clamp(Math.round(x + (i + 0.5) * sw / w - 0.5), 0, W - 1); const v = g[yy * W + xx]; t[j * w + i] = v; m += v; }
  }
  m /= t.length; let n = 0;
  for (let k = 0; k < t.length; k++) { t[k] -= m; n += t[k] * t[k]; }
  return { t, n: Math.sqrt(n) };
}
function ncc(g, W, x, y, T, w, h) {
  let s = 0, s2 = 0, c = 0;
  for (let j = 0; j < h; j++) {
    const row = (y + j) * W + x, tr = j * w;
    for (let i = 0; i < w; i++) { const v = g[row + i]; s += v; s2 += v * v; c += v * T.t[tr + i]; }
  }
  const n = w * h, varp = s2 - s * s / n;
  if (varp <= 1e-6 || T.n <= 1e-6) return 0;
  return c / (Math.sqrt(varp) * T.n);       // sum(T')*mean(P)=0 because T' is zero-mean
}
function search(g, W, H, T, w, h, cx, cy, r) {
  let best = { s: -2, x: cx, y: cy };
  const x0 = clamp(cx - r, 0, W - w), x1 = clamp(cx + r, 0, W - w), y0 = clamp(cy - r, 0, H - h), y1 = clamp(cy + r, 0, H - h);
  for (let y = y0; y <= y1; y += 2) for (let x = x0; x <= x1; x += 2) { const s = ncc(g, W, x, y, T, w, h); if (s > best.s) best = { s, x, y }; }
  const bx = best.x, by = best.y;                                         // refine around the coarse optimum
  for (let y = Math.max(0, by - 2); y <= Math.min(H - h, by + 2); y++) for (let x = Math.max(0, bx - 2); x <= Math.min(W - w, bx + 2); x++) {
    const s = ncc(g, W, x, y, T, w, h); if (s > best.s) best = { s, x, y };
  }
  return best;
}

/**
 * Track a box from frame `from` (where the operator drew it) to frame `to` (inclusive, either direction).
 * @returns {Promise<{boxes: {frame:number,bbox:object,score:number}[], lost: number|null}>}
 */
export async function trackBox({ src, fps, from, to, bbox, step = 3, onProgress, signal, minScore = 0.5 }) {
  const v = await loadReadable(src);
  try {
    const vw = v.videoWidth, vh = v.videoHeight;
    // Work at a scale where the box is ~40 px: fast, and enough detail to tell the athlete from water/sky.
    const k = clamp(40 / Math.max(bbox.w * vw, bbox.h * vh, 1), 160 / vw, 1);
    const W = Math.max(16, Math.round(vw * k)), H = Math.max(16, Math.round(vh * k));
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    const at = f => (f + 0.5) / fps;
    await seek(v, at(from));
    let g = grayFrame(ctx, v, W, H);
    let bx = bbox.x * W, by = bbox.y * H, bw = Math.max(4, bbox.w * W), bh = Math.max(4, bbox.h * H);
    const tw = Math.max(4, Math.round(bw)), th = Math.max(4, Math.round(bh));
    const T0 = sample(g, W, H, bx, by, bw, bh, tw, th);
    if (T0.n < 1e-3 * tw * th) throw new TrackError('FLAT', 'אין מספיק פרטים בתוך ה-BOX כדי לעקוב (צייר תיבה הדוקה יותר על הגולש)');
    let T = { t: Float32Array.from(T0.t), n: T0.n };
    const dir = to >= from ? 1 : -1, total = Math.abs(to - from), out = [];
    let weak = 0, lost = null;
    for (let f = from + dir * step; dir > 0 ? f <= to : f >= to; f += dir * step) {
      if (signal?.aborted) break;
      await step1(f);
      if (lost != null) break;
      // always end exactly on the last frame of the range so the box reaches the event edge
      if (Math.abs(to - f) < step && f !== to) { await step1(to); break; }
    }
    return { boxes: out, lost };

    async function step1(f) {
      await seek(v, at(f));
      g = grayFrame(ctx, v, W, H);
      const r = Math.round(Math.max(bw, bh) * 0.9 + 4 * step);
      const best = search(g, W, H, T, tw, th, Math.round(bx), Math.round(by), r);
      // scale: try the patch slightly smaller/larger around the matched centre (camera zoom / athlete distance)
      let sc = 1, sbest = best.s;
      for (const s of [0.9, 1.1]) {
        const nw = bw * s, nh = bh * s, cx = best.x + bw / 2, cy = best.y + bh / 2;
        const P = sample(g, W, H, cx - nw / 2, cy - nh / 2, nw, nh, tw, th);
        let c = 0; for (let i = 0; i < P.t.length; i++) c += P.t[i] * T.t[i];
        const sv = P.n > 1e-6 ? c / (P.n * T.n) : 0;
        if (sv > sbest + 0.02) { sbest = sv; sc = s; }
      }
      const cx = best.x + bw / 2, cy = best.y + bh / 2;
      bw = clamp(bw * sc, 4, W); bh = clamp(bh * sc, 4, H); bx = clamp(cx - bw / 2, 0, W - bw); by = clamp(cy - bh / 2, 0, H - bh);
      const score = Math.max(best.s, sbest);
      if (score < minScore) { if (++weak >= 2) { lost = f; return; } } else weak = 0;
      if (score >= minScore) out.push({ frame: f, score: +score.toFixed(3), bbox: { x: bx / W, y: by / H, w: bw / W, h: bh / H } });
      // slow template update keeps up with pose changes without drifting onto the background
      if (score > 0.7) {
        const P = sample(g, W, H, bx, by, bw, bh, tw, th); let n = 0;
        for (let i = 0; i < T.t.length; i++) { T.t[i] = 0.85 * T.t[i] + 0.1 * P.t[i] + 0.05 * T0.t[i]; n += T.t[i] * T.t[i]; }
        T.n = Math.sqrt(n);
      }
      onProgress?.(Math.min(1, Math.abs(f - from) / Math.max(1, total)));
    }
  } finally { v.removeAttribute('src'); v.load(); }
}
