// Automatic BOX tracking in the browser (no server, no model): follows the box the operator drew, frame by frame.
// The result is an ESTIMATE: every tracked box is stored as origin 'suggested', drawn dashed, and is never "verified"
// until a person checks it. When the athlete cannot be found for ~1 s the tracker stops and reports where.
//
// Built for drone surf footage and checked against scripts/sim-surf.py (textured water, foam, drone drift, look-alike
// surfers, spray occlusion):
//  - colour features, not only brightness (gray, R-B, G-(R+B)/2), so a surfer stands out from water and white foam;
//  - a loosely drawn box is mostly water: pixels that look like the box border get little weight (weighted NCC);
//  - constant-velocity prediction and a search around it, with a small preference for the predicted place;
//  - short occlusions are bridged (coast on the prediction, search wider), the template adapts slowly and stays
//    anchored to what the operator drew.

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/** Raised when pixels cannot be read (cloud video without CORS), the video is too slow, or the box has no detail. */
export class TrackError extends Error { constructor(code, msg) { super(msg); this.code = code; } }

function loadVideo(src, cors = true) {
  return new Promise((resolve, reject) => {
    const v = document.createElement('video');
    v.muted = true; v.preload = 'metadata'; v.playsInline = true; if (cors) v.crossOrigin = 'anonymous';   // frames are fetched per seek
    const done = ok => { v.onloadedmetadata = v.onerror = null; ok ? resolve(v) : reject(new TrackError('MEDIA', 'לא ניתן לטעון את הווידאו למעקב')); };
    v.onloadedmetadata = () => { clearTimeout(t); done(true); }; v.onerror = () => { clearTimeout(t); done(false); };
    const t = setTimeout(() => { v.onloadedmetadata = v.onerror = null; v.removeAttribute('src'); v.load(); reject(new TrackError('SLOW', 'הווידאו לא נטען למעקב תוך דקה. בדוק את החיבור ונסה "↻ עקוב שוב".')); }, 60000);
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
    if (Math.abs(v.currentTime - t) < 1e-4) t += 1e-4;
    const fin = () => { clearTimeout(to); v.removeEventListener('seeked', fin); resolve(); };
    const to = setTimeout(() => { v.removeEventListener('seeked', fin); reject(new TrackError('SLOW', 'הווידאו נטען לאט מדי והמעקב נעצר. נסה "↻ עקוב שוב".')); }, 20000);
    v.addEventListener('seeked', fin); v.currentTime = t;
  });
}

