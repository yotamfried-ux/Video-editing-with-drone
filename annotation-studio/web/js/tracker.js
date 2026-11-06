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
//  - the camera's own motion (drone closing in / pulling back, panning) is measured on the whole picture each step
//    and applied to the box first: when the camera zooms in, the box grows with the athlete and keeps the proportion
//    it was drawn with (the pipeline crops/zooms from it), instead of staying the size it was drawn.

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
  let sep = 0;
  for (let i = 0; i < L.length; i++) { const f = fg[i] / Math.max(fs, 1), b = bg[i] / Math.max(bs, 1); L[i] = f > 0 ? clamp(f / (f + 3 * b + 1e-3), 0, 1) : 0; sep += f * L[i]; }   // colours also found around the box (water, foam) score low
  L.sep = sep;   // how clearly the boxed colours stand apart from their surroundings (spray or foam inside the box: lower)
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

// ---- camera: how the whole picture zoomed and moved between two sampled frames (drone closing in / pulling back) ----
const SW = 128;
/** A small gray copy of the frame (SW px wide), zero-mean, for the camera estimate. */
function smallGray(F0, W, H) {
  const k = W / SW, sh = Math.max(8, Math.round(H / k)), o = new Float32Array(SW * sh);
  for (let j = 0; j < sh; j++) for (let i = 0; i < SW; i++) {
    let s = 0, c = 0;
    for (let y = Math.floor(j * k), ye = Math.min(H, Math.floor((j + 1) * k) || 1); y < ye; y++) for (let x = Math.floor(i * k), xe = Math.min(W, Math.floor((i + 1) * k) || 1); x < xe; x++) { s += F0[y * W + x]; c++; }
    o[j * SW + i] = c ? s / c : 0;
  }
  let m = 0; for (const v of o) m += v; m /= o.length; for (let i = 0; i < o.length; i++) o[i] -= m;
  return { g: o, w: SW, h: sh };
}
function half(I) {
  const w = I.w >> 1, h = I.h >> 1, o = new Float32Array(w * h);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const k = 2 * j * I.w + 2 * i; o[j * w + i] = (I.g[k] + I.g[k + 1] + I.g[k + I.w] + I.g[k + I.w + 1]) / 4; }
  return { g: o, w, h };
}
const bil = (I, x, y) => {
  const x0 = Math.floor(x), y0 = Math.floor(y), fx = x - x0, fy = y - y0, k = y0 * I.w + x0;
  return (I.g[k] * (1 - fx) + I.g[k + 1] * fx) * (1 - fy) + (I.g[k + I.w] * (1 - fx) + I.g[k + I.w + 1] * fx) * fy;
};
/** Gauss-Newton fit of B(c + s(x-c) + t) = A(x) (robust weights: waves and foam that changed count less), on the
 *  picture AROUND the athlete: `ex` = {x0,y0,x1,y1} in small-image units is left out, since the athlete moves on its own.
 *  Returns {s, tx, ty} in units of the small image, or null when the fit is not trustworthy (e.g. a background with
 *  too little detail to tell how the camera moved: then the camera is assumed still). */
