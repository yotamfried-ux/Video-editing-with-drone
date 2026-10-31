// Precision Annotation Workbench: video + frame-accurate multitrack timeline + inspector.
import { h, $, api, ltr, pill, toast, dialog, closeDialog, timecode, fpsOf, uid, fmtDate, eventHe, eventOptions, eventInfo, sportName, sportsList, DECISION_HE, STATUS_HE, STATUS_CLASS } from './ui.js';
import { setTopbar, rememberSource } from './main.js';

const SPEEDS = [0.25, 0.5, 1, 2];
const COLORS = ['var(--ath1)', 'var(--ath2)', 'var(--ath3)', 'var(--ath4)'];
let S = null, cleanup = [];
const LEGACY = ['wave_ride', 'failed_takeoff', 'wipeout', 'paddle_out', 'other'];
const effSport = x => x.sport_id ?? S.src.primary_sport_id ?? null;

export function teardownAnnotate() { cleanup.forEach(f => f()); cleanup = []; S = null; }
const on = (t, ev, fn, o) => { t.addEventListener(ev, fn, o); cleanup.push(() => t.removeEventListener(ev, fn, o)); };

export async function renderAnnotate(root, id) {
  if (!id) {
    const r = await api('/api/sources?limit=1&status=not_annotated');
    if (r.items[0]) { location.hash = `#/annotate/${r.items[0].id}`; return; }
    root.append(h('div', { class: 'page' }, h('div', { class: 'empty' }, 'בחר סרטון מהספרייה כדי להתחיל', h('p', {}, h('a', { class: 'btn primary', href: '#/library' }, 'לספרייה'))))); return;
  }
  rememberSource(id);
  const [src, draft, athletes, revs] = await Promise.all([api(`/api/sources/${id}`), api(`/api/sources/${id}/draft`), api('/api/athletes'), api(`/api/sources/${id}/revisions`)]);
  S = {
    src, fps: fpsOf(src), total: src.frame_count, draft, athletes: athletes.items, revs: revs.items,
    sel: null, frame: 0, ppf: 6, mark: { in: null, out: null }, tool: 'select', speed: 1, save: 'saved', dirty: 0, inflight: false,
    undo: [], redo: [], saveTimer: null, retryTimer: null, insp: true, overlay: true, banner: null, playing: false, root,
  };
  restorePending();
  root.replaceChildren(layout());
  mountVideo();
  bindKeys();
  fit();
  refresh();
  cleanup.push(() => { clearTimeout(S?.saveTimer); clearTimeout(S?.retryTimer); });
}

// ---------------- state helpers ----------------
const C = () => S.draft.content;
const seg = id => C().segments.find(s => s.id === id);
const selSeg = () => S.sel && seg(S.sel);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const athName = id => S.athletes.find(a => a.id === id)?.label ?? 'לא ידוע';
const athColor = id => { const i = S.athletes.findIndex(a => a.id === id); return i < 0 ? 'var(--muted)' : COLORS[i % COLORS.length]; };

function snapshot() { S.undo.push(JSON.stringify(C())); if (S.undo.length > 100) S.undo.shift(); S.redo = []; }
function edit(fn, { quiet = false } = {}) { snapshot(); fn(C()); changed(); if (!quiet) refresh(); }
function changed() { S.dirty++; setSave('dirty'); clearTimeout(S.saveTimer); S.saveTimer = setTimeout(save, 700); persistPending(); }
function undo(redo = false) {
  const from = redo ? S.redo : S.undo, to = redo ? S.undo : S.redo;
  if (!from.length) return;
  to.push(JSON.stringify(C())); S.draft.content = JSON.parse(from.pop());
  if (S.sel && !seg(S.sel)) S.sel = null;
  changed(); refresh();
}

// ---------------- durable draft queue + autosave ----------------
const pendKey = () => `studio.pending.${S.src.id}`;
function persistPending() { try { localStorage.setItem(pendKey(), JSON.stringify({ base: S.draft.version, content: C(), at: Date.now() })); } catch {} }
function clearPending() { try { localStorage.removeItem(pendKey()); } catch {} }
function restorePending() {
  try {
    const p = JSON.parse(localStorage.getItem(pendKey()) ?? 'null');
    if (!p) return;
    if (JSON.stringify(p.content) === JSON.stringify(C())) return clearPending();
    if (p.base === S.draft.version) { S.draft.content = p.content; S.dirty++; S.banner = { kind: 'warn', text: 'שוחזרה טיוטה מקומית שלא נשמרה בשרת — נשמרת כעת.' }; setTimeout(save, 300); }
    else S.banner = { kind: 'bad', text: 'קיימת טיוטה מקומית ישנה שמתנגשת עם גרסת השרת.', action: ['השתמש בטיוטה המקומית', () => { S.draft.content = p.content; S.banner = null; changed(); refresh(); }], action2: ['השלך', () => { clearPending(); S.banner = null; refresh(); }] };
  } catch {}
}
function setSave(state) { S.save = state; const el = $('#savepill'); if (el) paintSave(el); }
const SAVE_UI = { saved: ['נשמר', 'ok'], dirty: ['שינויים לא שמורים', 'warn'], saving: ['שומר…', 'busy'], offline: ['לא מקוון — ממתין לשליחה', 'warn'], conflict: ['התנגשות גרסאות', 'bad'], failed: ['שמירה נכשלה', 'bad'] };
function paintSave(el) { const [t, c] = SAVE_UI[S.save]; el.className = `pill ${c}`; el.replaceChildren(h('span', { class: 'dot' }), t); el.dataset.state = S.save; }

async function save() {
  if (!S || S.inflight || S.save === 'conflict') return;
  const mySeq = S.dirty; S.inflight = true; setSave('saving');
  try {
    const r = await api(`/api/sources/${S.src.id}/draft`, { method: 'PUT', body: { expected_version: S.draft.version, content: C() } });
    S.draft.version = r.version; S.inflight = false;
    if (S.dirty !== mySeq) { setSave('dirty'); S.saveTimer = setTimeout(save, 200); } else { setSave('saved'); clearPending(); }
    paintStatus();
  } catch (e) {
    S.inflight = false;
    if (e.code === 'VERSION_CONFLICT') { setSave('conflict'); S.banner = { kind: 'bad', text: e.message, action: ['טען גרסת שרת', reloadServer], action2: ['דרוס עם הגרסה שלי', async () => { const d = await api(`/api/sources/${S.src.id}/draft`); S.draft.version = d.version; S.save = 'dirty'; S.banner = null; save(); refresh(); }] }; refresh(); }
    else if (e.status && e.status < 500 && e.status !== 0) { setSave('failed'); toast(e.message, true); }
    else { setSave('offline'); clearTimeout(S.retryTimer); S.retryTimer = setTimeout(save, 3000); }
  }
}
async function reloadServer() { const d = await api(`/api/sources/${S.src.id}/draft`); S.draft = d; clearPending(); S.banner = null; S.save = 'saved'; S.sel = null; refresh(); }