const NCH = 3, CH_W = [0.25, 0.55, 0.2];   // warm-vs-blue carries most: skin/boards vs water and white foam
function features(ctx, v, W, H) {
  ctx.drawImage(v, 0, 0, W, H);
  let d;
  try { d = ctx.getImageData(0, 0, W, H).data; }
  catch { throw new TrackError('CORS', 'הדפדפן לא מורשה לקרוא את פיקסלי הווידאו (חסרה הרשאת CORS לווידאו בענן)'); }
  const n = W * H, f = [new Float32Array(n), new Float32Array(n), new Float32Array(n)];
  for (let i = 0, j = 0; i < n; i++, j += 4) {
    const r = d[j], g = d[j + 1], b = d[j + 2];
    f[0][i] = 0.299 * r + 0.587 * g + 0.114 * b; f[1][i] = r - b; f[2][i] = g - (r + b) / 2;
  }
  return f;
}
/** Sample a (w x h) patch of every channel from region (x,y,sw,sh). */
function patch(F, W, H, x, y, sw, sh, w, h) {
  const out = F.map(() => new Float32Array(w * h));
  for (let j = 0; j < h; j++) {
    const yy = clamp(Math.round(y + (j + 0.5) * sh / h - 0.5), 0, H - 1);
    for (let i = 0; i < w; i++) {
      const k = yy * W + clamp(Math.round(x + (i + 0.5) * sw / w - 0.5), 0, W - 1);
      for (let c = 0; c < NCH; c++) out[c][j * w + i] = F[c][k];
    }
  }
  return out;
}
/** Weighted zero-mean template per channel: t = w*(p-mean), n = sqrt(sum w*(p-mean)^2). */
function makeTemplate(P, wt, sumW) {
  return P.map(ch => {
    let m = 0; for (let i = 0; i < ch.length; i++) m += wt[i] * ch[i]; m /= sumW;
    const t = new Float32Array(ch.length); let n = 0;
    for (let i = 0; i < ch.length; i++) { const d = ch[i] - m; t[i] = wt[i] * d; n += wt[i] * d * d; }
    return { t, n: Math.sqrt(n) };
  });
}
/** Weighted NCC between template T and the (w x h) patch at (x,y) of planes G (width GW). */
function nccAt(G, GW, x, y, T, wt, sumW, w, h) {
  let tot = 0;
  for (let c = 0; c < NCH; c++) {
    const ch = G[c], tc = T[c]; if (tc.n < 1e-6) continue;
    let s = 0, s2 = 0, cr = 0;
    for (let j = 0; j < h; j++) {
      const row = (y + j) * GW + x, tr = j * w;
      for (let i = 0; i < w; i++) { const p = ch[row + i], ww = wt[tr + i]; s += ww * p; s2 += ww * p * p; cr += tc.t[tr + i] * p; }
    }
    const varp = s2 - s * s / sumW;
    if (varp > 1e-6) tot += CH_W[c] * cr / (Math.sqrt(varp) * tc.n);
  }
  return tot;
}
function nccPatch(P, T, wt, sumW) {
  const Q = makeTemplate(P, wt, sumW); let tot = 0;
  for (let c = 0; c < NCH; c++) {
    if (Q[c].n < 1e-6 || T[c].n < 1e-6) continue;
    let cr = 0; for (let i = 0; i < Q[c].t.length; i++) cr += Q[c].t[i] * T[c].t[i] / Math.max(wt[i], 1e-6);
    tot += CH_W[c] * cr / (Q[c].n * T[c].n);
  }
  return tot;
}
/** Weights: soft window x "does not look like the border of the box" (the water around a loosely drawn box). */
function weights(P, w, h) {
  const n = w * h, ring = [];
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if (i < 2 || j < 2 || i >= w - 2 || j >= h - 2) ring.push(j * w + i);
  const st = P.map(ch => { let m = 0; for (const k of ring) m += ch[k]; m /= ring.length; let v = 0; for (const k of ring) v += (ch[k] - m) ** 2; return { m, s: Math.sqrt(v / ring.length) + 4 }; });
  const wt = new Float32Array(n); let fg = 0;
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) {
    const k = j * w + i;
    let d = 0; for (let c = 0; c < NCH; c++) d = Math.max(d, Math.abs(P[c][k] - st[c].m) / st[c].s);
    const fk = clamp((d - 1.5) / 1.5, 0, 1); fg += fk;
    const win = (0.5 - 0.5 * Math.cos(2 * Math.PI * (i + 0.5) / w)) * (0.5 - 0.5 * Math.cos(2 * Math.PI * (j + 0.5) / h));
    wt[k] = (0.12 + 0.88 * fk) * (0.35 + 0.65 * win);
  }
  const mask = new Float32Array(n);
  for (let k = 0; k < n; k++) mask[k] = wt[k] > 0.5 ? 1 : 0;
  if (fg / n < 0.01) wt.fill(1);                                    // nothing stands out: plain matching
  return { wt, mask, fgFrac: fg / n };
}