function fitMotion(A, B, ex, reg) {
  const PA = [A, half(A)], PB = [B, half(B)];
  let s = 1, tx = 0, ty = 0;
  for (let lv = 1; lv >= 0; lv--) {
    const a = PA[lv], b = PB[lv], cx = a.w / 2, cy = a.h / 2;
    if (lv === 0) { tx *= 2; ty *= 2; }
    for (let it = 0; it < 8; it++) {
      let h00 = 0, h01 = 0, h02 = 0, h11 = 0, h12 = 0, h22 = 0, g0 = 0, g1 = 0, g2 = 0, ss = 0, nn = 0;
      const f = lv ? 0.5 : 1;
      const X0 = Math.max(2, Math.floor(reg.x0 * f)), X1 = Math.min(a.w - 2, Math.ceil(reg.x1 * f)), Y0 = Math.max(2, Math.floor(reg.y0 * f)), Y1 = Math.min(a.h - 2, Math.ceil(reg.y1 * f));
      for (let y = Y0; y < Y1; y++) for (let x = X0; x < X1; x++) {
        if (ex && x >= ex.x0 * f && x <= ex.x1 * f && y >= ex.y0 * f && y <= ex.y1 * f) continue;
        const u = cx + s * (x - cx) + tx, v = cy + s * (y - cy) + ty;
        if (u < 1 || v < 1 || u >= b.w - 2 || v >= b.h - 2) continue;
        const r = bil(b, u, v) - a.g[y * a.w + x];
        const gx = (bil(b, u + 1, v) - bil(b, u - 1, v)) / 2, gy = (bil(b, u, v + 1) - bil(b, u, v - 1)) / 2;
        const w = 1 / (1 + (r / 12) ** 2);
        const j0 = gx * (x - cx) + gy * (y - cy);
        h00 += w * j0 * j0; h01 += w * j0 * gx; h02 += w * j0 * gy; h11 += w * gx * gx; h12 += w * gx * gy; h22 += w * gy * gy;
        g0 += w * j0 * r; g1 += w * gx * r; g2 += w * gy * r; ss += r * r; nn++;
      }
      if (nn < (X1 - X0) * (Y1 - Y0) * 0.3) return null;
      // enough detail in both directions (and for scale) to measure the camera; a flat sky/sea is not
      if (h11 / nn < 4 || h22 / nn < 4 || h00 / (nn * (a.w * a.w + a.h * a.h) / 12) < 0.5) return null;
      // solve H d = -g (3x3, Cramer)
      const det = h00 * (h11 * h22 - h12 * h12) - h01 * (h01 * h22 - h12 * h02) + h02 * (h01 * h12 - h11 * h02);
      if (Math.abs(det) < 1e-9) return null;
      const d0 = -(g0 * (h11 * h22 - h12 * h12) - h01 * (g1 * h22 - h12 * g2) + h02 * (g1 * h12 - h11 * g2)) / det;
      const d1 = -(h00 * (g1 * h22 - g2 * h12) - g0 * (h01 * h22 - h12 * h02) + h02 * (h01 * g2 - g1 * h02)) / det;
      const d2 = -(h00 * (h11 * g2 - h12 * g1) - h01 * (h01 * g2 - g1 * h02) + g0 * (h01 * h12 - h11 * h02)) / det;
      s += d0; tx += d1; ty += d2;
      if (!(Math.abs(s - 1) < 0.15) || Math.abs(tx) > a.w / 4 || Math.abs(ty) > a.h / 4) return null;
      if (Math.abs(d0) < 1e-5 && Math.abs(d1) < 0.01 && Math.abs(d2) < 0.01) break;
    }
  }
  return { s, tx, ty };
}
/**
 * The camera's zoom and pan between two frames. A real zoom scales the WHOLE picture about its centre, so the left,
 * right, top and bottom halves each show the same scale; moving water (waves running in different directions, a
 * breaking wave) can look like a zoom to a whole-picture fit, but its halves disagree. A scale is used only when all
 * four halves agree with it; otherwise the camera is taken as not zooming (live 0112: the box shrank ~1.5% per step
 * on a static shot of breaking waves). The pan is kept either way.
 */
function cameraMotion(A, B, ex) {
  const all = { x0: 0, y0: 0, x1: A.w, y1: A.h }, g = fitMotion(A, B, ex, all);
  if (!g || Math.abs(g.s - 1) < 0.002) return g;
  const hw = A.w / 2, hh = A.h / 2;
  const parts = [{ ...all, x1: hw }, { ...all, x0: hw }, { ...all, y1: hh }, { ...all, y0: hh }].map(r => fitMotion(A, B, ex, r));
  const agree = parts.every(p => p && (p.s - 1) / (g.s - 1) >= 0.2);   // each half zooms the same way, noticeably
  return agree ? g : { s: 1, tx: g.tx, ty: g.ty };
}

/**
 * Where the athlete AND their equipment are (surfer + board, player + ball close to them...): the connected blob of
 * pixels coloured like what the operator boxed, grown from the centre (look-alikes further away are separate blobs).
 * Measured on a grid that scales with the box, so small gaps (board / body / shorts) are bridged. Returns the blob's
 * extent (1st-99th percentile, robust to a stray pixel) in working pixels, or null when there is no clear blob.
 */