// ---------------- layout ----------------
function layout() {
  return h('div', { class: 'wb', id: 'wb', 'data-testid': 'workbench' },
    h('div', { class: 'wb-main' },
      h('div', { class: 'stage-wrap' }, h('div', { class: 'stage', id: 'stage' },
        h('video', { id: 'vid', muted: true, playsinline: true, preload: 'auto', 'aria-label': 'נגן וידאו' }),
        h('div', { class: 'ov', id: 'ov' }, h('svg', { id: 'ovsvg', viewBox: '0 0 100 100' })),
        h('div', { class: 'hud' }, h('span', { class: 'pill mono', id: 'hudfr' }, ''), h('span', { class: 'pill', id: 'hudtool' }, '')))),
      h('div', { class: 'controls', id: 'controls', role: 'toolbar', 'aria-label': 'בקרת נגן' }),
      h('div', { class: 'tl', id: 'tl' },
        h('div', { class: 'tl-labels', id: 'tllabels' }),
        h('div', { class: 'tl-scroll', id: 'tlscroll' }, h('div', { class: 'tl-inner', id: 'tlinner' })))),
    h('aside', { class: 'insp', id: 'insp', 'aria-label': 'מפקח' }));
}

function mountVideo() {
  const v = $('#vid'); v.src = S.src.playback_url;
  v.addEventListener('loadedmetadata', () => { placeOverlay(); refresh(); });
  v.addEventListener('seeked', () => { syncFrameFromVideo(); });
  v.addEventListener('play', () => { S.playing = true; loop(); paintControls(); });
  v.addEventListener('pause', () => { S.playing = false; syncFrameFromVideo(); paintControls(); });
  new ResizeObserver(() => { placeOverlay(); fit(false); }).observe($('#stage'));
  on(document, 'visibilitychange', () => { if (document.hidden) v.pause(); });
}
function loop() {
  const v = $('#vid'); if (!v) return;
  const tick = () => { if (!S?.playing) return; syncFrameFromVideo(true); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}
function syncFrameFromVideo(light) {
  const v = $('#vid'); if (!v || !S) return;
  const f = clamp(Math.floor(v.currentTime * S.fps + 1e-3), 0, S.total - 1);
  if (f !== S.frame) { S.frame = f; light ? paintPlayhead() : refresh(); }
}
export function seekFrame(f, { keepPlaying = false } = {}) {
  S.frame = clamp(Math.round(f), 0, S.total - 1);
  const v = $('#vid'); if (!keepPlaying) v.pause();
  v.currentTime = (S.frame + 0.5) / S.fps; // mid-frame => exact frame, never a neighbour
  paintPlayhead(); paintControls(); paintOverlay(); paintHud();
}
function placeOverlay() {
  const v = $('#vid'), ov = $('#ov'); if (!v || !v.videoWidth) return;
  const r = v.getBoundingClientRect(), p = $('#stage').getBoundingClientRect();
  const sc = Math.min(r.width / v.videoWidth, r.height / v.videoHeight), w = v.videoWidth * sc, hh = v.videoHeight * sc;
  Object.assign(ov.style, { left: `${r.left - p.left + (r.width - w) / 2}px`, top: `${r.top - p.top + (r.height - hh) / 2}px`, width: `${w}px`, height: `${hh}px` });
}

// ---------------- controls ----------------
function paintControls() {
  const c = $('#controls'); if (!c) return;
  const btn = (label, fn, title, extra = {}) => h('button', { class: 'btn sm', title, 'aria-label': title, onclick: fn, ...extra }, label);
  c.replaceChildren(
    btn(S.playing ? '❚❚' : '▶', togglePlay, 'ניגון / השהיה (רווח)', { 'data-testid': 'play' }),
    btn('◀|', () => step(-1), 'פריים אחורה (←)', { 'data-testid': 'step-back' }), btn('|▶', () => step(1), 'פריים קדימה (→)', { 'data-testid': 'step-fwd' }),
    h('span', { class: 'tc mono', 'data-testid': 'timecode' }, timecode(S.frame, S.fps)),
    h('span', { class: 'fr mono', 'data-testid': 'framenum' }, `frame ${S.frame} / ${S.total}`),
    h('span', { class: 'sep' }),
    h('div', { class: 'seg-ctl', role: 'group', 'aria-label': 'מהירות ניגון' }, SPEEDS.map(s => h('button', { 'aria-pressed': String(S.speed === s), onclick: () => setSpeed(s), 'data-testid': `speed-${s}` }, `${s}×`))),
    h('span', { class: 'sep' }),
    btn('[ I', () => markIn(), 'סימון תחילה (I)', { 'data-testid': 'mark-in' }), btn('O ]', () => markOut(), 'סימון סוף (O)', { 'data-testid': 'mark-out' }),
    h('span', { class: 'fr mono' }, S.mark.in != null ? `in ${S.mark.in}` : 'in —', ' · ', S.mark.out != null ? `out ${S.mark.out}` : 'out —'),
    btn('◁ מקטע', () => jumpSeg(-1), 'מקטע קודם ([)'), btn('מקטע ▷', () => jumpSeg(1), 'מקטע הבא (])'),
    h('span', { class: 'sep' }),
    btn('－', () => zoom(0.7), 'הקטן ציר זמן'), btn('＋', () => zoom(1.4), 'הגדל ציר זמן'), btn('התאם', () => { fit(); refresh(); }, 'התאם ציר זמן'),
    h('span', { class: 'spacer' }),
    btn('⌨', helpDialog, 'קיצורי מקלדת (?)'),
    h('button', { class: 'btn sm', 'aria-pressed': String(S.overlay), onclick: () => { S.overlay = !S.overlay; refresh(); }, title: 'הצג / הסתר תיבות (לא משנה תוויות שמורות)' }, 'תיבות'),
    h('button', { class: 'btn sm', 'aria-pressed': String(S.insp), onclick: () => { S.insp = !S.insp; $('#wb').classList.toggle('insp-off', !S.insp); setTimeout(() => { placeOverlay(); fit(false); refresh(); }, 30); }, title: 'פתח / סגור מפקח' }, 'מפקח'));
}
function togglePlay() { const v = $('#vid'); if (v.paused) { v.playbackRate = S.speed; v.play(); } else v.pause(); }
function step(n) { seekFrame(S.frame + n); }
function setSpeed(s) { S.speed = s; $('#vid').playbackRate = s; paintControls(); }
function markIn() { S.mark.in = S.frame; if (S.mark.out != null && S.mark.out <= S.mark.in) S.mark.out = null; paintMarks(); paintControls(); }
function markOut() {
  const end = S.frame + 1; // half-open: the marked frame is included
  if (S.mark.in == null) return toast('סמן תחילה (I) לפני סוף (O)', true);
  if (end <= S.mark.in) return toast('הסוף חייב להיות אחרי ההתחלה', true);
  S.mark.out = end;
  createSegment(S.mark.in, S.mark.out); S.mark = { in: null, out: null };
}
function createSegment(s, e, athlete = null) {
  const id = uid();
  const a = athlete ?? (selSeg()?.athlete_id ?? null);
  edit(c => c.segments.push({ id, start_frame: s, end_frame: e, athlete_id: a, event_type: eventOptions(S.src.primary_sport_id ?? null, null)[0]?.key ?? 'other', decision: 'include', reason_code: null, notes: '', framing_mode: null, target: null }));
  S.sel = id; refresh(); setTimeout(() => $('#f-athlete')?.focus(), 0);
}
function jumpSeg(dir) {
  const starts = C().segments.map(s => s.start_frame).sort((a, b) => a - b);
  const t = dir > 0 ? starts.find(x => x > S.frame) : [...starts].reverse().find(x => x < S.frame);
  if (t != null) { seekFrame(t); const s = C().segments.find(x => x.start_frame === t); S.sel = s.id; refresh(); }
}
function nextUnresolved() {
  const list = C().segments.filter(s => s.decision === 'uncertain' || (s.decision === 'include' && !s.athlete_id)).sort((a, b) => a.start_frame - b.start_frame);
  const t = list.find(s => s.start_frame > S.frame) ?? list[0];
  if (!t) return toast('אין פריטים לא פתורים');
  S.sel = t.id; seekFrame(t.start_frame); refresh();
}

// ---------------- timeline ----------------
function fit(doRefresh = true) {
  const sc = $('#tlscroll'); if (!sc || !S) return;
  S.ppf = Math.max(0.5, (sc.clientWidth - 24) / S.total);
  if (doRefresh) sc.scrollLeft = 0;
}
function zoom(k) {
  const sc = $('#tlscroll'); const centre = (sc.scrollLeft + sc.clientWidth / 2) / S.ppf;
  S.ppf = clamp(S.ppf * k, 0.5, 40); refresh(); sc.scrollLeft = centre * S.ppf - sc.clientWidth / 2;
}
const xOf = f => f * S.ppf;
function tracks() {
  const ids = [...new Set(C().segments.map(s => s.athlete_id))];
  if (S.sel && selSeg() && !ids.includes(selSeg().athlete_id)) ids.push(selSeg().athlete_id);
  const order = S.athletes.map(a => a.id);
  ids.sort((a, b) => (a == null) - (b == null) || order.indexOf(a) - order.indexOf(b));
  if (!ids.length) ids.push(null);
  return ids.map(aid => {
    const segs = C().segments.filter(s => s.athlete_id === aid).sort((a, b) => a.start_frame - b.start_frame || a.end_frame - b.end_frame);
    const lanes = []; const laneOf = new Map();
    for (const s of segs) { let l = lanes.findIndex(e => e <= s.start_frame); if (l < 0) { l = lanes.length; lanes.push(0); } lanes[l] = s.end_frame; laneOf.set(s.id, l); }
    return { aid, segs, laneOf, lanes: Math.max(1, lanes.length) };
  });
}
function paintTimeline() {
  const inner = $('#tlinner'), labels = $('#tllabels'); if (!inner) return;
  const W = Math.ceil(xOf(S.total)) + 40;
  inner.style.width = `${W}px`;
  const ruler = h('div', { class: 'ruler', id: 'ruler', 'data-testid': 'ruler', role: 'slider', 'aria-label': 'מיקום בסרטון', 'aria-valuemin': 0, 'aria-valuemax': S.total - 1, 'aria-valuenow': S.frame });
  const steps = [1, 2, 5, 10, 15, 30, 60, 150, 300, 900, 1800, 3600]; const stp = steps.find(s => s * S.ppf >= 70) ?? 3600;
  for (let f = 0; f <= S.total; f += stp) ruler.append(h('div', { class: 'tick mono', style: { left: `${xOf(f)}px` } }, stp < S.fps ? `${f}` : timecode(f, S.fps)));
  bindScrub(ruler);
  inner.replaceChildren(ruler);
  labels.replaceChildren(h('div', { class: 'lab', style: { height: '26px', color: 'var(--muted)' } }, 'ציר זמן'));
  for (const t of tracks()) {
    const rowH = 8 + t.lanes * 28;
    const row = h('div', { class: 'trk', 'data-track': t.aid ?? 'unknown', style: { height: `${rowH}px` } });
    for (const s of t.segs) {
      const lane = t.laneOf.get(s.id);
      const cls = s.decision === 'include' ? 'inc' : s.decision === 'exclude' ? 'exc' : 'unc';
      const icon = s.decision === 'include' ? '✓' : s.decision === 'exclude' ? '✕' : '?';
      const el = h('div', { class: `sg ${cls}${S.sel === s.id ? ' sel' : ''}`, 'data-id': s.id, 'data-testid': 'segment', role: 'button', tabindex: 0, 'aria-label': `${DECISION_HE[s.decision]} ${eventHe(s.event_type, effSport(s))} פריימים ${s.start_frame} עד ${s.end_frame}`,
        style: { left: `${xOf(s.start_frame)}px`, width: `${Math.max(4, xOf(s.end_frame - s.start_frame))}px`, top: `${4 + lane * 28}px`, borderColor: s.athlete_id ? athColor(s.athlete_id) : undefined } },
        h('span', { class: 'h l' }), `${icon} ${eventHe(s.event_type, effSport(s))}`, h('span', { class: 'h r' }));
      for (const k of C().keyframes.filter(k => k.segment_id === s.id)) el.append(h('i', { class: `kfm${k.origin === 'manual' ? '' : ' i'}`, style: { left: `${xOf(k.frame - s.start_frame)}px` } }));
      bindSegment(el, s); row.append(el);
    }
    bindCreate(row, t.aid);
    inner.append(row);
    labels.append(h('div', { class: 'lab', style: { height: `${rowH}px` } }, h('span', { class: 'swatch', style: { background: t.aid ? athColor(t.aid) : 'var(--muted)' } }), t.aid ? athName(t.aid) : 'לא ידוע'));
  }
  const rv = h('div', { class: 'trk', style: { height: '30px' }, 'data-track': 'reviewed' });
  for (const r of C().reviewed_ranges) rv.append(h('div', { class: 'rv', title: `נבדק ${r.start_frame}–${r.end_frame}`, style: { left: `${xOf(r.start_frame)}px`, width: `${xOf(r.end_frame - r.start_frame)}px` } }));
  inner.append(rv); labels.append(h('div', { class: 'lab', style: { height: '30px', color: 'var(--accent)' } }, '▭ טווחים שנבדקו'));
  inner.append(h('div', { class: 'ph', id: 'ph' }), h('div', { class: 'mk', id: 'mkin' }), h('div', { class: 'mk', id: 'mkout' }));
  paintPlayhead(); paintMarks();
}
function paintPlayhead() {
  const ph = $('#ph'); if (ph) ph.style.left = `${xOf(S.frame + 0.5)}px`;
  const tc = $('[data-testid=timecode]'), fr = $('[data-testid=framenum]');
  if (tc) tc.textContent = timecode(S.frame, S.fps); if (fr) fr.textContent = `frame ${S.frame} / ${S.total}`;
  const sc = $('#tlscroll'), x = xOf(S.frame);
  if (S.playing && (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 30)) sc.scrollLeft = x - 40;
  $('#ruler')?.setAttribute('aria-valuenow', S.frame);
  if (S.playing) paintOverlay(); paintHud();
}
function paintMarks() {
  const a = $('#mkin'), b = $('#mkout'); if (!a) return;
  a.style.display = S.mark.in != null ? '' : 'none'; if (S.mark.in != null) a.style.left = `${xOf(S.mark.in)}px`;
  b.style.display = S.mark.out != null ? '' : 'none'; if (S.mark.out != null) b.style.left = `${xOf(S.mark.out)}px`;
}
const frameAt = (ev, el, round = false) => { const r = el.getBoundingClientRect(); const x = ev.clientX - r.left; return clamp(round ? Math.round(x / S.ppf) : Math.floor(x / S.ppf), 0, round ? S.total : S.total - 1); };
function bindScrub(ruler) {
  ruler.addEventListener('pointerdown', e => {
    ruler.setPointerCapture(e.pointerId); seekFrame(frameAt(e, ruler));
    const mv = ev => seekFrame(frameAt(ev, ruler)), up = () => { ruler.removeEventListener('pointermove', mv); ruler.removeEventListener('pointerup', up); syncAfterScrub(); };
    ruler.addEventListener('pointermove', mv); ruler.addEventListener('pointerup', up);
  });
}
function syncAfterScrub() { refresh(); }
function bindSegment(el, s) {
  el.addEventListener('click', e => { e.stopPropagation(); });
  el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); S.sel = s.id; seekFrame(s.start_frame); refresh(); } });
  el.addEventListener('pointerdown', e => {
    e.stopPropagation();
    const mode = e.target.classList.contains('l') ? 'l' : e.target.classList.contains('r') ? 'r' : 'm';
    const row = el.parentElement, startF = frameAt(e, row, true), orig = { ...s }; let moved = false;
    S.sel = s.id; el.setPointerCapture(e.pointerId);
    const mv = ev => {
      const d = frameAt(ev, row, true) - startF; if (!d && !moved) return;
      if (!moved) { snapshot(); moved = true; }
      const len = orig.end_frame - orig.start_frame;
      if (mode === 'm') { const ns = clamp(orig.start_frame + d, 0, S.total - len); s.start_frame = ns; s.end_frame = ns + len; }
      else if (mode === 'l') s.start_frame = clamp(orig.start_frame + d, 0, orig.end_frame - 1);
      else s.end_frame = clamp(orig.end_frame + d, orig.start_frame + 1, S.total);
      el.style.left = `${xOf(s.start_frame)}px`; el.style.width = `${xOf(s.end_frame - s.start_frame)}px`;
    };
    const up = () => {
      el.removeEventListener('pointermove', mv); el.removeEventListener('pointerup', up);
      if (moved) { // keep keyframes inside the segment
        C().keyframes = C().keyframes.filter(k => k.segment_id !== s.id || (k.frame >= s.start_frame && k.frame < s.end_frame));
        changed();
      } else seekFrame(S.frame);
      refresh();
    };
    el.addEventListener('pointermove', mv); el.addEventListener('pointerup', up);
    refresh(); // selection highlight
  });
}
function bindCreate(row, aid) {
  row.addEventListener('pointerdown', e => {
    if (e.target !== row) return;
    const a = frameAt(e, row, true); let b = a; row.setPointerCapture(e.pointerId);
    const ghost = h('div', { class: 'sg inc', style: { left: `${xOf(a)}px`, width: '2px', top: '4px', opacity: '.6' } }); row.append(ghost);
    const mv = ev => { b = frameAt(ev, row, true); ghost.style.left = `${xOf(Math.min(a, b))}px`; ghost.style.width = `${xOf(Math.abs(b - a))}px`; };
    const up = () => { row.removeEventListener('pointermove', mv); row.removeEventListener('pointerup', up); ghost.remove(); if (Math.abs(b - a) >= 1) createSegment(Math.min(a, b), Math.max(a, b), aid); else { S.sel = null; seekFrame(clamp(a, 0, S.total - 1)); refresh(); } };
    row.addEventListener('pointermove', mv); row.addEventListener('pointerup', up);
  });
}