// ---- colour model: "how much does this pixel look like the athlete rather than the water around it" ----
const BINS = 8, binOf = (r, g, b) => ((r >> 5) * BINS + (g >> 5)) * BINS + (b >> 5);
function readRGB(ctx, W, H) { return ctx.getImageData(0, 0, W, H).data; }
/** fg histogram from the weighted drawn box, bg histogram from a ring around it -> per-bin likelihood ratio. */
function colourModel(d, W, H, bx, by, bw, bh, wt, tw, th) {
  const fg = new Float32Array(BINS ** 3), bg = new Float32Array(BINS ** 3);
  let fs = 0, bs = 0;
  for (let j = 0; j < th; j++) for (let i = 0; i < tw; i++) {
    const x = Math.round(bx + (i + 0.5) * bw / tw), y = Math.round(by + (j + 0.5) * bh / th);
    if (x < 0 || y < 0 || x >= W || y >= H) continue;
    const k = (y * W + x) * 4, w = wt[j * tw + i]; fg[binOf(d[k], d[k + 1], d[k + 2])] += w; fs += w;
  }
  const x0 = Math.max(0, Math.round(bx - bw)), x1 = Math.min(W - 1, Math.round(bx + 2 * bw)), y0 = Math.max(0, Math.round(by - bh)), y1 = Math.min(H - 1, Math.round(by + 2 * bh));
  for (let y = y0; y <= y1; y += 2) for (let x = x0; x <= x1; x += 2) {
    if (x >= bx && x < bx + bw && y >= by && y < by + bh) continue;
    const k = (y * W + x) * 4; bg[binOf(d[k], d[k + 1], d[k + 2])]++; bs++;
  }
  const L = new Float32Array(BINS ** 3);
  for (let i = 0; i < L.length; i++) { const f = fg[i] / Math.max(fs, 1), b = bg[i] / Math.max(bs, 1); L[i] = f > 0 ? clamp(f / (f + 3 * b + 1e-3), 0, 1) : 0; }   // colours also found around the box (water, foam) score low
  return L;
}
/** Mean-shift on the colour likelihood: the centre of "athlete-coloured" pixels near the predicted place. */
function meanShift(d, W, H, L, cx, cy, bw, bh) {
  let mass = 0;
  for (let it = 0; it < 6; it++) {
    const x0 = Math.max(0, Math.round(cx - bw)), x1 = Math.min(W - 1, Math.round(cx + bw)), y0 = Math.max(0, Math.round(cy - bh)), y1 = Math.min(H - 1, Math.round(cy + bh));
    let sx = 0, sy = 0, sw = 0;
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const k = (y * W + x) * 4, p = L[binOf(d[k], d[k + 1], d[k + 2])]; if (p < 0.6) continue;
      const g = Math.exp(-(((x - cx) / bw) ** 2 + ((y - cy) / bh) ** 2) * 2) * p;
      sx += g * x; sy += g * y; sw += g;
    }
    if (sw < 1e-6) return { cx, cy, mass: 0 };
    const nx = sx / sw, ny = sy / sw, moved = Math.hypot(nx - cx, ny - cy);
    cx = nx; cy = ny; mass = sw;
    if (moved < 0.5) break;
  }
  return { cx, cy, mass };
}

/**
 * Track a box from frame `from` (where the operator drew it) to frame `to` (inclusive, either direction).
 * @returns {Promise<{boxes: {frame:number,bbox:object,score:number}[], lost: number|null}>}
 */