function extent(d, W, H, L, cx, cy, bw, bh) {
  const g = Math.max(1, Math.round(Math.min(bw, bh) / 20));
  const x0 = Math.max(0, Math.round(cx - bw * 2)), y0 = Math.max(0, Math.round(cy - bh * 2));
  const gw = Math.max(1, Math.ceil((Math.min(W, Math.round(cx + bw * 2)) - x0) / g)), gh = Math.max(1, Math.ceil((Math.min(H, Math.round(cy + bh * 2)) - y0) / g));
  const cnt = new Uint16Array(gw * gh), need = Math.max(1, Math.round(g * g * 0.15));
  for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) {
    let c = 0;
    for (let y = y0 + j * g, ye = Math.min(H, y + g); y < ye; y++) for (let x = x0 + i * g, xe = Math.min(W, x + g); x < xe; x++) {
      const k = (y * W + x) * 4; if (L[binOf(d[k], d[k + 1], d[k + 2])] >= 0.6) c++;
    }
    cnt[j * gw + i] = c >= need ? c : 0;
  }
  // the largest connected blob that reaches into the middle of the box (not just the cell nearest the centre: that can
  // be a lone bit of the head or a gap between body and board)
  const ci = (cx - x0) / g - 0.5, cj = (cy - y0) / g - 0.5, seen = new Uint8Array(gw * gh);
  let bestN = 0, hx = null, hy = null;
  for (let j0 = 0; j0 < gh; j0++) for (let i0 = 0; i0 < gw; i0++) {
    const k0 = j0 * gw + i0;
    if (!cnt[k0] || seen[k0] || Math.abs((i0 - ci) * g) > bw * 0.3 || Math.abs((j0 - cj) * g) > bh * 0.3) continue;
    const st = [k0], ax = new Float32Array(gw), ay = new Float32Array(gh); seen[k0] = 1; let n = 0;
    while (st.length) {
      const k = st.pop(), i = k % gw, j = (k - i) / gw; ax[i] += cnt[k]; ay[j] += cnt[k]; n += cnt[k];
      for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        const ii = i + di, jj = j + dj; if (ii < 0 || jj < 0 || ii >= gw || jj >= gh) continue;
        const kk = jj * gw + ii; if (!seen[kk] && cnt[kk]) { seen[kk] = 1; st.push(kk); }
      }
    }
    if (n > bestN) { bestN = n; hx = ax; hy = ay; }
  }
  if (!bestN) return null;
  const n = bestN;
  const q = (h, p) => { let a = 0; for (let i = 0; i < h.length; i++) { a += h[i]; if (a >= p * n) return i; } return h.length - 1; };
  // one cell more on every side: dark parts next to the coloured ones (head, shorts, a shadowed board edge) are inside
  return { n, x0: x0 + (q(hx, 0.01) - 1) * g, x1: x0 + (q(hx, 0.99) + 2) * g, y0: y0 + (q(hy, 0.01) - 1) * g, y1: y0 + (q(hy, 0.99) + 2) * g };
}

/**
 * Track a box from frame `from` (where the operator drew it) to frame `to` (inclusive, either direction).
 * @returns {Promise<{boxes: {frame:number,bbox:object,score:number}[], lost: number|null}>}
 */