// ---------------- bounding boxes ----------------
function boxAt(segId, f) {
  const ks = C().keyframes.filter(k => k.segment_id === segId).sort((a, b) => a.frame - b.frame);
  const exact = ks.find(k => k.frame === f); if (exact) return { bbox: exact.bbox, kf: exact, interp: exact.origin !== 'manual' };
  const a = [...ks].reverse().find(k => k.frame < f), b = ks.find(k => k.frame > f);
  if (!a || !b) return null;
  const t = (f - a.frame) / (b.frame - a.frame), L = (p, q) => p + (q - p) * t;
  return { bbox: { x: L(a.bbox.x, b.bbox.x), y: L(a.bbox.y, b.bbox.y), w: L(a.bbox.w, b.bbox.w), h: L(a.bbox.h, b.bbox.h) }, kf: null, interp: true };
}
function paintOverlay() {
  const svg = $('#ovsvg'), ov = $('#ov'); if (!svg) return;
  placeOverlay();
  const W = ov.clientWidth || 1, H = ov.clientHeight || 1;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  ov.classList.toggle('draw', S.tool === 'box');
  svg.replaceChildren();
  if (!S.overlay) return;
  for (const s of C().segments) {
    if (S.frame < s.start_frame || S.frame >= s.end_frame) continue;
    const b = boxAt(s.id, S.frame); if (!b) continue;
    const isSel = s.id === S.sel, col = s.athlete_id ? athColor(s.athlete_id) : '#aab';
    const r = svgEl('rect', { class: `bx${b.interp ? ' interp' : ''}${isSel ? ' sel' : ''}`, x: b.bbox.x * W, y: b.bbox.y * H, width: b.bbox.w * W, height: b.bbox.h * H, stroke: col, 'data-testid': 'bbox', 'data-seg': s.id, 'data-interp': b.interp, opacity: isSel ? 1 : 0.55 });
    r.addEventListener('pointerdown', e => { e.stopPropagation(); S.sel = s.id; if (isSel) dragBox(e, s, b, 'move'); else refresh(); });
    svg.append(r);
    if (isSel) {
      const hd = svgEl('rect', { x: (b.bbox.x + b.bbox.w) * W - 5, y: (b.bbox.y + b.bbox.h) * H - 5, width: 10, height: 10, fill: col, style: 'cursor:nwse-resize;pointer-events:all' });
      hd.addEventListener('pointerdown', e => { e.stopPropagation(); dragBox(e, s, b, 'size'); }); svg.append(hd);
      const lbl = svgEl('text', { x: b.bbox.x * W, y: Math.max(14, b.bbox.y * H - 6), fill: col, 'font-size': 13, direction: 'rtl', style: 'paint-order:stroke;stroke:#000;stroke-width:3px' }); lbl.textContent = `${s.athlete_id ? athName(s.athlete_id) : 'לא ידוע'}${b.interp ? ' · משוער' : ''}`; svg.append(lbl);
    }
  }
  if (S.tool === 'box') ov.onpointerdown = drawBox; else ov.onpointerdown = null;
}
const svgEl = (t, a) => { const e = document.createElementNS('http://www.w3.org/2000/svg', t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
const norm = (e, ov) => { const r = ov.getBoundingClientRect(); return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) }; };
function putKeyframe(s, bbox) {
  const bb = { x: +bbox.x.toFixed(5), y: +bbox.y.toFixed(5), w: +bbox.w.toFixed(5), h: +bbox.h.toFixed(5) };
  if (bb.w < 0.003 || bb.h < 0.003) return;
  edit(c => { const ex = c.keyframes.find(k => k.segment_id === s.id && k.frame === S.frame); if (ex) { ex.bbox = bb; ex.origin = 'manual'; } else c.keyframes.push({ id: uid(), segment_id: s.id, frame: S.frame, bbox: bb, visibility: 'visible', origin: 'manual' }); });
}
function drawBox(e) {
  const s = selSeg(); if (!s) return toast('בחר מקטע לפני ציור תיבה', true);
  if (S.frame < s.start_frame || S.frame >= s.end_frame) return toast('הפריים הנוכחי מחוץ למקטע שנבחר', true);
  const ov = $('#ov'), a = norm(e, ov); const svg = $('#ovsvg'); const W = ov.clientWidth, H = ov.clientHeight, g = svgEl('rect', { class: 'bx', x: a.x * W, y: a.y * H, width: 0, height: 0, stroke: '#fff' }); svg.append(g); ov.setPointerCapture(e.pointerId);
  let box = null;
  const mv = ev => { const b = norm(ev, ov); box = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) }; for (const [k, v] of [['x', box.x * W], ['y', box.y * H], ['width', box.w * W], ['height', box.h * H]]) g.setAttribute(k, v); };
  const up = () => { ov.removeEventListener('pointermove', mv); ov.removeEventListener('pointerup', up); if (box) putKeyframe(s, box); else paintOverlay(); };
  ov.addEventListener('pointermove', mv); ov.addEventListener('pointerup', up);
}
function dragBox(e, s, b, mode) {
  const ov = $('#ov'), a = norm(e, ov), o = { ...b.bbox }; let nb = o; ov.style.pointerEvents = 'auto'; ov.setPointerCapture(e.pointerId);
  const rect = $(`[data-seg="${s.id}"]`);
  const mv = ev => { const p = norm(ev, ov), dx = p.x - a.x, dy = p.y - a.y;
    nb = mode === 'move' ? { ...o, x: clamp(o.x + dx, 0, 1 - o.w), y: clamp(o.y + dy, 0, 1 - o.h) } : { ...o, w: clamp(o.w + dx, 0.004, 1 - o.x), h: clamp(o.h + dy, 0.004, 1 - o.y) };
    const W = ov.clientWidth, H = ov.clientHeight; rect?.setAttribute('x', nb.x * W); rect?.setAttribute('y', nb.y * H); rect?.setAttribute('width', nb.w * W); rect?.setAttribute('height', nb.h * H); };
  const up = () => { ov.removeEventListener('pointermove', mv); ov.removeEventListener('pointerup', up); ov.style.pointerEvents = ''; if (nb !== o) putKeyframe(s, nb); else refresh(); };
  ov.addEventListener('pointermove', mv); ov.addEventListener('pointerup', up);
}
function fillInterpolated(s) {
  const man = C().keyframes.filter(k => k.segment_id === s.id && k.origin === 'manual').sort((a, b) => a.frame - b.frame);
  if (man.length < 2) return toast('נדרשים לפחות שני קיפריימים ידניים', true);
  edit(c => {
    c.keyframes = c.keyframes.filter(k => !(k.segment_id === s.id && k.origin === 'interpolated'));
    for (let i = 0; i < man.length - 1; i++) for (let f = man[i].frame + 10; f < man[i + 1].frame; f += 10) {
      const t = (f - man[i].frame) / (man[i + 1].frame - man[i].frame), L = (p, q) => +(p + (q - p) * t).toFixed(5);
      c.keyframes.push({ id: uid(), segment_id: s.id, frame: f, bbox: { x: L(man[i].bbox.x, man[i + 1].bbox.x), y: L(man[i].bbox.y, man[i + 1].bbox.y), w: L(man[i].bbox.w, man[i + 1].bbox.w), h: L(man[i].bbox.h, man[i + 1].bbox.h) }, visibility: 'visible', origin: 'interpolated' });
    }
  });
  toast('נוצרו קיפריימים משוערים (אינטרפולציה לינארית) — יש לאשר או לתקן');
}

