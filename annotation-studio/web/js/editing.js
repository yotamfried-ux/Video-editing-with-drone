// Editing Review: synchronized source + rendered output with EDL-verified overlays and metrics.
import { h, $, api, ltr, pill, toast, timecode } from './ui.js';
import { setTopbar } from './main.js';

let E = null, cleanup = [];
export function teardownEditing() { cleanup.forEach(f => f()); cleanup = []; E = null; }
const svgEl = (t, a) => { const e = document.createElementNS('http://www.w3.org/2000/svg', t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
const ERR_HE = { missing_surfer: 'גולש חסר', partial_clipping: 'חיתוך חלקי', edge_violation: 'חריגת שוליים', centering_error: 'סטיית מרכוז', crop_jump: 'קפיצת חיתוך', wrong_surfer: 'גולש שגוי' };
const fx = v => v == null ? '—' : (v * 100).toFixed(1) + '%';

export async function renderEditing(root, id) {
  setTopbar(h('strong', {}, 'בקרת עריכה'), pill('מקור מול פלט מרונדר'));
  const outs = (await api('/api/outputs')).items;
  if (!outs.length) return root.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'empty' }, 'אין פלטים עם EDL. ללא EDL לא ניתן לבצע הערכה מדויקת — מיפוי חזותי הוא חלופה בביטחון נמוך בלבד ומסומן "לא מאומת".')));
  id = id || outs[0].id;
  const rv = await api(`/api/outputs/${id}/review`);
  const firstSha = rv.frames.find(x => x.sha && rv.sources[x.sha])?.sha ?? Object.keys(rv.sources)[0];
  const src = firstSha ? rv.sources[firstSha] : null;
  E = { id, rv, src, sources: rv.sources, curSha: firstSha, f: 0, frames: rv.frames, fps: rv.edl.output.fps, proposal: null, playing: false };
  const sel = h('select', { 'aria-label': 'פלט', onchange: e => { location.hash = `#/editing/${e.target.value}`; } }, outs.map(o => h('option', { value: o.id, selected: o.id === id }, `${o.output_id} · ${o.mode}`)));
  const verified = rv.verified !== false && rv.report.mapping === 'verified';
  root.replaceChildren(h('div', { class: 'editgrid', 'data-testid': 'editing' },
    vbox('מקור', 'srcv', src ? src.playback_url : null, 'srcsvg', 'מקור (שחזור מארכיון מוגן)'),
    vbox('פלט מרונדר', 'outv', rv.edl.output_file ? `/media/${id}/out` : null, 'outsvg', 'פלט'),
    h('div', { class: 'side', id: 'side' })));
  bind(); paintSide(sel, verified); seek(0);
}
function vbox(title, vid, url, svgId, cap) {
  return h('div', { class: 'vbox' }, h('div', { class: 'cap' }, title), h('div', { class: 'stage-wrap', style: { flex: 1 } },
    h('div', { class: 'stage', id: `${vid}-stage` }, url ? h('video', { id: vid, src: url, muted: true, playsinline: true, preload: 'auto', 'aria-label': cap }) : h('div', { class: 'empty', style: { margin: '30%' } }, 'אין וידאו זמין'),
      h('div', { class: 'ov', id: `${vid}-ov` }, h('svg', { id: svgId, viewBox: '0 0 1 1', preserveAspectRatio: 'none' })))));
}
function place(vidId) {
  const v = $(`#${vidId}`), ov = $(`#${vidId}-ov`), st = $(`#${vidId}-stage`); if (!v || !v.videoWidth) return;
  const r = v.getBoundingClientRect(), p = st.getBoundingClientRect(), sc = Math.min(r.width / v.videoWidth, r.height / v.videoHeight), w = v.videoWidth * sc, hh = v.videoHeight * sc;
  Object.assign(ov.style, { left: `${r.left - p.left + (r.width - w) / 2}px`, top: `${r.top - p.top + (r.height - hh) / 2}px`, width: `${w}px`, height: `${hh}px` });
}
function bind() {
  for (const id of ['srcv', 'outv']) { const v = $(`#${id}`); if (v) { v.addEventListener('loadedmetadata', () => { place(id); paintOverlays(); }); new ResizeObserver(() => { place(id); }).observe($(`#${id}-stage`)); } }
  const kd = e => {
    if (!E || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); seek(E.f + (e.shiftKey ? 10 : 1)); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); seek(E.f - (e.shiftKey ? 10 : 1)); }
    else if (e.key === ' ') { e.preventDefault(); play(); }
  };
  window.addEventListener('keydown', kd); cleanup.push(() => window.removeEventListener('keydown', kd));
}
function seek(f) {
  if (!E) return;
  E.f = Math.max(0, Math.min(E.frames.length ? E.frames[E.frames.length - 1].f : 0, Math.round(f)));
  const row = E.frames.find(x => x.f === E.f), ov = $('#outv'), sv = $('#srcv');
  if (ov) { ov.pause(); ov.currentTime = (E.f + 0.5) / E.fps; }
  if (sv && row) { sv.pause(); pointSource(row, sv); }
  paintOverlays(); paintMeta();
}
/** Point the source player at the exact source frame of an output row, switching file for multi-source reels. */
function pointSource(row, sv) {
  const info = E.sources[row.sha];
  if (!info) return;
  const t = (row.src + 0.5) / (info.fps_num / info.fps_den);
  if (E.curSha !== row.sha) {
    E.curSha = row.sha; E.src = info;
    sv.addEventListener('loadedmetadata', () => { sv.currentTime = t; place('srcv'); paintOverlays(); }, { once: true });
    sv.src = info.playback_url;
  } else sv.currentTime = t;
}
function play() {
  const ov = $('#outv'); if (!ov) return;
  if (!ov.paused) { ov.pause(); E.playing = false; return; }
  E.playing = true; ov.play();
  const tick = () => { if (!E || !E.playing || ov.paused) { if (E) E.playing = false; return; } E.f = Math.floor(ov.currentTime * E.fps); const row = E.frames.find(x => x.f === E.f), sv = $('#srcv'); if (row && sv) pointSource(row, sv); paintOverlays(); paintMeta(); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}
function paintOverlays() {
  const row = E.frames.find(x => x.f === E.f), edl = E.rv.edl;
  const s = $('#srcsvg'), o = $('#outsvg'); if (!s || !o) return;
  s.replaceChildren(); o.replaceChildren();
  if (!row) return;
  const dims = E.sources[row.sha] ?? edl.source, SW = dims.width, SH = dims.height, OW = edl.output.width, OH = edl.output.height;
  const c = row.crop;
  s.append(svgEl('rect', { x: (c.cx - c.w / 2) / SW, y: (c.cy - c.h / 2) / SH, width: c.w / SW, height: c.h / SH, fill: 'none', stroke: '#ffd166', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke', 'data-testid': 'crop-rect' }));
  if (row.reviewed) {
    const b = row.src_bbox;
    s.append(svgEl('rect', { x: b.x, y: b.y, width: b.w, height: b.h, fill: 'none', stroke: '#3ddc97', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke', 'data-testid': 'gt-box' }));
    const m = E.rv.report.thresholds.safe_margin;
    o.append(svgEl('rect', { x: m, y: m, width: 1 - 2 * m, height: 1 - 2 * m, fill: 'none', stroke: '#8c97a8', 'stroke-dasharray': '6 4', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke' }));
    o.append(svgEl('rect', { x: row.box.x1 / OW, y: row.box.y1 / OH, width: (row.box.x2 - row.box.x1) / OW, height: (row.box.y2 - row.box.y1) / OH, fill: 'none', stroke: '#3ddc97', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke', 'data-testid': 'out-box' }));
    const cx = (row.box.x1 + row.box.x2) / 2 / OW, cy = (row.box.y1 + row.box.y2) / 2 / OH;
    o.append(svgEl('circle', { cx, cy, r: 0.012, fill: '#3ddc97' }));
    if (row.target) { o.append(svgEl('path', { d: `M${row.target.x - 0.03} ${row.target.y}H${row.target.x + 0.03}M${row.target.x} ${row.target.y - 0.02}V${row.target.y + 0.02}`, stroke: '#ff6b6b', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke' })); o.append(svgEl('line', { x1: cx, y1: cy, x2: row.target.x, y2: row.target.y, stroke: '#ff6b6b', 'stroke-dasharray': '3 3', 'vector-effect': 'non-scaling-stroke' })); }
  }
  if (E.proposal) { const p = E.proposal; s.append(svgEl('rect', { x: (p.cx - p.w / 2) / SW, y: (p.cy - p.h / 2) / SH, width: p.w / SW, height: p.h / SH, fill: 'rgba(76,201,240,.15)', stroke: '#4cc9f0', 'stroke-dasharray': '6 4', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke', 'data-testid': 'proposal-rect' })); drawPreview(); }
  place('srcv'); place('outv');
}
function drawPreview() {
  const cv = $('#prev'), sv = $('#srcv'); if (!cv || !sv || !E.proposal || !sv.videoWidth) return;
  const p = E.proposal, k = sv.videoWidth / (E.sources[E.curSha]?.width ?? E.rv.edl.source.width), ctx = cv.getContext('2d');
  ctx.drawImage(sv, (p.cx - p.w / 2) * k, (p.cy - p.h / 2) * k, p.w * k, p.h * k, 0, 0, cv.width, cv.height);
}
function paintMeta() {
  const row = E.frames.find(x => x.f === E.f), el = $('#meta'); if (!el) return;
  el.replaceChildren(ltr(`out f${E.f} · ${timecode(E.f, E.fps)}`), ' → ', row ? ltr(`src f${row.src}`) : '—', row?.blend ? ' · מעבר בין קליפים (לא נמדד)' : row?.reviewed ? ` · נראות ${fx(row.vis)}${row.err != null ? ` · סטיית מרכוז ${row.err.toFixed(3)}` : ''}${row.origin !== 'manual' ? ' · משוער' : ''}` : ' · לא נבדק');
  for (const p of E.phs ?? []) { p.setAttribute('x1', E.f); p.setAttribute('x2', E.f); }
}
function chart(title, key, max, color) {
  const n = E.frames.length, svg = svgEl('svg', { class: 'chart', viewBox: `0 0 ${n} 1`, preserveAspectRatio: 'none', 'data-testid': `chart-${key}` });
  let d = '', pen = false;
  for (const r of E.frames) { const v = r.reviewed ? r[key] : null; if (v == null) { pen = false; continue; } const y = 1 - Math.min(1, v / max); d += `${pen ? 'L' : 'M'}${r.f} ${(0.04 + 0.92 * y).toFixed(4)}`; pen = true; }
  svg.append(svgEl('path', { d, fill: 'none', stroke: color, 'stroke-width': 1.6, 'vector-effect': 'non-scaling-stroke' }));
  for (const r of E.frames) if (r.cut) svg.append(svgEl('line', { x1: r.f, x2: r.f, y1: 0, y2: 1, stroke: '#8c97a8', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke', 'stroke-dasharray': '2 3' }));
  const ph = svgEl('line', { x1: 0, x2: 0, y1: 0, y2: 1, stroke: '#ff6b6b', 'stroke-width': 1.5, 'vector-effect': 'non-scaling-stroke' }); ph.classList.add('chart-ph'); svg.append(ph);
  (E.phs ??= []).push(ph); svg.addEventListener('click', ev => { const r = svg.getBoundingClientRect(); seek(((ev.clientX - r.left) / r.width) * n); });
  return h('div', {}, h('div', { class: 'meta' }, title), svg);
}
function paintSide(sel, verified) {
  const r = E.rv.report, side = $('#side'), edl = E.rv.edl;
  E.phs = [];
  const errs = r.errors ?? [];
  side.replaceChildren(
    h('div', {}, sel),
    h('div', { class: 'toolbar', style: { margin: 0 } }, verified ? pill('מיפוי מאומת (EDL)', 'ok') : pill('מיפוי לא מאומת — אין ציון מדויק', 'bad'), pill(edl.mode === 'contain' ? 'Contain' : edl.mode === 'tracked_crop' ? 'חיתוך עוקב' : edl.mode === 'mixed' ? 'משולב' : 'Pad'), ltr(edl.pipeline_commit ? `commit ${String(edl.pipeline_commit).slice(0, 8)}` : ''), ltr(`${edl.output.width}×${edl.output.height}`)),
    h('div', { class: 'mono meta', id: 'meta', 'data-testid': 'editmeta' }),
    h('div', { class: 'toolbar', style: { margin: 0 } }, h('button', { class: 'btn sm', onclick: () => seek(E.f - 1) }, '◀|'), h('button', { class: 'btn sm', 'data-testid': 'edit-play', onclick: play }, '▶ / ❚❚'), h('button', { class: 'btn sm', onclick: () => seek(E.f + 1) }, '|▶')),
    (rv0 => rv0.unresolved?.length ? h('div', { class: 'banner warn', 'data-testid': 'unresolved-sources' }, `${rv0.unresolved.length} מקורות אינם ניתנים להערכה: ${rv0.unresolved.map(u => u.reason === 'no_approved_revision' ? 'אין גרסה מאושרת' : 'המקור אינו בקטלוג').join(', ')}`) : null)(E.rv),
    !verified ? h('div', { class: 'banner bad' }, 'לא ניתן לחשב מדדי מרכוז/נראות ללא EDL מאומת. ', h('code', {}, r.reason ?? 'EDL_UNVERIFIED')) : metrics(r),
    verified ? h('div', {}, chart('סטיית מרכוז (מנורמל)', 'err', 0.5, '#ffa657'), chart('נראות הגולש בפלט', 'vis', 1, '#3ddc97')) : null,
    verified ? h('div', {}, h('b', {}, `ציר שגיאות (${errs.length})`), h('div', { style: { maxHeight: '180px', overflow: 'auto' } }, h('table', { class: 't', 'data-testid': 'error-table' }, h('tbody', {}, errs.length ? summarize(errs).map(g => h('tr', { class: 'err-row', 'data-testid': 'err-row', onclick: () => seek(g.out_frame) }, h('td', {}, pill(ERR_HE[g.type] ?? g.type, 'warn')), h('td', {}, ltr(`out ${g.out_frame}${g.count > 1 ? `–${g.out_frame + g.count - 1}` : ''}`)), h('td', {}, ltr(`src ${g.src_frame}`)))) : [h('tr', {}, h('td', {}, 'אין שגיאות'))])))) : null,
    verified ? altCrop() : null);
}
function summarize(errs) { // collapse consecutive frames of the same type into one jump-target row
  const out = []; for (const e of errs) { const l = out.find(g => g.type === e.type && g.out_frame + g.count === e.out_frame); if (l) l.count++; else out.push({ ...e, count: 1 }); } return out;
}
function metrics(r) {
  const v = r.visibility, c = r.centering;
  return h('div', { class: 'stats', style: { margin: 0 } }, [['כיסוי הערכה', fx(r.coverage.coverage_ratio)], ['פריימי מעבר', r.coverage.blend_frames ?? 0], ['נראה במלואו', fx(v.fully_visible)], ['חתוך חלקית', fx(v.partially_clipped)], ['חסר', fx(v.missing)], ['מרכוז (חציון)', c.scored_frames ? c.median.toFixed(3) : 'לא נמדד'], ['p95', c.scored_frames ? c.p95.toFixed(3) : '—'], ['קפיצות חיתוך', r.smoothness.crop_jumps], ['חריגות שוליים', fx(r.edge_violation_share)]].map(([l, x]) => h('div', { class: 'stat', style: { minWidth: '90px', padding: '6px 10px' } }, h('b', { style: { fontSize: '16px' } }, x), h('span', {}, l))));
}
function altCrop() {
  const cv = h('canvas', { id: 'prev', width: 180, height: 320, style: { background: '#000', borderRadius: '6px', border: '1px solid var(--line)' }, 'aria-label': 'תצוגה מקדימה של חיתוך חלופי' });
  return h('div', {}, h('b', {}, 'חיתוך חלופי (הצעה בלבד)'), h('div', { class: 'meta' }, 'לא משנה את הסרטון, הפלט או התוויות. אישור יוצר רשומה חדשה.'),
    h('div', { class: 'toolbar', style: { margin: '6px 0' } },
      h('button', { class: 'btn sm', 'data-testid': 'propose', onclick: async () => {
        const row = E.frames.find(x => x.f === E.f && x.reviewed); if (!row) return toast('בפריים זה אין תיבת אמת נבדקת', true);
        const mode = row.framing_mode === 'directional_lead_room' && row.target ? 'directional_lead_room' : 'geometric_center';
        try { const r = await api('/api/editing/proposals', { method: 'POST', body: { source_id: E.sources[row.sha].id, bbox: row.src_bbox, mode, target: row.target } }); E.proposal = { ...r.proposal, id: r.id }; paintOverlays(); toast('הצעת חיתוך נוצרה (טרם אושרה)'); paintProposalState(); } catch (e) { toast(e.message, true); } } }, 'הצע חיתוך'),
      h('button', { class: 'btn sm primary', id: 'approve-prop', disabled: true, 'data-testid': 'approve-crop', onclick: async () => { try { await api(`/api/editing/proposals/${E.proposal.id}/approve`, { method: 'POST', body: {} }); toast('נשמרה גרסת עריכה מאושרת חדשה'); } catch (e) { toast(e.message, true); } } }, 'אשר כדוגמה')),
    cv);
}
function paintProposalState() { const b = $('#approve-prop'); if (b) b.disabled = !E.proposal; }