export async function trackBox({ src, fps, from, to, bbox, step = 3, onProgress, signal, minScore = 0.45, hold }) {
  const v = await loadReadable(src);
  try {
    const vw = v.videoWidth, vh = v.videoHeight;
    // Work where the drawn box is ~56 px across: enough detail to tell a surfer from foam, still fast.
    const k = clamp(56 / Math.max(bbox.w * vw, bbox.h * vh, 1), 320 / vw, 1);
    const W = Math.max(32, Math.round(vw * k)), H = Math.max(32, Math.round(vh * k));
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    const at = f => (f + 0.5) / fps;
    await seek(v, at(from));
    let F = features(ctx, v, W, H);
    let RGB = readRGB(ctx, W, H);
    let bx = bbox.x * W, by = bbox.y * H, bw = Math.max(6, bbox.w * W), bh = Math.max(6, bbox.h * H);
    const tw = clamp(Math.round(bw), 8, 72), th = clamp(Math.round(bh), 8, 72);
    const P0 = patch(F, W, H, bx, by, bw, bh, tw, th);
    const { wt, mask, fgFrac } = weights(P0, tw, th);
    const sumW = wt.reduce((a, b) => a + b, 0);
    const T0 = makeTemplate(P0, wt, sumW);
    if (T0.every(t => t.n < 0.5 * Math.sqrt(sumW))) throw new TrackError('FLAT', 'אין מספיק פרטים בתוך ה-BOX כדי לעקוב (צייר תיבה הדוקה יותר על הגולש)');
    const L = colourModel(RGB, W, H, bx, by, bw, bh, mask, tw, th);
    const mass0 = Math.max(1e-6, meanShift(RGB, W, H, L, bx + bw / 2, by + bh / 2, bw * 0.6, bh * 0.6).mass);
    const recent = P0.map(c => Float32Array.from(c));
    let T = T0;
    const dir = to >= from ? 1 : -1, total = Math.abs(to - from), out = [];
    let vx = 0, vy = 0, miss = 0, lost = null, lastGood = from;
    const maxMiss = Math.max(3, Math.round(fps / step));            // ~1 s without a confident match -> give up
    for (let f = from + dir * step; dir > 0 ? f <= to : f >= to; f += dir * step) {
      if (signal?.aborted) break;
      await one(f);
      if (lost != null) break;
      if (Math.abs(to - f) < step && f !== to) { await one(to); break; }
    }
    return { boxes: out, lost, fg: +fgFrac.toFixed(3) };

    async function one(f) {
      while (hold?.() && !signal?.aborted) await new Promise(r => setTimeout(r, 250));   // yield the network to the player
      await seek(v, at(f));
      F = features(ctx, v, W, H); RGB = readRGB(ctx, W, H);
      // 1) colour: mean-shift from the predicted centre onto the athlete-coloured pixels (robust to foam and water)
      const pcx = bx + vx + bw / 2, pcy = by + vy + bh / 2;
      const ms = meanShift(RGB, W, H, L, pcx, pcy, bw * (miss ? 0.9 : 0.6), bh * (miss ? 0.9 : 0.6));
      const colour = ms.mass / mass0;
      // 2) shape: template match on a grid resampled so the box is tw x th, searched around the colour centre
      const sx = bw / tw, sy = bh / th, gW = Math.max(tw + 1, Math.round(W / sx)), gH = Math.max(th + 1, Math.round(H / sy));
      const G = F.map(ch => { const o = new Float32Array(gW * gH); for (let y = 0; y < gH; y++) { const yy = Math.min(H - 1, Math.round((y + 0.5) * sy - 0.5)); for (let x = 0; x < gW; x++) o[y * gW + x] = ch[yy * W + Math.min(W - 1, Math.max(0, Math.round((x + 0.5) * sx - 0.5)))]; } return o; });
      const useColour = colour >= 0.25;
      const ccx = useColour ? ms.cx : pcx, ccy = useColour ? ms.cy : pcy;
      const px = (ccx - bw / 2) / sx, py = (ccy - bh / 2) / sy;
      const r = useColour ? Math.max(tw, th) * 0.35 + 2 : Math.max(tw, th) * (miss ? Math.min(2.5, 0.8 + 0.35 * miss) : 0.55) + 3;
      const pen = 0.25 / Math.max(tw, th);
      let best = { s: -9, raw: -9, x: Math.round(px), y: Math.round(py) };
      const x0 = clamp(Math.round(px - r), 0, gW - tw), x1 = clamp(Math.round(px + r), 0, gW - tw);
      const y0 = clamp(Math.round(py - r), 0, gH - th), y1 = clamp(Math.round(py + r), 0, gH - th);
      const st = r > 30 ? 3 : 2;
      const eval1 = (x, y) => { const raw = nccAt(G, gW, x, y, T, wt, sumW, tw, th), sc2 = raw - pen * Math.hypot(x - px, y - py); if (sc2 > best.s) best = { s: sc2, raw, x, y }; };
      for (let y = y0; y <= y1; y += st) for (let x = x0; x <= x1; x += st) eval1(x, y);
      const cbx = best.x, cby = best.y;
      for (let y = Math.max(0, cby - st); y <= Math.min(gH - th, cby + st); y++) for (let x = Math.max(0, cbx - st); x <= Math.min(gW - tw, cbx + st); x++) eval1(x, y);
      let cx = (best.x + tw / 2) * sx, cy = (best.y + th / 2) * sy;
      // shape match weak (spray, pose change) but colour clearly there: trust the colour centre
      if (useColour && best.raw < 0.4) { cx = ms.cx; cy = ms.cy; }
      let sc = 1, sb = best.raw;
      for (const s2 of [0.9, 1.1]) {
        const v2 = nccPatch(patch(F, W, H, cx - bw * s2 / 2, cy - bh * s2 / 2, bw * s2, bh * s2, tw, th), T, wt, sumW);
        if (v2 > sb + 0.03) { sb = v2; sc = s2; }
      }
      const dist = Math.hypot(cx - pcx, cy - pcy) / Math.hypot(bw, bh);   // in box diagonals
      const conf = Math.max(sb, Math.min(1, colour) * 0.8);
      // A sudden jump is only believed with a strong shape match; otherwise the athlete is assumed hidden for a moment.
      const ok = sb >= 0.75 || (dist < (sb >= 0.6 ? 0.6 : 0.35) && (sb >= (miss ? 0.33 : minScore) || (useColour && colour >= 0.5)));
      if (!ok) {                                                      // not confident: coast on the prediction
        miss++; bx = clamp(bx + vx, 0, W - bw); by = clamp(by + vy, 0, H - bh);
        if (miss > maxMiss) lost = lastGood + dir * step;
        return;
      }
      const nw = clamp(bw * sc, 6, W), nh = clamp(bh * sc, 6, H), nx = clamp(cx - nw / 2, 0, W - nw), ny = clamp(cy - nh / 2, 0, H - nh);
      const n1 = miss + 1;
      vx = 0.5 * vx + 0.5 * (nx - bx) / n1; vy = 0.5 * vy + 0.5 * (ny - by) / n1;
      const vmax = 0.35 * Math.hypot(bw, bh), vm = Math.hypot(vx, vy); if (vm > vmax) { vx *= vmax / vm; vy *= vmax / vm; }   // no runaway prediction
      bx = nx; by = ny; bw = nw; bh = nh; miss = 0; lastGood = f;
      out.push({ frame: f, score: +conf.toFixed(3), bbox: { x: bx / W, y: by / H, w: bw / W, h: bh / H } });
      if (sb > 0.6) {                                                 // slow adaptation, anchored to the drawn box
        const P = patch(F, W, H, bx, by, bw, bh, tw, th);
        for (let c = 0; c < NCH; c++) for (let i = 0; i < P[c].length; i++) recent[c][i] = 0.8 * recent[c][i] + 0.2 * P[c][i];
        const R = makeTemplate(recent, wt, sumW);
        T = T0.map((t0, c) => { const t = new Float32Array(t0.t.length); let n = 0; for (let i = 0; i < t.length; i++) { t[i] = 0.5 * t0.t[i] + 0.5 * R[c].t[i]; n += t[i] * t[i] / Math.max(wt[i], 1e-6); } return { t, n: Math.sqrt(n) }; });
      }
      onProgress?.(Math.min(1, Math.abs(f - from) / Math.max(1, total)));
    }
  } finally { v.removeAttribute('src'); v.load(); }
}