// ---------------- inspector ----------------
function paintInspector() {
  const el = $('#insp'); if (!el) return;
  const s = selSeg();
  const unresolved = { unc: C().segments.filter(x => x.decision === 'uncertain').length, unk: C().segments.filter(x => x.decision === 'include' && !x.athlete_id).length };
  const cov = (() => { const m = new Uint8Array(S.total); for (const r of C().reviewed_ranges) m.fill(1, r.start_frame, r.end_frame); return m.reduce((a, b) => a + b, 0) / S.total; })();
  const rev = S.revs[0];
  el.replaceChildren(...[
    S.banner ? h('div', { class: `banner ${S.banner.kind}`, role: 'alert' }, S.banner.text, h('div', { style: { display: 'flex', gap: '6px', marginTop: '6px' } }, S.banner.action ? h('button', { class: 'btn sm', onclick: S.banner.action[1] }, S.banner.action[0]) : null, S.banner.action2 ? h('button', { class: 'btn sm', onclick: S.banner.action2[1] }, S.banner.action2[0]) : null)) : null,
    h('h3', {}, 'מקטע נבחר'),
    !s ? h('div', { class: 'empty', style: { padding: '16px' } }, 'בחר מקטע בציר הזמן, או סמן I / O ליצירת מקטע חדש.') : segForm(s),
    h('h3', {}, 'מקטעים', h('span', { class: 'pill' }, C().segments.length)),
    h('ul', { class: 'list', 'data-testid': 'seglist' }, C().segments.slice().sort((a, b) => a.start_frame - b.start_frame).map(x => h('li', { 'aria-selected': String(x.id === S.sel), style: { cursor: 'pointer' }, onclick: () => { S.sel = x.id; seekFrame(x.start_frame); refresh(); } }, h('span', { class: 'swatch', style: { background: athColor(x.athlete_id) } }), h('span', { class: 'mono ltr' }, `${x.start_frame}–${x.end_frame}`), h('span', { style: { flex: 1 } }, `${DECISION_HE[x.decision]} · ${eventHe(x.event_type, effSport(x))}`)))),
    h('h3', {}, 'כיסוי בדיקה'),
    h('div', { class: 'meta' }, `נבדק ${Math.round(cov * 100)}% מהסרטון — אזור שלא נבדק איננו סימון שלילי.`),
    h('div', { style: { display: 'flex', gap: '6px', marginTop: '6px' } },
      h('button', { class: 'btn sm', 'data-testid': 'mark-reviewed', onclick: () => { const a = S.mark.in ?? 0, b = S.mark.out ?? S.frame + 1; if (b <= a) return toast('סמן טווח (I ואז O או נגן עד סוף הטווח)', true); edit(c => c.reviewed_ranges.push({ start_frame: a, end_frame: b })); } }, 'סמן כנבדק (I→נוכחי)'),
      h('button', { class: 'btn sm', onclick: () => edit(c => c.reviewed_ranges.push({ start_frame: 0, end_frame: S.total })) }, 'כל הסרטון נבדק'),
      h('button', { class: 'btn sm', onclick: () => edit(c => { c.reviewed_ranges = []; }) }, 'נקה')),
    h('h3', {}, 'אישור'),
    h('div', { class: 'meta', 'data-testid': 'unresolved' }, `לא בטוח: ${unresolved.unc} · כלול ללא גולש: ${unresolved.unk}`),
    approvalForm(unresolved),
    h('h3', {}, 'היסטוריית גרסאות', h('span', { class: 'pill' }, S.revs.length)),
    h('ul', { class: 'list', 'data-testid': 'revlist' }, S.revs.length ? S.revs.map(r => h('li', {}, h('b', {}, `v${r.seq}`), h('span', { style: { flex: 1 }, class: 'meta' }, fmtDate(r.approved_at), r.reason ? ` · ${r.reason}` : ''), h('span', { class: 'mono ltr meta' }, r.digest.slice(0, 8)), h('button', { class: 'btn sm', title: 'טען כטיוטה', onclick: () => restoreRevision(r) }, 'שחזר'))) : [h('li', {}, 'אין גרסאות מאושרות')])
  ].filter(Boolean));
}
async function restoreRevision(r) {
  const full = await api(`/api/revisions/${r.id}`); snapshot(); S.draft.content = full.content; S.sel = null; changed(); refresh(); toast(`נטענה גרסה v${r.seq} כטיוטה (הגרסה המאושרת לא שונתה)`);
}
function field(label, ctl, id) { return h('div', {}, h('label', { class: 'f', for: id }, label), ctl); }
function segForm(s) {
  const upd = (k, v) => edit(c => { const x = c.segments.find(y => y.id === s.id); x[k] = v; });
  const kfs = C().keyframes.filter(k => k.segment_id === s.id).sort((a, b) => a.frame - b.frame);
  return h('div', { 'data-testid': 'segform' },
    h('div', { class: 'meta' }, h('span', { class: 'mono ltr' }, `[${s.start_frame}, ${s.end_frame})`), ` · ${s.end_frame - s.start_frame} פריימים · `, ltr(`${timecode(s.start_frame, S.fps)} → ${timecode(s.end_frame, S.fps)}`)),
    field('גולש', h('div', { style: { display: 'flex', gap: '6px' } },
      h('select', { id: 'f-athlete', 'data-testid': 'athlete-select', onchange: e => upd('athlete_id', e.target.value || null) }, h('option', { value: '' }, 'לא ידוע'), S.athletes.map((a, i) => h('option', { value: a.id, selected: a.id === s.athlete_id }, `${i + 1}. ${a.label}`))),
      h('button', { class: 'btn sm', 'data-testid': 'new-athlete', onclick: newAthlete }, '＋ חדש')), 'f-athlete'),
    field('ענף למקטע', h('select', { id: 'f-sport', 'data-testid': 'seg-sport', onchange: e => upd('sport_id', e.target.value || null) },
      h('option', { value: '' }, `כמו המקור (${sportName(S.src.primary_sport_id ?? null)})`), sportsList().filter(x => x.enabled || x.id === s.sport_id).map(x => h('option', { value: x.id, selected: x.id === s.sport_id }, x.name_he))), 'f-sport'),
    field('סוג אירוע', h('select', { id: 'f-type', 'data-testid': 'event-type', onchange: e => upd('event_type', e.target.value) }, eventOptions(effSport(s), s.event_type).map(t => h('option', { value: t.key, selected: t.key === s.event_type }, t.label_he))), 'f-type'),
    (effSport(s) != null || LEGACY.includes(s.event_type)) && !eventOptions(effSport(s), null).some(t => t.key === s.event_type)
      ? h('div', { class: 'banner bad', role: 'alert', 'data-testid': 'event-mismatch' }, `סוג האירוע "${s.event_type}" אינו שייך לענף "${sportName(effSport(s))}" — בחר סוג תקין לפני השמירה.`) : null,
    ...(eventInfo(effSport(s), s.event_type)?.required_attrs ?? []).map(a => field(`שדה חובה: ${a}`, h('input', { type: 'text', id: `f-attr-${a}`, 'data-testid': `attr-${a}`, value: s.attrs?.[a] ?? '', onchange: e => edit(c => { const x = c.segments.find(y => y.id === s.id); x.attrs = { ...(x.attrs ?? {}), [a]: e.target.value }; }) }), `f-attr-${a}`)),
    h('label', { class: 'f' }, 'החלטה'),
    h('div', { class: 'rad', role: 'group', 'aria-label': 'החלטה' }, [['include', 'inc', 'כלול', 'E'], ['exclude', 'exc', 'החרג', 'X'], ['uncertain', 'unc', 'לא בטוח', 'U']].map(([k, c, l, key]) => h('button', { class: c, 'aria-pressed': String(s.decision === k), 'data-testid': `dec-${k}`, onclick: () => upd('decision', k) }, `${l} `, h('kbd', {}, key)))),
    s.decision === 'exclude' ? field('סיבת החרגה', h('select', { id: 'f-reason', onchange: e => upd('reason_code', e.target.value || null) }, [['', '—'], ['failed_takeoff', 'עמידה כושלת'], ['no_readable_ride', 'אין רכיבה קריאה'], ['duplicate', 'כפילות'], ['wrong_athlete', 'גולש שגוי'], ['target_lost', 'אובדן המטרה']].map(([k, l]) => h('option', { value: k, selected: k === (s.reason_code ?? '') }, l))), 'f-reason') : null,
    field('הערות', h('textarea', { id: 'f-notes', onchange: e => upd('notes', e.target.value) }, s.notes ?? ''), 'f-notes'),
    field('יעד קומפוזיציה (לעריכה)', h('select', { id: 'f-frame', onchange: e => { upd('framing_mode', e.target.value || null); if (e.target.value !== 'directional_lead_room') upd('target', null); else if (!s.target) upd('target', { x: 0.4, y: 0.5 }); } }, [['', 'לא נקבע'], ['contain', 'Contain (מסגרת מלאה)'], ['geometric_center', 'מרכז גיאומטרי'], ['directional_lead_room', 'כיווני (מרווח קדמי)']].map(([k, l]) => h('option', { value: k, selected: k === (s.framing_mode ?? '') }, l))), 'f-frame'),
    s.framing_mode === 'directional_lead_room' ? h('div', { class: 'cols2' }, field('יעד X', h('input', { type: 'number', id: 'f-tx', min: 0, max: 1, step: 0.05, value: s.target?.x ?? 0.4, onchange: e => upd('target', { x: clamp(+e.target.value, 0, 1), y: s.target?.y ?? 0.5 }) }), 'f-tx'), field('יעד Y', h('input', { type: 'number', id: 'f-ty', min: 0, max: 1, step: 0.05, value: s.target?.y ?? 0.5, onchange: e => upd('target', { x: s.target?.x ?? 0.4, y: clamp(+e.target.value, 0, 1) }) }), 'f-ty')) : null,
    h('h3', {}, 'תיבות תיחום (קיפריימים)', h('span', { class: 'pill' }, kfs.length)),
    h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
      h('button', { class: 'btn sm', 'aria-pressed': String(S.tool === 'box'), 'data-testid': 'tool-box', onclick: () => { S.tool = S.tool === 'box' ? 'select' : 'box'; refresh(); } }, 'ציור תיבה ', h('kbd', {}, 'B')),
      h('button', { class: 'btn sm', onclick: () => fillInterpolated(s) }, 'מלא ביניים (משוער)')),
    h('ul', { class: 'list', 'data-testid': 'kflist', style: { marginTop: '6px', maxHeight: '140px', overflow: 'auto' } }, kfs.map(k => h('li', {}, h('span', { class: 'mono ltr' }, `f${k.frame}`), h('span', { class: 'meta', style: { flex: 1 } }, k.origin === 'manual' ? 'ידני' : k.origin === 'interpolated' ? 'משוער' : 'הצעה'),
      k.origin !== 'manual' ? h('button', { class: 'btn sm', title: 'אשר כידני', onclick: () => edit(c => { c.keyframes.find(x => x.id === k.id).origin = 'manual'; }) }, '✓') : null,
      h('button', { class: 'btn sm', onclick: () => seekFrame(k.frame) }, 'עבור'), h('button', { class: 'btn sm danger', 'aria-label': 'מחק קיפריים', onclick: () => edit(c => { c.keyframes = c.keyframes.filter(x => x.id !== k.id); }) }, '✕')))),
    h('div', { style: { marginTop: '10px' } }, h('button', { class: 'btn danger sm', 'data-testid': 'delete-seg', onclick: deleteSel }, 'מחק מקטע ', h('kbd', {}, 'Del'))));
}
function deleteSel() { const s = selSeg(); if (!s) return; edit(c => { c.segments = c.segments.filter(x => x.id !== s.id); c.keyframes = c.keyframes.filter(k => k.segment_id !== s.id); }); S.sel = null; refresh(); }
async function newAthlete() {
  const inp = h('input', { type: 'text', id: 'na-label', placeholder: 'שם / מזהה פסבדונימי' });
  const d = dialog('גולש חדש', h('div', {}, h('label', { class: 'f', for: 'na-label' }, 'תווית'), inp), [
    h('button', { class: 'btn primary', 'data-testid': 'na-ok', onclick: async () => { try { const a = await api('/api/athletes', { method: 'POST', body: { label: inp.value } }); S.athletes.push({ ...a, appearances: [] }); closeDialog(); const s = selSeg(); if (s) edit(c => { c.segments.find(x => x.id === s.id).athlete_id = a.id; }); refresh(); } catch (e) { toast(e.message, true); } } }, 'צור'),
    h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')]);
  inp.focus(); inp.addEventListener('keydown', e => { if (e.key === 'Enter') $('[data-testid=na-ok]').click(); });
}
function approvalForm(u) {
  let scope = 'source', reason = '', ack = false;
  const btn = h('button', { class: 'btn primary', 'data-testid': 'approve', onclick: async () => {
    btn.disabled = true;
    try {
      clearTimeout(S.saveTimer); while (S.inflight) await new Promise(r => setTimeout(r, 50));
      if (S.save !== 'saved') await save();
      if (S.save !== 'saved') throw new Error('יש לשמור את הטיוטה לפני אישור');
      const r = await api(`/api/sources/${S.src.id}/approve`, { method: 'POST', body: { expected_version: S.draft.version, scope, reason, acknowledge_unresolved: ack } });
      toast(r.unchanged ? 'אין שינוי מאז הגרסה המאושרת' : `גרסה ${r.revision.seq} אושרה ונשמרה כבלתי ניתנת לשינוי`);
      S.revs = (await api(`/api/sources/${S.src.id}/revisions`)).items; paintStatus(); refresh();
    } catch (e) { toast(e.message + (e.data?.unresolved ? ' — סמן אישור מפורש' : ''), true); btn.disabled = false; }
  } }, 'אשר גרסה');
  return h('div', {},
    h('div', { class: 'cols2' }, field('היקף אישור', h('select', { id: 'ap-scope', onchange: e => { scope = e.target.value; } }, [['source', 'כל הסרטון'], ['interval', 'טווח'], ['segment', 'מקטע']].map(([k, l]) => h('option', { value: k }, l))), 'ap-scope'), field('סיבה / הערה', h('input', { type: 'text', id: 'ap-reason', oninput: e => { reason = e.target.value; } }), 'ap-reason')),
    (u.unc || u.unk) ? h('label', { style: { display: 'flex', gap: '6px', margin: '8px 0', color: 'var(--unc)' } }, h('input', { type: 'checkbox', 'data-testid': 'ack', onchange: e => { ack = e.target.checked; } }), `אני מאשר במפורש ${u.unc + u.unk} פריטים לא פתורים`) : null, btn);
}

// ---------------- chrome / refresh ----------------
function paintHud() { const a = $('#hudfr'), b = $('#hudtool'); if (a) a.textContent = `f${S.frame}`; if (b) b.textContent = S.tool === 'box' ? 'כלי תיבה פעיל (B)' : ''; if (b) b.style.display = S.tool === 'box' ? '' : 'none'; }
function paintStatus() {
  const rev = S.revs[0];
  setTopbar(h('strong', {}, 'סימון'), h('span', { class: 'ltr mono', title: S.src.sha256, 'data-testid': 'srcname' }, S.src.display_name),
    S.src.ingest_state === 'ready' ? pill('ארכיון מאומת', 'ok') : pill('ארכיון לא מאומת', 'bad'),
    pill(rev ? `גרסה מאושרת v${rev.seq}` : 'אין גרסה מאושרת', rev ? 'ok' : ''),
    sportPicker(),
    h('span', { class: 'spacer' }), h('span', { id: 'savepill', 'data-testid': 'savepill', 'aria-live': 'polite' }));
  paintSave($('#savepill'));
}
function refresh() {
  if (!S) return;
  paintStatus(); paintControls(); paintTimeline(); paintOverlay(); paintInspector(); paintHud();
}

// ---------------- keyboard ----------------
function helpDialog() {
  const rows = [['Space', 'ניגון / השהיה'], ['← / →', 'פריים אחורה / קדימה'], ['Shift + ← / →', '10 פריימים'], ['I / O', 'תחילת / סוף מקטע (יוצר מקטע)'], ['[ / ]', 'מקטע קודם / הבא'], ['1–9', 'שיוך גולש למקטע'], ['E / X / U', 'כלול / החרג / לא בטוח'], ['B', 'כלי ציור תיבה'], ['N', 'הפריט הלא פתור הבא'], ['Q / W', 'האט / האץ'], ['+ / −', 'זום ציר זמן'], ['Del', 'מחק מקטע'], ['Ctrl + Z / Y', 'בטל / חזור'], ['Ctrl + S', 'שמירה מיידית'], ['?', 'עזרה']];
  dialog('קיצורי מקלדת', h('div', { class: 'keys' }, rows.flatMap(([k, d]) => [h('kbd', { dir: 'ltr' }, k), d])), [h('button', { class: 'btn', onclick: closeDialog }, 'סגור')]);
}
function bindKeys() {
  on(window, 'keydown', e => {
    if (!S || $('#dlg').open) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); clearTimeout(S.saveTimer); save(); return; }
    if (typing) return;
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(e.shiftKey); return; }
    if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); undo(true); return; }
    if (mod || e.altKey) return;
    const k = e.key, s = selSeg();
    const act = {
      ' ': () => togglePlay(), ArrowLeft: () => step(e.shiftKey ? -10 : -1), ArrowRight: () => step(e.shiftKey ? 10 : 1),
      i: markIn, I: markIn, o: markOut, O: markOut, '[': () => jumpSeg(-1), ']': () => jumpSeg(1),
      b: () => { S.tool = S.tool === 'box' ? 'select' : 'box'; refresh(); }, B: () => { S.tool = S.tool === 'box' ? 'select' : 'box'; refresh(); },
      n: nextUnresolved, N: nextUnresolved,
      e: () => s && edit(c => { c.segments.find(x => x.id === s.id).decision = 'include'; }), x: () => s && edit(c => { c.segments.find(x => x.id === s.id).decision = 'exclude'; }), u: () => s && edit(c => { c.segments.find(x => x.id === s.id).decision = 'uncertain'; }),
      q: () => setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(S.speed) - 1)]), w: () => setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(S.speed) + 1)]),
      '+': () => zoom(1.4), '=': () => zoom(1.4), '-': () => zoom(0.7), '?': helpDialog, Delete: deleteSel, Backspace: deleteSel,
      Escape: () => { S.tool = 'select'; S.sel = null; refresh(); },
    };
    if (/^[1-9]$/.test(k) && s) { const a = S.athletes[+k - 1]; if (a) { e.preventDefault(); edit(c => { c.segments.find(x => x.id === s.id).athlete_id = a.id; }); } return; }
    if (act[k]) { e.preventDefault(); act[k](); }
  });
  on(window, 'beforeunload', e => { if (S && (S.save === 'dirty' || S.save === 'offline' || S.save === 'saving')) { persistPending(); e.preventDefault(); e.returnValue = ''; } });
}