export async function trackBox({ src, fps, from, to, bbox, step = 3, onProgress, signal, minScore = 0.45, hold, refs = [] }) {
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
    const bw0 = bw, bh0 = bh;
    const tw = clamp(Math.round(bw), 8, 72), th = clamp(Math.round(bh), 8, 72);
    const P0 = patch(F, W, H, bx, by, bw, bh, tw, th);
    const { wt, mask, fgFrac } = weights(P0, tw, th);
    const sumW = wt.reduce((a, b) => a + b, 0);
    const T0 = makeTemplate(P0, wt, sumW);
    if (T0.every(t => t.n < 0.5 * Math.sqrt(sumW))) throw new TrackError('FLAT', 'אין מספיק פרטים בתוך ה-BOX כדי לעקוב (צייר תיבה הדוקה יותר על הגולש)');
    const L = colourModel(RGB, W, H, bx, by, bw, bh, mask, tw, th);
    const mass0 = Math.max(1e-6, meanShift(RGB, W, H, L, bx + bw / 2, by + bh / 2, bw * 0.6, bh * 0.6).mass);
    let cam = smallGray(F[0], W, H);
    const recent = P0.map(c => Float32Array.from(c));
    // the athlete + equipment blob at the drawn box: how much of the drawn box it fills, to keep the same margin later
    // The athlete's extent is measured with the colours of the CLEANEST box the operator drew (`refs`: other drawn boxes
    // of this athlete), not necessarily this one: a correction made in spray learns foam as "athlete".
    let LX = L, ref = { bw, bh, e: extent(RGB, W, H, L, bx + bw / 2, by + bh / 2, bw, bh) };
    for (const r of refs.slice(0, 4)) {
      if (signal?.aborted) break;
      await seek(v, at(r.frame));
      const F2 = features(ctx, v, W, H), D2 = readRGB(ctx, W, H);
      const rx = r.bbox.x * W, ry = r.bbox.y * H, rw = Math.max(6, r.bbox.w * W), rh = Math.max(6, r.bbox.h * H);
      const L2 = colourModel(D2, W, H, rx, ry, rw, rh, weights(patch(F2, W, H, rx, ry, rw, rh, tw, th), tw, th).mask, tw, th);
      if (L2.sep > LX.sep + 0.05) { const e2 = extent(D2, W, H, L2, rx + rw / 2, ry + rh / 2, rw, rh); if (e2) { LX = L2; ref = { bw: rw, bh: rh, e: e2 }; } }
    }
    if (refs.length) { await seek(v, at(from)); F = features(ctx, v, W, H); RGB = readRGB(ctx, W, H); }
    const b0 = ref.e;
    const pad = b0 ? clamp(Math.max(ref.bw / (b0.x1 - b0.x0), ref.bh / (b0.y1 - b0.y0)), 1.06, 1.6) : 1.15;   // drawn box / blob
    const grow = { l: 0, t: 0, r: 0, b: 0 };
    let camAcc = 1, camSteps = 0;   // camera zoom applied since the last check against the athlete's own look   // how far the box reaches past the tracked box, per side (smoothed)
    let dens = b0 ? b0.n / (ref.bw * ref.bh) : 0;   // how densely the athlete's colours fill a box drawn around them
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

    // The stored box should hold the whole athlete and equipment (surfer + board): the tracked box, grown on a side
    // where the athlete's colour blob reaches past it (they turn, stand up, come closer). On real footage the blob also
    // catches wake, foam and spray, so the growth is kept modest and steady: at most a quarter of the box per side,
    // smoothed over time, and starting gradually away from each drawn box (the box the operator drew is the size it is).
    // A blob that is thin (spray hides part of the athlete) or far larger than the athlete is ignored.
    function contain(cx, cy, f) {
      const e = extent(RGB, W, H, LX, cx, cy, bw, bh), ew = e && e.x1 - e.x0, eh = e && e.y1 - e.y0;
      const d = e ? e.n / (bw * bh) : 0, big = 3 * Math.max(bw, bh);   // the athlete may turn: a flat drawn box is short, not they
      const ok = e && b0 && d > 0.6 * dens && ew < big && eh < big;
      if (e) dens = 0.85 * dens + 0.15 * d;   // follows slow changes (the athlete turns, comes closer), not a sudden drop
      const cap = 0.25, want = { l: 0, t: 0, r: 0, b: 0 };
      if (ok) {
        const mx = (pad - 1) / 2 * ew, my = (pad - 1) / 2 * eh;
        want.l = clamp((bx - (e.x0 - mx)) / bw, 0, cap); want.r = clamp((e.x1 + mx - bx - bw) / bw, 0, cap);
        want.t = clamp((by - (e.y0 - my)) / bh, 0, cap); want.b = clamp((e.y1 + my - by - bh) / bh, 0, cap);
      }
      for (const k of ['l', 't', 'r', 'b']) grow[k] = ok ? 0.7 * grow[k] + 0.3 * want[k] : 0.85 * grow[k];
      const ramp = Math.min(1, Math.abs(f - from) / (5 * step));
      let L0 = bx - grow.l * ramp * bw, T0 = by - grow.t * ramp * bh, R0 = bx + bw + grow.r * ramp * bw, B0 = by + bh + grow.b * ramp * bh;
      L0 = clamp(L0, 0, W - 1); T0 = clamp(T0, 0, H - 1); R0 = clamp(R0, L0 + 1, W); B0 = clamp(B0, T0 + 1, H);   // always inside the picture
      return { x: L0 / W, y: T0 / H, w: (R0 - L0) / W, h: (B0 - T0) / H };
    }

    async function one(f) {
      while (hold?.() && !signal?.aborted) await new Promise(r => setTimeout(r, 250));   // yield the network to the player
      await seek(v, at(f));
      F = features(ctx, v, W, H); RGB = readRGB(ctx, W, H);
      // the camera: move and scale the box with the picture (zoom in -> the athlete and the box grow together)
      const kk = W / SW, ex = { x0: (bx - bw) / kk, y0: (by - bh) / kk, x1: (bx + 2 * bw) / kk, y1: (by + 2 * bh) / kk };   // the athlete and around it
      const cam1 = smallGray(F[0], W, H), m = cameraMotion(cam, cam1, ex); cam = cam1;
      if (m) {
        const k = W / SW, ox = W / 2, oy = cam1.h * k / 2;
        const ncx = ox + m.s * (bx + bw / 2 - ox) + m.tx * k, ncy = oy + m.s * (by + bh / 2 - oy) + m.ty * k;
        const z = clamp(m.s, 0.25 * bw0 / bw, 6 * bw0 / bw);
        bw = clamp(bw * z, 6, W); bh = clamp(bh * z, 6, H); bx = clamp(ncx - bw / 2, 0, W - bw); by = clamp(ncy - bh / 2, 0, H - bh);
        camAcc *= z;
      }
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
      // size: the camera zoom is already applied (above); here only a small change for the athlete's own pose
      let scx = 1, scy = 1, sb = best.raw;
      for (const s2 of [0.95, 1.05]) {
        if (bw * s2 / bw0 < 0.25 || bw * s2 / bw0 > 6) continue;
        const v2 = nccPatch(patch(F, W, H, cx - bw * s2 / 2, cy - bh * s2 / 2, bw * s2, bh * s2, tw, th), T, wt, sumW);
        if (v2 > sb + 0.03) { sb = v2; scx = scy = s2; }
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
      const nw = clamp(bw * scx, 6, W), nh = clamp(bh * scy, 6, H), nx = clamp(cx - nw / 2, 0, W - nw), ny = clamp(cy - nh / 2, 0, H - nh);
      const n1 = miss + 1;
      vx = 0.5 * vx + 0.5 * (nx - bx) / n1; vy = 0.5 * vy + 0.5 * (ny - by) / n1;
      const vmax = 0.35 * Math.hypot(bw, bh), vm = Math.hypot(vx, vy); if (vm > vmax) { vx *= vmax / vm; vy *= vmax / vm; }   // no runaway prediction
      bx = nx; by = ny; bw = nw; bh = nh; miss = 0; lastGood = f;
      // every few steps: if the box fits the athlete better without the zoom the camera estimate added since the last
      // check, that zoom was the water moving, not the camera (live 0112: the box shrank ~1.5% per step): undo it
      if (++camSteps >= 5) {
        if (Math.abs(Math.log(camAcc)) > 0.02 && sb > 0.5) {
          const ow = clamp(bw / camAcc, 6, W), oh = clamp(bh / camAcc, 6, H), cx2 = bx + bw / 2, cy2 = by + bh / 2;
          const vNow = nccPatch(patch(F, W, H, bx, by, bw, bh, tw, th), T, wt, sumW), vOld = nccPatch(patch(F, W, H, cx2 - ow / 2, cy2 - oh / 2, ow, oh, tw, th), T, wt, sumW);
          if (vOld > vNow + 0.01) { bw = ow; bh = oh; bx = clamp(cx2 - bw / 2, 0, W - bw); by = clamp(cy2 - bh / 2, 0, H - bh); }
        }
        camAcc = 1; camSteps = 0;
      }
      out.push({ frame: f, score: +conf.toFixed(3), bbox: contain(bx + bw / 2, by + bh / 2, f) });
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

// for tests (pure functions, no browser needed)
export const _camera = { cameraMotion, smallGray, fit: fitMotion };