// ---------------- sport classification (spec §18) ----------------
function sportPicker() {
  const cur = S.src.primary_sport_id ?? '';
  return h('label', { class: 'pill', style: { gap: '6px' } }, 'ענף:',
    h('select', { id: 'src-sport', 'data-testid': 'source-sport', 'aria-label': 'ענף הספורט של הסרטון', onchange: e => changeSport(e.target.value || null, cur) },
      h('option', { value: '' }, 'לא מסווג'), sportsList().filter(x => x.enabled || x.id === cur).map(x => h('option', { value: x.id, selected: x.id === cur }, x.name_he))));
}
async function changeSport(next, prev, opts = {}) {
  if (S.dirty || S.inflight) { toast('יש שינויים שטרם נשמרו — המתן לשמירה לפני שינוי ענף', true); return refresh(); }
  if (!opts.confirmed && (S.revs.length || next == null)) {
    return dialog('שינוי ענף ספורט', h('div', {}, h('p', {}, S.revs.length ? 'לסרטון יש גרסאות מאושרות. הן והדאטהסטים הקפואים לא ישתנו; רק הטיוטה והסיווג הנוכחי.' : 'לשנות את הסיווג?'), h('p', { class: 'meta' }, `${sportName(prev ?? null)} ← ${sportName(next)}`)), [
      h('button', { class: 'btn primary', 'data-testid': 'confirm-sport', onclick: () => { closeDialog(); changeSport(next, prev, { confirmed: true }); } }, 'אשר שינוי'),
      h('button', { class: 'btn', onclick: () => { closeDialog(); refresh(); } }, 'ביטול')]);
  }
  try {
    await api(`/api/sources/${S.src.id}/sport`, { method: 'PATCH', body: { sport_id: next, reason: 'operator', ...opts.body } });
    toast(`הענף עודכן: ${sportName(next)}`);
    const root = S.root, id = S.src.id; teardownAnnotate(); await renderAnnotate(root, id);
  } catch (e) {
    if (e.code !== 'SPORT_INCOMPATIBLE') { toast(e.message, true); return refresh(); }
    const bad = e.data.incompatible, keys = [...new Set(bad.map(b => b.event_type))];
    const targets = (sportsList().find(x => x.id === next)?.event_types ?? []).filter(t => t.enabled);
    const picks = new Map(keys.map(k => [k, h('select', { 'aria-label': `מיפוי ${k}`, 'data-testid': `remap-${k}` }, h('option', { value: '' }, 'השאר (ידרוש תיקון ידני)'), targets.map(t => h('option', { value: t.key }, t.label_he)))]));
    dialog('סוגי אירוע לא תואמים לענף החדש', h('div', {}, h('p', {}, `${bad.length} מקטעים בטיוטה משתמשים בסוגי אירוע שאינם קיימים בענף "${sportName(next)}". שום מקטע לא יימחק.`),
      h('ul', { class: 'list' }, keys.map(k => h('li', {}, ltr(k), ' → ', picks.get(k))))), [
      h('button', { class: 'btn primary', 'data-testid': 'apply-remap', onclick: () => {
        const remap = Object.fromEntries([...picks].filter(([, el]) => el.value).map(([k, el]) => [k, el.value]));
        closeDialog(); changeSport(next, prev, { confirmed: true, body: { remap, acknowledge_incompatible: true } }); } }, 'החל מיפוי ושנה ענף'),
      h('button', { class: 'btn', onclick: () => { closeDialog(); refresh(); } }, 'ביטול')]);
  }
}
