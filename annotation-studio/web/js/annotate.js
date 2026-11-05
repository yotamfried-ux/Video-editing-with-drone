// Precision Annotation Workbench V2: Video + Bounding Box QA + Multitrack Timeline + Full Taxonomy Inspector.
import {
  h, $, api, ltr, pill, toast, dialog, closeDialog, timecode, fpsOf, uid, fmtDate,
  eventHe, eventOptions, eventInfo, sportName, sportsList, DECISION_HE, STATUS_HE, STATUS_CLASS, REASON_LIST, awaitJob
} from './ui.js';
import { setTopbar, rememberSource } from './main.js';
import { trackBox } from './tracker.js';

const SPEEDS = [0.25, 0.5, 1, 2];
const COLORS = ['#3ddc97', '#4cc9f0', '#ffa657', '#c792ea', '#ff777e'];
let S = null, cleanup = [];
const LEGACY = ['wave_ride', 'failed_takeoff', 'wipeout', 'paddle_out', 'other'];
const effSport = x => x.sport_id ?? S.src.primary_sport_id ?? null;

export function teardownAnnotate() { if (S) { S.trackQueue = []; S.tracking?.ctl.abort(); S.copyCtl?.abort(); if (S.copy?.url) URL.revokeObjectURL(S.copy.url); } cleanup.forEach(f => f()); cleanup = []; S = null; }
const on = (t, ev, fn, o) => { t.addEventListener(ev, fn, o); cleanup.push(() => t.removeEventListener(ev, fn, o)); };

export async function renderAnnotate(root, id) {
  if (!id) {
    const r = await api('/api/sources?limit=1&status=not_annotated');
    if (r.items[0]) { location.hash = `#/annotate/${r.items[0].id}`; return; }
    root.append(h('div', { class: 'page' }, h('div', { class: 'empty' }, 'בחר סרטון בקטלוג כדי להתחיל', h('p', {}, h('a', { class: 'btn primary', href: '#/catalog' }, 'לקטלוג'))))); return;
  }
  // Independent annotation stream (addendum §2): #/annotate/<source>?set=<setId> works on that set's own assignment.
  const [rawId, qs] = String(id).split('?');
  const setId = new URLSearchParams(qs ?? '').get('set') || 'primary';
  id = rawId;
  if (setId === 'primary') rememberSource(id);
  const draftUrl = setId === 'primary' ? `/api/sources/${id}/draft` : `/api/sets/${setId}/assignments/${id}`;
  const [src, draft, athletes, revs, ownerInfo, appearances] = await Promise.all([
    api(`/api/sources/${id}`),
    api(draftUrl),
    api('/api/athletes'),
    api(`/api/sources/${id}/revisions`),
    api(`/api/sources/${id}/catalog-owner`).catch(() => ({ owner_athlete_id: null, owner_status: 'unassigned' })),
    api(`/api/sources/${id}/appearances`).catch(() => ({ items: [] }))
  ]);

  if (!draft.content.box_verifications) draft.content.box_verifications = [];

  S = {
    setId, draftUrl, src, fps: fpsOf(src), total: src.frame_count, draft, athletes: athletes.items, revs: revs.items, ownerInfo, appearances: appearances.items,
    sel: null, frame: 0, ppf: 6, mark: { in: null, out: null }, tool: 'select', speed: 1, save: 'saved', dirty: 0, inflight: false,
    undo: [], redo: [], saveTimer: null, retryTimer: null, insp: true, overlay: true, banner: null, playing: false, root,
    inspTab: 'event', // 'event' | 'associate' | 'box'
    quality: 'proxy', // 'proxy' | 'original'
    boxTargetAthlete: null,
  };

  // Spec §21.4: a video with events opens with a clearly selected event, not a blank inspector.
  const firstSeg = [...draft.content.segments].sort((a, b) => a.start_frame - b.start_frame)[0];
  if (firstSeg) S.sel = firstSeg.id;
  // Opened from the quick catalog at a specific event/tab ("what is missing" chip).
  let focus = null;
  try { focus = JSON.parse(sessionStorage.getItem('studio.focus') ?? 'null'); sessionStorage.removeItem('studio.focus'); } catch {}
  if (focus?.source === id) { if (focus.seg && seg(focus.seg)) S.sel = focus.seg; if (focus.tab) S.inspTab = focus.tab; }
  try { S.fromCatalog = sessionStorage.getItem('studio.fromCatalog') === id; } catch {}
  restorePending();
  watchCloudProxy();
  root.replaceChildren(layout());
  mountVideo();
  bindKeys();
  fit();
  if (draft.legacy_box_qa_upgraded) {
    S.banner = { kind: 'warn', text: 'אימותי BOX ישנים שלא היו קשורים ל-BOX בפריים המדויק סומנו "נדרשת בדיקה מחדש". ההיסטוריה נשמרה; גרסאות מאושרות לא שונו.' };
    changed();
  }
  refresh();
  refreshStates();
  if (focus?.source === id && selSeg()) setTimeout(() => S && seekFrame(selSeg().start_frame), 0);
  if (S.setId === 'primary') Promise.all([api(`/api/physical-actions?source=${id}`), api('/api/physical-actions')]).then(([m, all]) => { if (!S) return; S.actions = m.items; S.allActions = all.items; refresh(); }).catch(() => {});
  cleanup.push(() => { clearTimeout(S?.saveTimer); clearTimeout(S?.retryTimer); });
}

// ---------------- state helpers ----------------
const C = () => S.draft.content;
const seg = id => C().segments.find(s => s.id === id);
const selSeg = () => S.sel && seg(S.sel);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const athName = id => S.athletes.find(a => a.id === id)?.label ?? 'לא ידוע';
const athColor = id => {
  const i = S.athletes.findIndex(a => a.id === id);
  return i < 0 ? '#9eb0ca' : COLORS[i % COLORS.length];
};

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
const pendKey = () => `studio.pending.${S.src.id}${S.setId && S.setId !== 'primary' ? `.${S.setId}` : ''}`;
function persistPending() { try { localStorage.setItem(pendKey(), JSON.stringify({ base: S.draft.version, content: C(), at: Date.now() })); } catch {} }
function clearPending() { try { localStorage.removeItem(pendKey()); } catch {} }
function restorePending() {
  try {
    const p = JSON.parse(localStorage.getItem(pendKey()) ?? 'null');
    if (!p) return;
    if (JSON.stringify(p.content) === JSON.stringify(C())) return clearPending();
    if (p.base === S.draft.version) { S.draft.content = p.content; S.dirty++; S.banner = { kind: 'warn', restored: true, text: 'שוחזרה טיוטה מקומית שלא נשמרה בשרת — נשמרת כעת.' }; setTimeout(save, 300); }
    else S.banner = { kind: 'bad', text: 'קיימת טיוטה מקומית ישנה שמתנגשת עם גרסת השרת.', action: ['השתמש בטיוטה המקומית', () => { S.draft.content = p.content; S.banner = null; changed(); refresh(); }], action2: ['השלך', () => { clearPending(); S.banner = null; refresh(); }] };
  } catch {}
}
function setSave(state) { S.save = state; const el = $('#savepill'); if (el) paintSave(el); }
const SAVE_UI = { saved: ['נשמר', 'ok'], dirty: ['שינויים לא שמורים', 'warn'], saving: ['שומר…', 'busy'], offline: ['לא מקוון — ממתין לשליחה', 'warn'], conflict: ['התנגשות גרסאות', 'bad'], failed: ['שמירה נכשלה', 'bad'] };
function paintSave(el) {
  const [t, c] = SAVE_UI[S.save]; el.className = `pill ${c}`;
  if (S.save === 'saved' && !S.savedAt && S.draft?.updated_at) S.savedAt = new Date(S.draft.updated_at);   // the real time of the last save on the server
  el.replaceChildren(h('span', { class: 'dot' }), S.save === 'saved' && S.savedAt ? `${t} · ${S.savedAt.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : t);
  el.dataset.state = S.save;
  const b = $('#savebtn'); if (!b) return;
  // One obvious save button. Autosave keeps running; the button saves NOW and says clearly what happened.
  const label = { saved: '✓ הכל נשמר', dirty: '💾 שמור עכשיו', saving: 'שומר…', offline: '💾 נסה לשמור שוב', failed: '💾 נסה לשמור שוב', conflict: 'התנגשות: ראה הודעה' }[S.save];
  b.textContent = label; b.className = `btn ${S.save === 'saved' || S.save === 'saving' ? '' : 'primary'} save-btn`;
  b.disabled = S.save === 'saved' || S.save === 'saving' || S.save === 'conflict';
}
async function saveNow() {
  clearTimeout(S.saveTimer); clearTimeout(S.retryTimer);
  commitWatched();
  while (S.inflight) await new Promise(r => setTimeout(r, 50));
  if (S.save !== 'saved') await save();
  if (S.save === 'saved') toast('נשמר ✓'); else if (S.save !== 'conflict') toast('השמירה לא הצליחה. השינויים שמורים בדפדפן ויישלחו שוב.', true);
}

async function save() {
  if (!S || S.inflight || S.save === 'conflict') return;
  const mySeq = S.dirty; S.inflight = true; setSave('saving');
  try {
    for (const t of C().tracks ?? []) syncSegmentsFromTrack(C(), t);   // events made/changed after tracking get their boxes
    const fixed = repairOutOfRange(C());
    const fixBanner = fixed.length ? { kind: 'warn', text: `תוקן אוטומטית לפני שמירה (ערכים מחוץ לטווח האירוע): ${fixed.join(' · ')}` } : null;
    reconcileVerifications(C());
    const r = await api(S.draftUrl, { method: 'PUT', body: { expected_version: S.draft.version, content: C() } });
    S.draft.version = r.version; S.inflight = false; S.savedAt = new Date();
    if (fixBanner || S.banner?.restored || S.banner?.testid === 'save-failed') { S.banner = fixBanner; paintInspector(); }
    refreshStates();
    if (S.dirty !== mySeq) { setSave('dirty'); S.saveTimer = setTimeout(save, 200); } else { setSave('saved'); clearPending(); }
    paintStatus();
  } catch (e) {
    S.inflight = false;
    if (e.code === 'VERSION_CONFLICT') { setSave('conflict'); S.banner = { kind: 'bad', text: e.message, action: ['טען גרסת שרת', reloadServer], action2: ['דרוס עם הגרסה שלי', async () => { const d = await api(S.draftUrl); S.draft.version = d.version; S.save = 'dirty'; S.banner = null; save(); refresh(); }] }; refresh(); }
    else if (e.status && e.status < 500 && e.status !== 0) {
      setSave('failed');
      // Persistent, explained and recoverable: the draft stays saved locally until the operator chooses.
      S.banner = { kind: 'bad', testid: 'save-failed', text: `השמירה נדחתה על ידי השרת: ${e.message}. השינויים שמורים מקומית בדפדפן. תקן את הנקודה ונסה שוב, או טען את הגרסה השמורה בשרת (השינויים המקומיים יימחקו).`,
        action: ['נסה שוב', () => { S.banner = null; save(); refresh(); }], action2: ['טען גרסת שרת', reloadServer] };
      refresh();
    }
    else { setSave('offline'); clearTimeout(S.retryTimer); S.retryTimer = setTimeout(save, 3000); }
  }
}
function confirmReset() {
  const segs = C().segments.length, boxes = (C().tracks ?? []).reduce((n, t) => n + t.points.length, 0) + C().keyframes.length;
  dialog('לקטלג את הסרטון מחדש?', h('div', {},
    h('p', {}, `יימחקו מהטיוטה: ${segs} אירועים, ${boxes} תיבות/נקודות מעקב, וסימון "מה שצפית".`),
    h('p', { class: 'meta' }, 'עותק מלא נשמר ביומן, ואפשר לבטל את האיפוס בלחיצה אחת (כל עוד לא נשמר משהו חדש).')), [
    h('button', { class: 'btn danger', 'data-testid': 'reset-confirm', onclick: async () => { closeDialog(); await doReset(); } }, 'כן, קטלג מחדש'),
    h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')]);
}
async function doReset() {
  clearTimeout(S.saveTimer); while (S.inflight) await new Promise(r => setTimeout(r, 50));
  if (S.save !== 'saved') await save();
  if (S.save !== 'saved') return toast('יש שינויים שלא נשמרו - פתור את הודעת השמירה ואז נסה שוב', true);
  S.trackQueue = []; S.tracking?.ctl.abort(); S.tracking = null;
  try {
    const r = await api(`/api/sources/${S.src.id}/draft/reset`, { method: 'POST', body: { expected_version: S.draft.version } });
    S.draft = await api(S.draftUrl); clearPending(); S.sel = null; S.undo = []; S.redo = []; S.mark = { in: null, out: null };
    S.trackLost = {}; S.trackErr = {}; S.autoTried = new Set(['legacy']); S.banner = { kind: 'warn', testid: 'reset-done', text: 'הקטלוג של הסרטון אופס. אפשר להתחיל לסמן מחדש.', action: ['בטל איפוס', undoReset] };
    void r; setSave('saved'); refresh();
  } catch (e) { toast(e.message, true); }
}
async function undoReset() {
  try {
    await api(`/api/sources/${S.src.id}/draft/restore`, { method: 'POST', body: { expected_version: S.draft.version } });
    S.draft = await api(S.draftUrl); clearPending(); S.banner = null; S.sel = null; setSave('saved'); refresh(); toast('האיפוס בוטל - הסימונים חזרו');
  } catch (e) { toast(e.message, true); }
}
async function reloadServer() { const d = await api(S.draftUrl); S.draft = d; clearPending(); S.banner = null; S.save = 'saved'; S.sel = null; refresh(); }

// ---------------- layout ----------------
function layout() {
  return h('div', { class: 'wb', id: 'wb', 'data-testid': 'workbench' },
    h('div', { class: 'wb-main' },
      h('div', { class: 'stage-wrap' },
        h('div', { class: 'stage', id: 'stage' },
          h('video', { id: 'vid', muted: true, playsinline: true, preload: 'auto', 'aria-label': 'נגן וידאו' }),
          h('div', { class: 'ov', id: 'ov' }, h('svg', { id: 'ovsvg', viewBox: '0 0 100 100' })),
          h('div', { class: 'hud' },
            h('span', { class: 'pill mono', id: 'hudfr' }, ''),
            h('span', { class: 'pill', id: 'hudtool' }, ''),
            h('span', { class: 'pill mark-live', id: 'hudmark', 'data-testid': 'mark-live', style: { display: 'none' } }, ''),
            h('span', { class: 'pill stall-live', id: 'hudstall', 'data-testid': 'stall', style: { display: 'none' } }, ''),
            h('span', { class: 'pill stall-live', id: 'hudcopy', 'data-testid': 'local-copy', style: { display: 'none' } }, ''),
            h('span', { class: 'pill track-live', id: 'hudtrack', 'data-testid': 'track-progress', style: { display: 'none' } }, '')
          ),
          h('div', { class: 'boxhover', id: 'boxHover', style: { position: 'absolute', bottom: '12px', right: '12px', display: 'none' } }, '')
        )
      ),
      h('div', { class: 'controls', id: 'controls', role: 'toolbar', 'aria-label': 'בקרת נגן' }),
      h('div', { class: 'tl', id: 'tl' },
        h('div', { class: 'tl-labels', id: 'tllabels' }),
        h('div', { class: 'tl-scroll', id: 'tlscroll' }, h('div', { class: 'tl-inner', id: 'tlinner' }))
      )
    ),
    h('aside', { class: 'insp', id: 'insp', 'aria-label': 'מפקח תיוג' })
  );
}

/** The video the player, the tracker and the thumbnails read: the in-browser copy once it is there. */
function mediaUrl() { return S.quality === 'original' ? `/media/${S.src.id}/original` : (S.copy?.url ?? S.src.playback_url); }
const LOCAL_COPY_MAX = 1.5e9;
/**
 * The originals are 4K/60 at 100-170 Mb/s: streaming them stalls on most connections, and the player, the tracker and
 * the thumbnails each pulled their own stream. Download the video ONCE into the browser (with progress); everything
 * then plays and seeks from that copy without the network. Falls back to streaming if the download fails.
 */
function startLocalCopy() {
  const mine = S, url = S.src.playback_url, size = S.src.byte_size;
  if (!url || !(size > 0 && size <= LOCAL_COPY_MAX)) { S.copyReady = Promise.resolve(); return; }
  const ctl = new AbortController(); S.copyCtl = ctl; S.copy = { pct: 0 }; setTimeout(paintCopy, 0);
  S.copyReady = (async () => {
    try {
      const r = await fetch(url, { signal: ctl.signal, credentials: 'same-origin' });
      if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
      const total = Number(r.headers.get('content-length')) || size, reader = r.body.getReader(), parts = []; let got = 0, last = 0;
      for (;;) {
        const { done, value } = await reader.read(); if (done) break;
        parts.push(value); got += value.length;
        if (S !== mine) return ctl.abort();
        if (Date.now() - last > 250) { last = Date.now(); mine.copy = { pct: Math.min(1, got / total), got, total }; paintCopy(); }
      }
      if (S !== mine) return;
      const blobUrl = URL.createObjectURL(new Blob(parts, { type: 'video/mp4' }));
      mine.copy = { url: blobUrl };
      if (S.quality !== 'original') {
        const v = $('#vid'), t = v.currentTime, playing = !v.paused;
        v.preload = 'auto'; v.src = blobUrl;
        v.addEventListener('loadedmetadata', () => { v.currentTime = t; if (playing) v.play().catch(() => {}); }, { once: true });
      }
      paintStall(false); paintCopy();
    } catch (e) {
      if (S !== mine || ctl.signal.aborted) return;
      mine.copy = { failed: true }; paintCopy();     // keep streaming as before
    }
  })();
}
function paintCopy() {
  const el = $('#hudcopy'); if (!el) return;
  const c = S?.copy, on = !!c && c.url == null && !c.failed;
  el.style.display = on ? '' : 'none';
  if (on) el.textContent = `מוריד את הסרטון לדפדפן לניגון חלק… ${Math.round((c.pct ?? 0) * 100)}%${c.total ? ` (${Math.round(c.got / 1e6)}/${Math.round(c.total / 1e6)} MB)` : ''}`;
}
function mountVideo() {
  const v = $('#vid');
  startLocalCopy();
  if (S.copy && !S.copy.url) v.preload = 'metadata';       // don't compete with the download; the first frame still shows
  v.src = mediaUrl();
  v.addEventListener('loadedmetadata', () => { placeOverlay(); refresh(); });
  v.addEventListener('seeked', () => { syncFrameFromVideo(); });
  v.addEventListener('play', () => { if (!S) return; S.playing = true; S.watchFrom = S.frame; loop(); paintControls(); });
  v.addEventListener('pause', () => { if (!S) return; S.playing = false; syncFrameFromVideo(); commitWatched(); paintControls(); });
  // The originals are 4K/60 at ~100-170 Mb/s; most connections cannot stream that in real time. Say so instead of
  // leaving the operator with a frozen picture, and suggest what helps.
  v.addEventListener('waiting', () => { if (!S?.playing) return; S.stalls = (S.stalls ?? 0) + 1; paintStall(true); });
  v.addEventListener('playing', () => paintStall(false));
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
// What the operator actually played is recorded as "watched" automatically (no extra button). A jump ends the
// current watched stretch at the frame before the jump; a stretch shorter than half a second is ignored.
export function mergeRanges(rs) {
  const out = [];
  for (const r of [...rs].sort((a, b) => a.start_frame - b.start_frame)) {
    const last = out.at(-1);
    if (last && r.start_frame <= last.end_frame) last.end_frame = Math.max(last.end_frame, r.end_frame);
    else out.push({ start_frame: r.start_frame, end_frame: r.end_frame });
  }
  return out;
}
function commitWatched() {
  if (!S || S.watchFrom == null) return;
  const a = S.watchFrom, b = Math.min(S.total, S.frame + 1);
  S.watchFrom = S.playing ? S.frame : null;
  if (b - a < Math.max(2, Math.round(S.fps / 2))) return;
  const before = JSON.stringify(C().reviewed_ranges);
  const next = mergeRanges([...C().reviewed_ranges, { start_frame: a, end_frame: b }]);
  if (JSON.stringify(next) === before) return;
  C().reviewed_ranges = next; changed(); paintTimeline(); if (S.inspTab === 'event') paintInspector();
}
export function seekFrame(f, { keepPlaying = false } = {}) {
  if (S.playing) commitWatched();
  S.frame = clamp(Math.round(f), 0, S.total - 1);
  if (S.playing) S.watchFrom = S.frame;
  const v = $('#vid'); if (!keepPlaying) v.pause();
  v.currentTime = (S.frame + 0.5) / S.fps;
  paintPlayhead(); paintControls(); paintOverlay(); paintHud();
  if (S.inspTab === 'box') paintInspector();
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
  c.replaceChildren(...[
    btn(S.playing ? '❚❚' : '▶', togglePlay, 'ניגון / השהיה (רווח)', { 'data-testid': 'play' }),
    btn('◀|', () => step(-1), 'פריים אחורה (←)', { 'data-testid': 'step-back' }),
    btn('|▶', () => step(1), 'פריים קדימה (→)', { 'data-testid': 'step-fwd' }),
    h('span', { class: 'tc mono', 'data-testid': 'timecode' }, timecode(S.frame, S.fps)),
    h('span', { class: 'fr mono', 'data-testid': 'framenum' }, `frame ${S.frame} / ${S.total}`),
    h('span', { class: 'sep' }),
    h('div', { class: 'seg-ctl', role: 'group', 'aria-label': 'מהירות ניגון' }, SPEEDS.map(s => h('button', { 'aria-pressed': String(S.speed === s), onclick: () => setSpeed(s), 'data-testid': `speed-${s}` }, `${s}×`))),
    h('span', { class: 'sep' }),
    // Simple marking: the two actions that create an event are the big, labelled ones.
    // One button that changes with the state: "start event here" -> (play) -> "end event here".
    ...(S.mark.in == null
      ? [h('button', { class: 'btn primary mark-btn', title: 'התחל אירוע בנקודה הזו (מקש I)', 'data-testid': 'mark-in', onclick: () => markIn() }, '● התחל אירוע כאן')]
      : [h('button', { class: 'btn primary mark-btn recording', title: 'סיים את האירוע בנקודה הזו (מקש O)', 'data-testid': 'mark-out', onclick: () => markOut() }, '■ סיים אירוע כאן'),
         h('button', { class: 'btn sm', 'data-testid': 'mark-cancel', title: 'בטל את ההתחלה שסומנה (Esc)', onclick: () => { S.mark = { in: null, out: null }; paintMarks(); paintControls(); paintMarkLive(); } }, 'ביטול')]),
    btn('◁ אירוע קודם', () => jumpSeg(-1), 'אירוע קודם ([)'),
    btn('אירוע הבא ▷', () => jumpSeg(1), 'אירוע הבא (])'),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn sm', 'aria-pressed': String(!!S.moreControls), 'data-testid': 'more-controls', onclick: () => { S.moreControls = !S.moreControls; paintControls(); } }, 'עוד ⋯'),
    !S.moreControls ? null : h('span', { class: 'sep' }),
    !S.moreControls ? null : btn('－', () => zoom(0.7), 'הקטן ציר זמן'),
    !S.moreControls ? null : btn('＋', () => zoom(1.4), 'הגדל ציר זמן'),
    !S.moreControls ? null : btn('התאם', () => { fit(); refresh(); }, 'התאם ציר זמן'),
    // Quality mode toggle
    !S.moreControls ? null : h('label', { class: 'pill sm', style: { gap: '6px' } }, 'תצוגה:',
      h('select', {
        id: 'quality-select',
        'data-testid': 'quality-select',
        onchange: e => toggleQuality(e.target.value)
      },
        h('option', { value: 'proxy', selected: S.quality === 'proxy' }, 'מהירה (Proxy)'),
        h('option', { value: 'original', selected: S.quality === 'original' }, 'בדיקת מקור (4K)')
      )
    ),
    !S.moreControls ? null : btn('⌨', helpDialog, 'קיצורי מקלדת (?)'),
    !S.moreControls ? null : h('button', { class: 'btn sm', 'aria-pressed': String(S.overlay), onclick: () => { S.overlay = !S.overlay; refresh(); }, title: 'הצג / הסתר תיבות' }, 'תיבות'),
    !S.moreControls ? null : h('button', { class: 'btn sm', 'aria-pressed': String(S.insp), onclick: () => { S.insp = !S.insp; $('#wb').classList.toggle('insp-off', !S.insp); setTimeout(() => { placeOverlay(); fit(false); refresh(); }, 30); }, title: 'פתח / סגור מפקח' }, 'מפקח')
  ].filter(x => x != null)); // hidden tools are null: never render them as text
}

function toggleQuality(mode) {
  if (mode === S.quality) return;
  S.quality = mode;
  const v = $('#vid');
  const curTime = v.currentTime;
  v.src = mediaUrl();
  v.currentTime = curTime;
  toast(mode === 'original' ? 'הועבר למצב בדיקת מקור (4K מקורי)' : 'הועבר למצב תצוגה מהירה (Proxy)');
  refresh();
}

function togglePlay() { const v = $('#vid'); if (v.paused) { v.playbackRate = S.speed; v.play(); } else v.pause(); }
function step(n) { seekFrame(S.frame + n); }
function setSpeed(s) { S.speed = s; $('#vid').playbackRate = s; paintControls(); }
function markIn() { S.mark.in = S.frame; S.mark.out = null; paintMarks(); paintControls(); paintMarkLive(); }
function markOut() {
  if (S.mark.in == null) return toast('לחץ קודם "התחל אירוע כאן"', true);
  // Either direction works: if the operator went back before the start, the event spans the two points.
  const a = Math.min(S.mark.in, S.frame), b = Math.max(S.mark.in, S.frame) + 1;
  if (b - a < 2) return toast('האירוע קצר מדי: נגן קדימה ואז לחץ "סיים אירוע כאן"', true);
  S.mark = { in: null, out: null }; paintMarkLive();
  createSegment(a, b);
  toast(`נוצר אירוע מ־${timecode(a, S.fps)} עד ${timecode(b, S.fps)}. ענה על השאלות בצד.`);
}
// While an event is open: a growing bar on the timeline and a badge on the video, so it is obvious what is being marked.
function paintMarkLive() {
  const on = S?.mark?.in != null;
  const bar = $('#mklive'), badge = $('#hudmark');
  if (bar) { bar.style.display = on ? '' : 'none'; if (on) { const a = Math.min(S.mark.in, S.frame), b = Math.max(S.mark.in, S.frame) + 1; bar.style.left = `${xOf(a)}px`; bar.style.width = `${Math.max(3, xOf(b - a))}px`; } }
  if (badge) { badge.style.display = on ? '' : 'none'; if (on) badge.textContent = `● מסמן אירוע: מ־${timecode(Math.min(S.mark.in, S.frame), S.fps)} עד ${timecode(Math.max(S.mark.in, S.frame) + 1, S.fps)}`; }
}
function createSegment(s, e, athlete = null) {
  const id = uid();
  const a = athlete ?? (selSeg()?.athlete_id ?? null);
  edit(c => c.segments.push({
    id,
    start_frame: s,
    end_frame: e,
    athlete_id: a,
    event_type: (o => o.some(t => t.key === 'wave_ride') ? 'wave_ride' : o[0]?.key ?? 'wave_ride')(eventOptions(S.src.primary_sport_id ?? null, null)),
    // Operator decision (2026-11-04), management by exception: a marked event is usable and included unless the
    // operator says otherwise ("לא שמיש" / "רק חלק" / "החרג"). Replaces the earlier "never default positive" rule.
    decision: 'include',
    usability: 'usable',
    default_by_exception: true,
    reason_codes: [],
    reason_detail: '',
    key_moments: {},
    notes: '',
    framing_mode: null,
    target: null
  }));
  S.sel = id; S.inspTab = 'event'; refresh(); setTimeout(() => $('#f-athlete')?.focus(), 0);
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
      const el = h('div', {
        class: `sg ${cls}${S.sel === s.id ? ' sel' : ''}`,
        'data-id': s.id,
        'data-testid': 'segment',
        role: 'button',
        tabindex: 0,
        'aria-label': `${DECISION_HE[s.decision]} ${eventHe(s.event_type, effSport(s))} פריימים ${s.start_frame} עד ${s.end_frame}`,
        style: { left: `${xOf(s.start_frame)}px`, width: `${Math.max(4, xOf(s.end_frame - s.start_frame))}px`, top: `${4 + lane * 28}px`, borderColor: s.athlete_id ? athColor(s.athlete_id) : undefined }
      },
        h('span', { class: 'h l' }), `${icon} ${eventHe(s.event_type, effSport(s))}`, h('span', { class: 'h r' })
      );
      for (const k of C().keyframes.filter(k => k.segment_id === s.id && k.origin !== 'suggested')) {   // tracked points would clutter the bar
        el.append(h('i', { class: `kfm${k.origin === 'manual' ? '' : ' i'}`, style: { left: `${xOf(k.frame - s.start_frame)}px` } }));
      }
      bindSegment(el, s); row.append(el);
    }
    bindCreate(row, t.aid);
    inner.append(row);
    labels.append(h('div', { class: 'lab', style: { height: `${rowH}px` } }, h('span', { class: 'swatch', style: { background: t.aid ? athColor(t.aid) : 'var(--muted)' } }), t.aid ? athName(t.aid) : 'לא ידוע'));
  }
  const rv = h('div', { class: 'trk', style: { height: '30px' }, 'data-track': 'reviewed' });
  for (const r of C().reviewed_ranges) rv.append(h('div', { class: 'rv', title: `נצפה ${timecode(r.start_frame, S.fps)}–${timecode(r.end_frame, S.fps)}`, style: { left: `${xOf(r.start_frame)}px`, width: `${xOf(r.end_frame - r.start_frame)}px` } }));
  rv.append(h('div', { class: 'rv live', id: 'rvlive', style: { display: 'none' } }));
  inner.append(rv); labels.append(h('div', { class: 'lab', style: { height: '30px', color: 'var(--accent)' }, title: 'מתמלא לבד כשאתה מנגן את הסרטון' }, '▭ מה שצפית'));
  inner.append(h('div', { class: 'mklive', id: 'mklive', style: { display: 'none' } }), h('div', { class: 'ph', id: 'ph' }), h('div', { class: 'mk', id: 'mkin' }), h('div', { class: 'mk', id: 'mkout' }));
  paintPlayhead(); paintMarks();
}
function paintPlayhead() {
  const ph = $('#ph'); if (ph) ph.style.left = `${xOf(S.frame + 0.5)}px`;
  const tc = $('[data-testid=timecode]'), fr = $('[data-testid=framenum]');
  if (tc) tc.textContent = timecode(S.frame, S.fps); if (fr) fr.textContent = `frame ${S.frame} / ${S.total}`;
  const sc = $('#tlscroll'), x = xOf(S.frame);
  if (S.playing && (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 30)) sc.scrollLeft = x - 40;
  $('#ruler')?.setAttribute('aria-valuenow', S.frame);
  const live = $('#rvlive');
  if (live) { const on = S.playing && S.watchFrom != null && S.frame > S.watchFrom; live.style.display = on ? '' : 'none'; if (on) { live.style.left = `${xOf(S.watchFrom)}px`; live.style.width = `${xOf(S.frame + 1 - S.watchFrom)}px`; } }
  paintMarkLive();
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
  el.addEventListener('click', e => { e.stopPropagation(); S.sel = s.id; refresh(); });
  el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); S.sel = s.id; seekFrame(s.start_frame); refresh(); } });
  el.addEventListener('pointerdown', e => {
    e.stopPropagation();
    const mode = e.target.classList.contains('l') ? 'l' : e.target.classList.contains('r') ? 'r' : 'm';
    const row = el.parentElement, startF = frameAt(e, row, true), orig = { ...s }; let moved = false;
    // Select WITHOUT re-rendering the timeline: a re-render would detach this element and drop the pointer capture,
    // which made dragging the edges (changing the event's length) silently do nothing.
    S.sel = s.id; el.setPointerCapture(e.pointerId); S.dragging = true;
    el.parentElement?.parentElement?.querySelectorAll('.sg.sel').forEach(x => x.classList.remove('sel')); el.classList.add('sel');
    const mv = ev => {
      const d = frameAt(ev, row, true) - startF; if (!d && !moved) return;
      if (!moved) { snapshot(); moved = true; }
      const len = orig.end_frame - orig.start_frame;
      if (mode === 'm') { const ns = clamp(orig.start_frame + d, 0, S.total - len); s.start_frame = ns; s.end_frame = ns + len; }
      else if (mode === 'l') s.start_frame = clamp(orig.start_frame + d, 0, orig.end_frame - 1);
      else s.end_frame = clamp(orig.end_frame + d, orig.start_frame + 1, S.total);
      el.style.left = `${xOf(s.start_frame)}px`; el.style.width = `${xOf(s.end_frame - s.start_frame)}px`;
      // show the frame at the edge being dragged, so the new start/end is chosen by looking at the video
      if (mode !== 'm') { const f = mode === 'l' ? s.start_frame : s.end_frame - 1; if (f !== S.frame) seekFrame(f); }
    };
    const up = () => {
      el.removeEventListener('pointermove', mv); el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up);
      S.dragging = false;
      if (moved) {
        C().keyframes = C().keyframes.filter(k => k.segment_id !== s.id || (k.frame >= s.start_frame && k.frame < s.end_frame));
        const removed = repairOutOfRange(C());
        if (removed.length) toast(`הוסר אחרי שינוי האירוע: ${removed.join(' · ')}`);
        changed();
      } else seekFrame(S.frame);
      refresh();
    };
    el.addEventListener('pointermove', mv); el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    paintInspector();
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

// ---------------- bounding boxes & verification ----------------
function boxAt(segId, f) {
  const ks = C().keyframes.filter(k => k.segment_id === segId).sort((a, b) => a.frame - b.frame);
  const exact = ks.find(k => k.frame === f);
  const ver = latestVerification(C(), segId, f);   // the log is append-only: the LATEST decision is in force

  if (exact) {
    return {
      bbox: exact.bbox,
      kf: exact,
      interp: exact.origin !== 'manual',
      verification_status: ver?.status || exact.verification_status || 'unreviewed'
    };
  }
  const a = [...ks].reverse().find(k => k.frame < f), b = ks.find(k => k.frame > f);
  if (!a || !b) return null;
  const t = (f - a.frame) / (b.frame - a.frame), L = (p, q) => p + (q - p) * t;
  return {
    bbox: { x: L(a.bbox.x, b.bbox.x), y: L(a.bbox.y, b.bbox.y), w: L(a.bbox.w, b.bbox.w), h: L(a.bbox.h, b.bbox.h) },
    kf: null,
    interp: true,
    // No keyframe at this frame => nothing here can be a verified box (a positive decision needs an exact-frame box).
    verification_status: ver && !['verified_correct', 'corrected'].includes(ver.status) ? ver.status : 'unreviewed'
  };
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
    const isSel = s.id === S.sel, col = s.athlete_id ? athColor(s.athlete_id) : '#4cc9f0';

    const isVerified = b.verification_status === 'verified_correct';
    const isWrong = b.verification_status === 'wrong_performer';
    const isCorrected = b.verification_status === 'corrected';

    const strokeCol = isWrong ? '#ff777e' : isCorrected ? '#ffa657' : isVerified ? '#3ddc97' : col;
    const strokeDash = isVerified ? '' : '6 4';

    const r = svgEl('rect', {
      class: `bx${b.interp ? ' interp' : ''}${isSel ? ' sel' : ''}`,
      x: b.bbox.x * W, y: b.bbox.y * H, width: b.bbox.w * W, height: b.bbox.h * H,
      stroke: strokeCol,
      'stroke-dasharray': strokeDash,
      'data-testid': 'bbox', 'data-seg': s.id, 'data-interp': b.interp,
      'data-verified': isVerified,
      opacity: isSel ? 1 : 0.6
    });

    r.addEventListener('pointerdown', e => {
      e.stopPropagation();
      S.sel = s.id;
      S.inspTab = 'box'; // Clicking on box opens verification inspector
      if (isSel) dragBox(e, s, b, 'move'); else refresh();
    });
    svg.append(r);

    if (isSel) {
      // Resize handle
      const hd = svgEl('rect', { x: (b.bbox.x + b.bbox.w) * W - 6, y: (b.bbox.y + b.bbox.h) * H - 6, width: 12, height: 12, fill: strokeCol, style: 'cursor:nwse-resize;pointer-events:all' });
      hd.addEventListener('pointerdown', e => { e.stopPropagation(); dragBox(e, s, b, 'size'); });
      svg.append(hd);

      // Box Tag
      const statusText = isVerified ? ' ✓ תקין' : isWrong ? ' ✕ גולש שגוי' : isCorrected ? ' ✎ תוקן' : b.kf?.origin === 'manual' ? ' · סומן ידנית' : ' · מעקב אוטומטי';
      const athLabel = s.athlete_id ? athName(s.athlete_id) : 'לא ידוע';

      // Measure the label so the tag fits it exactly; with direction=rtl the text anchor is its RIGHT edge.
      const lbl = svgEl('text', { y: Math.max(14, b.bbox.y * H - 7), fill: '#06222c', 'font-size': 12, 'font-weight': 'bold', direction: 'rtl', 'data-testid': 'bbox-label' });
      lbl.textContent = `${athLabel}${statusText}`;
      svg.append(lbl);
      const tw = (() => { try { return lbl.getComputedTextLength(); } catch { return lbl.textContent.length * 7; } })() || lbl.textContent.length * 7;
      const tx = clamp(b.bbox.x * W, 0, Math.max(0, W - tw - 12));
      lbl.setAttribute('x', tx + tw + 6);
      const tagBg = svgEl('rect', { x: tx, y: Math.max(0, b.bbox.y * H - 22), width: tw + 12, height: 20, rx: 4, fill: strokeCol });
      svg.insertBefore(tagBg, lbl);
    }
  }
  // Whole-video track: shown on every frame where no event box of that athlete is drawn. Drag it to correct it.
  const shown = new Set(C().segments.filter(x => S.frame >= x.start_frame && S.frame < x.end_frame && boxAt(x.id, S.frame)).map(x => x.athlete_id ?? null));
  for (const t of C().tracks ?? []) {
    if (shown.has(t.athlete_id ?? null)) continue;
    const tb = trackBoxAt(t, S.frame); if (!tb) continue;
    const col = t.athlete_id ? athColor(t.athlete_id) : '#4cc9f0';
    const r = svgEl('rect', { class: 'bx interp sel', x: tb.bbox.x * W, y: tb.bbox.y * H, width: tb.bbox.w * W, height: tb.bbox.h * H, stroke: col, 'stroke-dasharray': tb.origin === 'manual' ? '' : '6 4', 'data-testid': 'track-box', 'data-track-box': t.id, style: 'cursor:move' });
    r.addEventListener('pointerdown', e => { e.stopPropagation(); dragBox(e, null, tb, 'move', t.athlete_id ?? null); });
    svg.append(r);
    const hd = svgEl('rect', { x: (tb.bbox.x + tb.bbox.w) * W - 6, y: (tb.bbox.y + tb.bbox.h) * H - 6, width: 12, height: 12, fill: col, style: 'cursor:nwse-resize;pointer-events:all' });
    hd.addEventListener('pointerdown', e => { e.stopPropagation(); dragBox(e, null, tb, 'size', t.athlete_id ?? null); });
    svg.append(hd);
    const lbl = svgEl('text', { x: tb.bbox.x * W + 4, y: Math.max(12, tb.bbox.y * H - 5), fill: col, 'font-size': 12, 'font-weight': 'bold' });
    lbl.textContent = `${t.athlete_id ? athName(t.athlete_id) : 'גולש'} · ${tb.origin === 'manual' ? 'סומן ידנית' : 'מעקב (גרור לתיקון)'}`;
    svg.append(lbl);
  }
  if (S.tool === 'box') ov.onpointerdown = drawBox; else ov.onpointerdown = null;
}

const svgEl = (t, a) => { const e = document.createElementNS('http://www.w3.org/2000/svg', t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
const norm = (e, ov) => { const r = ov.getBoundingClientRect(); return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) }; };

function putKeyframe(s, bbox, provenance = 'manual') {
  const bb = { x: +bbox.x.toFixed(5), y: +bbox.y.toFixed(5), w: +bbox.w.toFixed(5), h: +bbox.h.toFixed(5) };
  if (bb.w < 0.003 || bb.h < 0.003) return;
  edit(c => {
    const ex = c.keyframes.find(k => k.segment_id === s.id && k.frame === S.frame);
    if (ex) {
      ex.original_bbox = ex.bbox;
      ex.bbox = bb;
      ex.origin = provenance;
      ex.verification_status = 'unreviewed';
      ex.verified_at = null;
      ex.verified_by = null;
    } else {
      c.keyframes.push({
        id: uid(),
        segment_id: s.id,
        frame: S.frame,
        bbox: bb,
        visibility: 'visible',
        origin: provenance,
        verification_status: 'unreviewed',
        verified_at: null,
        verified_by: null
      });
    }
    // Geometry changed: any earlier human decision at this frame no longer applies (kept as history, not deleted).
    const last = latestVerification(c, s.id, S.frame);
    if (last && last.status !== 'unreviewed') appendVerification(c, s, S.frame, 'unreviewed', { invalidation: 'geometry_changed', original_bbox: last.bbox ?? undefined });
  });
}

// ---- automatic tracking: one box per athlete that follows them through the WHOLE video ----
// The operator draws a box once, anywhere in the video. The tracker follows the athlete back to the first frame and on
// to the last. Every box the operator draws or drags becomes an anchor: the stretch between two anchors is tracked from
// both sides and, frame by frame, the more confident result is kept - so one correction fixes the boxes before AND
// after it. Tracked boxes are estimates ('suggested', dashed); wrong ones are flagged, never approved one by one.
const R5 = b => ({ x: +b.x.toFixed(5), y: +b.y.toFixed(5), w: +b.w.toFixed(5), h: +b.h.toFixed(5) });
const trackOf = (c, athleteId) => (c.tracks ?? []).find(t => (t.athlete_id ?? null) === (athleteId ?? null));
/** Track box at a frame: the exact point, or interpolated between the two neighbouring points (never extrapolated). */
function trackBoxAt(t, f) {
  if (!t?.points?.length) return null;
  const pts = t.points.filter(p => p.flag !== 'wrong');
  const ex = pts.find(p => p.frame === f); if (ex) return { bbox: ex.bbox, origin: ex.origin, exact: true };
  let a = null, b = null;
  for (const p of pts) { if (p.frame < f && (!a || p.frame > a.frame)) a = p; if (p.frame > f && (!b || p.frame < b.frame)) b = p; }
  if (!a || !b || b.frame - a.frame > Math.max(12, S.fps)) return null;   // no box across a gap the tracker could not bridge
  const k = (f - a.frame) / (b.frame - a.frame), L = (u, v) => u + (v - u) * k;
  return { bbox: { x: L(a.bbox.x, b.bbox.x), y: L(a.bbox.y, b.bbox.y), w: L(a.bbox.w, b.bbox.w), h: L(a.bbox.h, b.bbox.h) }, origin: 'suggested', exact: false };
}
/** Record a hand-drawn / dragged box as an anchor of the athlete's track (inside an edit). */
function setAnchor(c, athleteId, frame, bbox) {
  c.tracks ??= [];
  let t = trackOf(c, athleteId);
  if (!t) { t = { id: uid(), athlete_id: athleteId ?? null, points: [] }; c.tracks.push(t); }
  t.points = t.points.filter(p => p.frame !== frame);
  t.points.push({ frame, bbox: R5(bbox), origin: 'manual' });
  t.points.sort((x, y) => x.frame - y.frame);
  return t;
}
/** Copy the track into the events of that athlete, so the event's BOX check works on it (estimates only). */
function syncSegmentsFromTrack(c, t) {
  for (const s of c.segments) {
    if ((s.athlete_id ?? null) !== (t.athlete_id ?? null)) continue;
    const checked = f => !!latestVerification(c, s.id, f);
    const prev = new Map(c.keyframes.filter(k => k.segment_id === s.id && k.origin === 'suggested').map(k => [k.frame, k.id]));
    c.keyframes = c.keyframes.filter(k => !(k.segment_id === s.id && k.origin === 'suggested' && !checked(k.frame)));
    const taken = new Set(c.keyframes.filter(k => k.segment_id === s.id).map(k => k.frame));
    for (const p of t.points) {
      if (p.flag === 'wrong' || p.frame < s.start_frame || p.frame >= s.end_frame || taken.has(p.frame)) continue;
      c.keyframes.push({ id: prev.get(p.frame) ?? uid(), segment_id: s.id, frame: p.frame, bbox: { ...p.bbox }, visibility: 'visible', origin: p.origin === 'manual' ? 'manual' : 'suggested', verification_status: 'unreviewed', verified_at: null, verified_by: null });
    }
  }
}
/**
 * (Re)track an athlete. With `around` = an anchor frame, only the stretches touching that anchor are redone;
 * without it, the whole video. Runs in the background with a progress pill; edits are applied at the end in one step.
 */
/**
 * Tracking requests go into a queue and are processed one after the other: a new box never throws away work in
 * progress. Each stretch (between two anchors, or from an anchor to the video's start/end) is saved as soon as it is
 * done, so leaving the page or drawing another box loses at most the stretch being computed.
 */
function trackAthlete(athleteId, around = null) {
  S.trackQueue ??= [];
  const same = q => (q.athleteId ?? null) === (athleteId ?? null);
  if (around == null) S.trackQueue = S.trackQueue.filter(q => !same(q));            // a full pass covers everything
  else if (S.trackQueue.some(q => same(q) && q.around == null)) return pumpTracking(); // already queued in full
  if (!S.trackQueue.some(q => same(q) && q.around === around)) S.trackQueue.push({ athleteId, around });
  pumpTracking();
}
async function pumpTracking() {
  if (!S || S.trackBusy) return;
  const mine = S;                                   // a pass belongs to the video it started on
  mine.trackBusy = true;
  try {
    if (mine.copy && !mine.copy.url && !mine.copy.failed) { mine.tracking = { pct: 0, waiting: true, ctl: new AbortController() }; paintTrackHud(); await mine.copyReady; } while (S === mine && mine.trackQueue?.length) { const q = mine.trackQueue.shift(); await runTrack(q.athleteId, q.around); } }
  finally { mine.trackBusy = false; mine.tracking = null; if (S === mine) { paintTrackHud(); refresh(); } }
}
/** Stretches to (re)compute, from the anchors as they are NOW. */
function trackUnits(t, around) {
  const anchors = t.points.filter(p => p.origin === 'manual').sort((a, b) => a.frame - b.frame);
  if (!anchors.length) return [];
  const last = S.total - 1, units = [];
  const k = around == null ? -1 : anchors.findIndex(p => p.frame === around);
  const i0 = around == null || k < 0 ? 0 : Math.max(0, k - 1), i1 = around == null || k < 0 ? anchors.length - 1 : Math.min(anchors.length - 1, k + 1);
  if (i0 === 0 && anchors[0].frame > 0) units.push([{ from: anchors[0].frame, to: 0, bbox: anchors[0].bbox }]);
  for (let i = i0; i < i1; i++) {
    const A = anchors[i], B = anchors[i + 1];
    if (B.frame - A.frame < 2) continue;
    units.push([{ from: A.frame, to: B.frame - 1, bbox: A.bbox, pair: true }, { from: B.frame, to: A.frame + 1, bbox: B.bbox, pair: true }]);
  }
  if (i1 === anchors.length - 1 && anchors.at(-1).frame < last) units.push([{ from: anchors.at(-1).frame, to: last, bbox: anchors.at(-1).bbox }]);
  return units;
}
async function runTrack(athleteId, around) {
  const mine = S, alive = () => S === mine;          // never write into another video opened meanwhile
  const t0 = trackOf(C(), athleteId); if (!t0) return;
  const units = trackUnits(t0, around); if (!units.length) return;
  const ctl = new AbortController(), me = { athleteId, pct: 0, ctl, queued: S.trackQueue?.length ?? 0 };
  S.tracking = me; paintTrackHud(); paintInspector();
  const src = mediaUrl();
  const step = Math.max(1, Math.round(S.fps / 10));
  const work = units.flat().reduce((n, j) => n + Math.abs(j.to - j.from), 0) || 1;
  let done = 0; const lostAll = [], bestAll = new Set();
  try {
    for (const unit of units) {
      if (ctl.signal.aborted || !alive()) return;
      const results = [];
      for (const j of unit) {
        const span = Math.abs(j.to - j.from);
        const r = await trackBox({ src, fps: S.fps, from: j.from, to: j.to, bbox: j.bbox, step, signal: ctl.signal, hold: () => alive() && !!S?.playing,
          onProgress: p => { if (!alive()) return ctl.abort(); me.pct = (done + p * span) / work; paintTrackHud(); } });
        results.push({ ...j, ...r }); done += span;
      }
      if (ctl.signal.aborted || !alive()) return;
      const { best, lost } = fuseUnit(results);
      lostAll.push(...lost); for (const f of best.keys()) bestAll.add(f);
      commitUnit(athleteId, results, best);       // saved now, not at the end
    }
  } catch (e) {
    if (!alive()) return;
    S.trackErr = { ...(S.trackErr ?? {}), [athleteId ?? '']: e.code === 'CORS'
      ? 'מעקב אוטומטי לא זמין לסרטון הזה: הדפדפן לא מורשה לקרוא את הווידאו מהענן (חסרה הרשאת CORS). ה-BOX נשמר בפריים שציירת.'
      : `המעקב האוטומטי נעצר: ${e.message}` };
    return;
  }
  if (!alive()) return;
  if (S.trackErr) delete S.trackErr[athleteId ?? ''];
  const gaps = lostAll.filter(f => !bestAll.has(f)).sort((a, b) => a - b);
  S.trackLost = { ...(S.trackLost ?? {}), [athleteId ?? '']: gaps.length ? gaps : null };
  if (gaps.length) toast(`המעקב איבד את הגולש ב-${gaps.map(f => timecode(f, S.fps)).join(', ')}. גרור/צייר שם את ה-BOX על הגולש, והמעקב יתוקן לפני ואחרי.`, true);
  else if (!S.trackQueue?.length) toast('ה-BOX עוקב אחרי הגולש לאורך כל הסרטון. אם משהו לא במקום - גרור אותו, והמעקב יתוקן לפני ואחרי.');
}
/** Two sides of a stretch: cut back a side that ends far from the other anchor, then keep per frame the side nearer its own anchor. */
function fuseUnit(results) {
  const cen = b => [b.x + b.w / 2, b.y + b.h / 2], dia = b => Math.hypot(b.w, b.h);
  const far = (p, q, k = 0.5) => { const [ax, ay] = cen(p), [bx2, by2] = cen(q); return Math.hypot(ax - bx2, ay - by2) > k * Math.max(dia(p), dia(q)); };
  for (const r of results) {
    if (!r.pair) continue;
    const other = results.find(o => o.pair && o !== r); if (!other) continue;
    const otherAt = new Map(other.boxes.map(b => [b.frame, b.bbox]));
    const ordered = [...r.boxes].sort((a, b) => Math.abs(b.frame - r.from) - Math.abs(a.frame - r.from));
    const drop = new Set();
    for (const b of ordered) {
      const o = otherAt.get(b.frame);
      if (o) { if (far(b.bbox, o)) { drop.add(b.frame); continue; } break; }
      const steps = Math.abs(other.from - b.frame) / Math.max(1, Math.round(S.fps / 10));
      if (far(b.bbox, other.bbox, 0.5 + 0.35 * steps)) { drop.add(b.frame); continue; }
      break;
    }
    r.boxes = r.boxes.filter(b => !drop.has(b.frame));
  }
  const best = new Map(), lost = [];
  for (const r of results) {
    if (!r.pair && r.lost == null && r.boxes.length && !r.boxes.some(b => b.frame === r.to)) { const e = r.boxes.reduce((m, b) => Math.abs(b.frame - r.to) < Math.abs(m.frame - r.to) ? b : m); if (Math.abs(e.frame - r.to) <= Math.max(3, Math.round(S.fps / 10))) r.boxes.push({ ...e, frame: r.to }); }
    if (r.lost != null) lost.push(r.lost);
    const span = Math.max(1, Math.abs(r.to - r.from));
    for (const b of r.boxes) { const eff = 0.3 * b.score + (1 - Math.abs(b.frame - r.from) / span); /* errors grow with distance from the anchor */ const o = best.get(b.frame); if (!o || eff > o.eff) best.set(b.frame, { ...b, eff }); }
  }
  return { best, lost };
}
function commitUnit(athleteId, results, best) {
  const lo = Math.min(...results.map(j => Math.min(j.from, j.to))), hi = Math.max(...results.map(j => Math.max(j.from, j.to)));
  edit(c => {
    const t = trackOf(c, athleteId); if (!t) return;
    const anchorF = new Set(t.points.filter(p => p.origin === 'manual').map(p => p.frame));
    t.points = t.points.filter(p => p.origin === 'manual' || p.frame < lo || p.frame > hi);
    for (const [f, b] of best) if (!anchorF.has(f)) t.points.push({ frame: f, bbox: R5(b.bbox), origin: 'suggested' });
    t.points.sort((x, y) => x.frame - y.frame);
    syncSegmentsFromTrack(c, t);
  }, { quiet: true });
  // never re-render the timeline under a drag in progress (it would drop the pointer capture); the drag repaints on release
  if (!S.dragging) paintTimeline(); paintOverlay(); if (S.inspTab === 'event' && !S.dragging) paintInspector();
}
/** True when the track does not yet cover the whole video densely (left unfinished, or made before this version). */
function trackIncomplete(t) {
  const pts = (t?.points ?? []).map(p => p.frame).sort((a, b) => a - b);
  if (!pts.length) return false;
  if (pts[0] > 0 || pts.at(-1) < S.total - 1) return true;
  const maxGap = 4 * Math.max(1, Math.round(S.fps / 10));
  for (let i = 1; i < pts.length; i++) if (pts[i] - pts[i - 1] > maxGap) return true;
  return false;
}
/** Compatibility entry point used by the event screen: the event's athlete, anchored at frame f0. */
function autoTrack(s, f0) { return trackAthlete(s?.athlete_id ?? null, f0); }
function paintStall(on) {
  const el = $('#hudstall'); if (!el) return;
  el.style.display = on ? '' : 'none';
  if (!on) return;
  if (S.copy && !S.copy.url && !S.copy.failed) return (el.style.display = 'none');   // the download pill already says it
  const r = S.src.byte_size && S.total ? S.src.byte_size * 8 / (S.total / S.fps) / 1e6 : null, mbps = r == null ? null : r < 10 ? r.toFixed(1) : Math.round(r);
  el.textContent = `טוען את הווידאו…${mbps != null ? ` (קובץ ${mbps} Mb/s)` : ''}${S.stalls > 1 ? ' · מהירות 0.5× או מעבר פריים־פריים (חיצים) חלקים יותר' : ''}`;
}
function paintTrackHud() {
  const el = $('#hudtrack'); if (!el) return;
  const t = S?.tracking;
  el.style.display = t ? '' : 'none';
  if (t?.waiting) return el.replaceChildren('המעקב יתחיל כשהסרטון יירד לדפדפן');
  if (t) el.replaceChildren(`עוקב אחרי הגולש… ${Math.round(t.pct * 100)}%${S.trackQueue?.length ? ` (+${S.trackQueue.length} בתור)` : ''} `, h('button', { class: 'btn sm', 'data-testid': 'track-cancel', onclick: () => { S.trackQueue = []; t.ctl.abort(); S.tracking = null; paintTrackHud(); toast('המעקב נעצר. מה שכבר חושב נשמר.'); } }, 'עצור'));
}
function retrackHere(s) {
  const aid = s?.athlete_id ?? null;
  if (!trackOf(C(), aid)?.points.some(p => p.origin === 'manual')) return toast('צייר קודם תיבה על הגולש (B)', true);
  trackAthlete(aid, null);
}
/** The one athlete every event of this video is about (null when there are none or several). */
function soleEventAthlete(c) {
  const ids = new Set(c.segments.map(s => s.athlete_id ?? null)); ids.delete(null);
  return ids.size === 1 ? [...ids][0] : null;
}
/** Who a box drawn with no event/athlete selected belongs to: the video owner, else the only athlete of its events. */
function defaultBoxAthlete(c) { return S.src.owner_athlete_id ?? soleEventAthlete(c) ?? null; }
/**
 * Boxes drawn before an athlete was chosen live on a track with no athlete, so no event got them. When the video's
 * events are all about one athlete, that track is theirs: hand its anchors over (merging with the athlete's own track
 * if there is one) and re-track. Returns true when something was claimed.
 */
function claimOrphanTrack() {
  const x = soleEventAthlete(C()), orphan = (C().tracks ?? []).find(t => (t.athlete_id ?? null) === null);
  if (!x || !orphan || !orphan.points.length) return false;
  const merge = !!trackOf(C(), x);
  edit(c => {
    const o = c.tracks.find(t => t.id === orphan.id), mine = trackOf(c, x);
    if (!mine) o.athlete_id = x;
    else {
      const own = new Set(mine.points.filter(p => p.origin === 'manual').map(p => p.frame));
      for (const p of o.points) if (p.origin === 'manual' && !own.has(p.frame)) setAnchor(c, x, p.frame, p.bbox);
      c.tracks = c.tracks.filter(t => t !== o);
    }
    syncSegmentsFromTrack(c, trackOf(c, x));
  }, { quiet: true });
  toast('BOX שסומן לפני שנבחר גולש שויך לגולש של האירועים.');
  if (merge) setTimeout(() => S && trackAthlete(x, null), 300);
  return true;
}
/** Events that have no boxes yet while the track covers them (saved before events took boxes from the track). */
function syncEventsOnOpen() {
  const c = structuredClone(C());
  for (const t of c.tracks ?? []) syncSegmentsFromTrack(c, t);
  const sig = ks => ks.map(k => JSON.stringify([k.segment_id, k.frame, k.bbox, k.origin, k.id])).sort().join();
  if (sig(c.keyframes) === sig(C().keyframes)) return;   // already in step: opening a video never rewrites it
  edit(cc => { for (const t of cc.tracks ?? []) syncSegmentsFromTrack(cc, t); }, { quiet: true });
}
/** Boxes drawn before video-level tracking existed: turn an event's hand-drawn boxes into anchors, once. */
function adoptLegacyBoxes() {
  // an approved video whose draft IS the approved version is never changed behind the operator's back
  // (no resume / re-sync / re-assign): any change would silently make it "changed since approval"
  if (S.draft.approved_current) return;
  claimOrphanTrack();
  syncEventsOnOpen();
  // an existing track that does not cover the whole video yet (left unfinished) is completed in the background
  for (const t of C().tracks ?? []) if (trackIncomplete(t) && t.points.some(p => p.origin === 'manual')) setTimeout(() => S && trackAthlete(t.athlete_id ?? null, null), 300);
  for (const s of C().segments) {
    const man = C().keyframes.filter(k => k.segment_id === s.id && k.origin === 'manual');
    if (!man.length || trackOf(C(), s.athlete_id ?? null)) continue;
    edit(c => { for (const k of man) setAnchor(c, s.athlete_id ?? null, k.frame, k.bbox); }, { quiet: true });
    setTimeout(() => S && trackAthlete(s.athlete_id ?? null, null), 300);
    return;
  }
}

// Append-only per-frame decision log (spec §21.2.4). Each entry is bound to the exact geometry and performer it attests.
function latestVerification(c, segId, frame) {
  let best = null;   // array position decides (append-only log), exactly like the server
  for (const v of c.box_verifications || []) if (v && v.segment_id === segId && v.frame === frame) best = v;
  return best;
}
function appendVerification(c, s, frame, status, extra = {}) {
  if (!c.box_verifications) c.box_verifications = [];
  const kf = c.keyframes.find(k => k.segment_id === s.id && k.frame === frame);
  const prev = latestVerification(c, s.id, frame);
  // Strictly increasing timestamps per frame so "latest" is unambiguous even within one millisecond.
  const at = new Date(Math.max(Date.now(), prev ? Date.parse(prev.verified_at) + 1 : 0)).toISOString();
  const entry = { segment_id: s.id, frame, status, athlete_id: s.athlete_id ?? null, verified_by: 'operator', verified_at: at, ...extra };
  if (!entry.bbox && kf?.bbox) entry.bbox = { ...kf.bbox };
  for (const k of Object.keys(entry)) if (entry[k] === undefined) delete entry[k];
  c.box_verifications.push(entry);
  if (kf) kf.verification_status = status;
  return entry;
}
const boxSame = (a, b) => !!a && !!b && ['x', 'y', 'w', 'h'].every(k => Math.abs(a[k] - b[k]) <= 1e-6);
/** Before every save: any positive decision no longer backed by the exact box/performer gets an explicit invalidation. */
function reconcileVerifications(c) {
  if (!c.box_verifications) c.box_verifications = [];
  const segs = new Map(c.segments.map(x => [x.id, x]));
  // Decisions about deleted segments or frames now outside a trimmed segment are moved to history, never silently dropped.
  const keep = [], gone = [];
  for (const v of c.box_verifications) { const s = segs.get(v.segment_id); (s && v.frame >= s.start_frame && v.frame < s.end_frame ? keep : gone).push(v); }
  if (gone.length) { c.box_verification_history = [...(c.box_verification_history || []), ...gone]; c.box_verifications = keep; }
  const seen = new Set();
  for (const v of [...c.box_verifications]) {
    const key = `${v.segment_id}:${v.frame}`; if (seen.has(key)) continue; seen.add(key);
    const last = latestVerification(c, v.segment_id, v.frame); if (!last) continue;
    if (last.status !== 'verified_correct' && last.status !== 'corrected') continue;
    const s = segs.get(v.segment_id), kf = c.keyframes.find(k => k.segment_id === v.segment_id && k.frame === v.frame);
    const why = !kf ? 'keyframe_removed' : !boxSame(kf.bbox, last.bbox) ? 'geometry_changed' : (s.athlete_id ?? null) !== (last.athlete_id ?? null) ? 'performer_changed' : (kf.visibility === 'occluded' || kf.visibility === 'not_visible') ? 'segment_changed' : null;
    if (why) appendVerification(c, s, v.frame, 'unreviewed', { invalidation: why, bbox: kf?.bbox ? { ...kf.bbox } : undefined });
  }
  for (const k of c.keyframes) {
    const last = latestVerification(c, k.segment_id, k.frame);
    const eff = last ? last.status : 'unreviewed';
    if ((k.verification_status ?? 'unreviewed') !== eff) k.verification_status = eff;
  }
}
/** Performer change: identity verifications made for the previous performer stop counting (spec §22.2 P0-1, item 5). */
function setSegmentAthlete(segId, athleteId) {
  edit(c => {
    const s = c.segments.find(x => x.id === segId); if (!s) return;
    if ((s.athlete_id ?? null) === (athleteId ?? null)) return;
    s.athlete_id = athleteId ?? null;
    reconcileVerifications(c);
  });
}
async function refreshStates() {
  if (!S || S.setId !== 'primary') return;   // states/track QA describe the primary Ground Truth stream
  try { S.states = await api(`/api/sources/${S.src.id}/states`); if (S.inspTab === 'box' || S.inspTab === 'event') paintInspector(); } catch { /* informational panel only */ }
}

function drawBox(e) {
  // A box can be drawn on ANY frame of the video. Inside the selected event it is also that event's box.
  const s = selSeg(), inSeg = !!s && S.frame >= s.start_frame && S.frame < s.end_frame;
  const aid = s?.athlete_id ?? defaultBoxAthlete(C());
  const ov = $('#ov'), a = norm(e, ov); const svg = $('#ovsvg'); const W = ov.clientWidth, H = ov.clientHeight, g = svgEl('rect', { class: 'bx', x: a.x * W, y: a.y * H, width: 0, height: 0, stroke: '#fff' }); svg.append(g); ov.setPointerCapture(e.pointerId);
  let box = null;
  const mv = ev => { const b = norm(ev, ov); box = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) }; for (const [k, v] of [['x', box.x * W], ['y', box.y * H], ['width', box.w * W], ['height', box.h * H]]) g.setAttribute(k, v); };
  const up = () => {
    ov.removeEventListener('pointermove', mv); ov.removeEventListener('pointerup', up);
    if (!box || box.w < 0.003 || box.h < 0.003) return paintOverlay();
    placeAnchor(inSeg ? s : null, aid, S.frame, box);
  };
  ov.addEventListener('pointermove', mv); ov.addEventListener('pointerup', up);
}
/** A drawn or dragged box: anchor of the athlete's whole-video track (+ the event's own box when inside an event). */
function placeAnchor(s, aid, f0, box) {
  if (s) putKeyframe(s, box, 'manual');
  edit(c => setAnchor(c, aid, f0, box), { quiet: true });
  S.tool = 'select';
  refresh();
  trackAthlete(aid, f0);
}

function dragBox(e, s, b, mode, aid = s?.athlete_id ?? null) {
  const ov = $('#ov'), a = norm(e, ov), o = { ...b.bbox }; let nb = o; ov.style.pointerEvents = 'auto'; ov.setPointerCapture(e.pointerId);
  const rect = e.target.closest('rect.bx') ?? (s ? $(`[data-seg="${s.id}"]`) : $('[data-track-box]'));
  const mv = ev => { const p = norm(ev, ov), dx = p.x - a.x, dy = p.y - a.y;
    nb = mode === 'move' ? { ...o, x: clamp(o.x + dx, 0, 1 - o.w), y: clamp(o.y + dy, 0, 1 - o.h) } : { ...o, w: clamp(o.w + dx, 0.004, 1 - o.x), h: clamp(o.h + dy, 0.004, 1 - o.y) };
    const W = ov.clientWidth, H = ov.clientHeight; rect?.setAttribute('x', nb.x * W); rect?.setAttribute('y', nb.y * H); rect?.setAttribute('width', nb.w * W); rect?.setAttribute('height', nb.h * H); };
  const up = () => {
    ov.removeEventListener('pointermove', mv); ov.removeEventListener('pointerup', up); ov.style.pointerEvents = '';
    if (nb !== o) {
      toast('ה-BOX תוקן. המעקב מתעדכן לפני ואחרי הנקודה הזו.');
      placeAnchor(s && S.frame >= s.start_frame && S.frame < s.end_frame ? s : null, aid, S.frame, nb);
    } else refresh();
  };
  ov.addEventListener('pointermove', mv); ov.addEventListener('pointerup', up);
}

function fillInterpolated(s) {
  const man = C().keyframes.filter(k => k.segment_id === s.id && k.origin === 'manual').sort((a, b) => a.frame - b.frame);
  if (man.length < 2) return toast('נדרשים לפחות שני קיפריימים ידניים', true);
  edit(c => {
    c.keyframes = c.keyframes.filter(k => !(k.segment_id === s.id && k.origin === 'interpolated'));
    for (let i = 0; i < man.length - 1; i++) for (let f = man[i].frame + 10; f < man[i + 1].frame; f += 10) {
      const t = (f - man[i].frame) / (man[i + 1].frame - man[i].frame), L = (p, q) => +(p + (q - p) * t).toFixed(5);
      c.keyframes.push({
        id: uid(),
        segment_id: s.id,
        frame: f,
        bbox: { x: L(man[i].bbox.x, man[i + 1].bbox.x), y: L(man[i].bbox.y, man[i + 1].bbox.y), w: L(man[i].bbox.w, man[i + 1].bbox.w), h: L(man[i].bbox.h, man[i + 1].bbox.h) },
        visibility: 'visible',
        origin: 'interpolated',
        verification_status: 'unreviewed' // Explicitly unreviewed!
      });
    }
  });
  toast('נוצרו קיפריימים משוערים (אינטרפולציה) — מסומנים לבדיקה ולא כמאומתים');
}

// ---------------- inspector ----------------
function paintInspector() {
  const el = $('#insp'); if (!el) return;
  // Simple marking mode: no tab bar. The event flow is the home screen; "שיוך הסרטון" and "בדיקת BOX" open as
  // sub-screens with one clear way back.
  if (S.inspTab === 'associate' || S.inspTab === 'box') {
    const title = S.inspTab === 'box' ? 'בדיקת BOX לאורך האירוע' : 'שיוך הסרטון: בעלים ומי מופיע';
    const back = h('div', { class: 'insp-back' },
      h('button', { class: 'btn sm', 'data-testid': 'insp-tab-event', onclick: () => { S.inspTab = 'event'; refresh(); } }, '→ חזרה לאירוע'),
      h('strong', {}, title));
    el.replaceChildren(back, S.inspTab === 'box' ? renderBoxQATab() : renderAssociateTab());
    return;
  }
  el.replaceChildren(renderEventTab());
}

function emptyGuide() {
  const segs = C().segments;
  return h('div', { class: 'guide', 'data-testid': 'mark-guide' },
    h('h3', {}, 'איך מסמנים אירוע'),
    h('ol', {},
      h('li', {}, 'נגן (רווח) עד תחילת הרכיבה ולחץ ', h('b', {}, '● התחל אירוע כאן'), '.'),
      h('li', {}, 'המשך לנגן. פס כתום גדל בציר הזמן. בסוף הרכיבה לחץ ', h('b', {}, '■ סיים אירוע כאן'), '.'),
      h('li', {}, 'ענה על 3 השאלות שיופיעו כאן: מי, שימושי?, לדאטהסט?')),
    h('div', { class: 'meta' }, 'אפשר גם לגרור בשורת הגולש בציר הזמן כדי ליצור אירוע. הכל נשמר אוטומטית, ו"שמור עכשיו" למעלה שומר מיד.'),
    segs.length ? h('div', {},
      h('div', { class: 'meta', style: { marginTop: '8px' } }, `אירועים בסרטון (${segs.length}), לחץ כדי לערוך:`),
      h('ul', { class: 'list', 'data-testid': 'event-list' }, segs.map((x, i) => h('li', { style: { cursor: 'pointer' }, onclick: () => { S.sel = x.id; seekFrame(x.start_frame); refresh(); } },
        h('b', {}, `${i + 1}.`), h('span', { style: { flex: 1 } }, ` ${eventInfo(effSport(x), x.event_type)?.label_he ?? x.event_type ?? 'אירוע'} · ${x.athlete_id ? athName(x.athlete_id) : 'ללא ביצוע'}`),
        h('span', { class: 'mono ltr meta' }, timecode(x.start_frame, S.fps)))))) : null);
}

// Inspector Tab 1: Event Annotation
function renderEventTab() {
  const s = selSeg();
  const cov = (() => { const m = new Uint8Array(S.total); for (const r of C().reviewed_ranges) m.fill(1, r.start_frame, r.end_frame); return m.reduce((a, b) => a + b, 0) / S.total; })();

  return h('div', { 'data-testid': 'insp-panel-event' },
    S.banner ? h('div', { class: `banner ${S.banner.kind}`, role: 'alert', 'data-testid': S.banner.testid ?? 'inspector-banner' }, S.banner.text, h('div', { style: { display: 'flex', gap: '6px', marginTop: '6px' } }, S.banner.action ? h('button', { class: 'btn sm', onclick: S.banner.action[1] }, S.banner.action[0]) : null, S.banner.action2 ? h('button', { class: 'btn sm', onclick: S.banner.action2[1] }, S.banner.action2[0]) : null)) : null,

    // Video owner: one line + a link to the association screen
    h('div', { class: 'owner-line', 'data-testid': 'owner-line' },
      h('span', {}, 'בעל הסרטון: ', h('strong', {}, S.src.owner_athlete_label || 'לא שויך')),
      h('button', { class: 'btn sm', 'data-testid': 'insp-tab-associate', onclick: () => { S.inspTab = 'associate'; refresh(); } }, 'שיוך הסרטון (בעלים, מי מופיע)')
    ),

    !s ? emptyGuide() : segForm(s),

    h('h3', {}, 'כמה מהסרטון צפית'),
    h('div', { class: 'cov-bar', 'data-testid': 'coverage', 'data-cov': String(Math.round(cov * 100)), title: 'הפס הכחול בציר הזמן מראה בדיוק מה צפית' },
      h('div', { class: 'cov-fill', style: { width: `${Math.round(cov * 100)}%` } })),
    h('div', { class: 'meta' }, cov >= 0.999 ? 'צפית בכל הסרטון ✓' : `צפית ב-${Math.round(cov * 100)}% מהסרטון. כל מה שאתה מנגן נרשם לבד (הפס הכחול "מה שצפית" בציר הזמן). חלק שלא צפית בו אינו "אין אירוע".`),
    cov >= 0.999 ? null : h('div', { style: { display: 'flex', gap: '6px', marginTop: '6px', flexWrap: 'wrap' } },
      h('button', { class: 'btn', 'data-testid': 'reviewed-all', onclick: () => edit(c => { c.reviewed_ranges = [{ start_frame: 0, end_frame: S.total }]; }) }, 'צפיתי בכל הסרטון (גם בלי לנגן כאן)')),
    h('details', { class: 'more', 'data-testid': 'watched-fix', style: { marginTop: '6px' } },
      h('summary', {}, 'תיקון ידני של מה שצפית'),
      h('div', { class: 'meta' }, 'לחץ "התחל אירוע כאן" בתחילת הקטע, עבור לסופו, ולחץ "סמן קטע כנצפה". "נקה" מוחק את כל הסימון.'),
      h('div', { style: { display: 'flex', gap: '6px', marginTop: '6px' } },
        h('button', { class: 'btn sm', 'data-testid': 'mark-reviewed', onclick: () => { const a = S.mark.in ?? 0, b = S.mark.out ?? S.frame + 1; if (b <= a) return toast('סמן התחלה ואז עבור לסוף הקטע שצפית', true); S.mark = { in: null, out: null }; paintMarkLive(); edit(c => { c.reviewed_ranges = mergeRanges([...c.reviewed_ranges, { start_frame: a, end_frame: b }]); }); } }, 'סמן קטע כנצפה'),
        h('button', { class: 'btn sm', 'data-testid': 'reviewed-clear', onclick: () => edit(c => { c.reviewed_ranges = []; }) }, 'נקה'))
    ),

    h('h3', {}, 'אישור סופי (Ground Truth)'),
    S.setId !== 'primary' ? setPanel() : statesPanel(),
    S.setId !== 'primary' ? null : approvalForm(),

    S.setId !== 'primary' ? null : h('h3', {}, 'היסטוריית גרסאות מאושרות', h('span', { class: 'pill' }, S.revs.length)),
    S.setId !== 'primary' ? null : h('ul', { class: 'list', 'data-testid': 'revlist' }, S.revs.length ? S.revs.map(r => h('li', {}, h('b', {}, `v${r.seq}`), h('span', { style: { flex: 1 }, class: 'meta' }, fmtDate(r.approved_at), r.reason ? ` · ${r.reason}` : ''), h('span', { class: 'mono ltr meta' }, r.digest.slice(0, 8)), h('button', { class: 'btn sm', title: 'טען כטיוטה', onclick: () => restoreRevision(r) }, 'שחזר'))) : [h('li', {}, 'אין גרסאות מאושרות')]),
    S.setId !== 'primary' ? null : h('details', { class: 'more', 'data-testid': 'reset-zone', style: { marginTop: '14px' } },
      h('summary', {}, 'טעיתי - קטלג את הסרטון מחדש'),
      h('div', { class: 'meta' }, 'מוחק את כל הסימונים של הסרטון הזה (אירועים, BOX, מעקב, מה שצפית) ומתחיל נקי. בעלים, ענף וגרסאות מאושרות לא משתנים. אפשר לבטל מיד אחרי.'),
      h('button', { class: 'btn danger', 'data-testid': 'reset-catalog', style: { marginTop: '6px' }, onclick: confirmReset }, 'קטלג מחדש'))
  );
}

// Inspector Tab 2: Video Ownership & People in Footage
function renderAssociateTab() {
  const visibleAppearances = S.src.locations || [];

  return h('div', { 'data-testid': 'insp-panel-associate', style: { display: 'flex', flexDirection: 'column', gap: '14px' } },
    h('div', { class: 'section', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px' } },
      h('strong', { style: { fontSize: '14px', display: 'block', marginBottom: '6px' } }, 'שיוך קטלוג ראשי (בעל הסרטון)'),
      h('p', { class: 'meta', style: { marginTop: 0 } }, 'שיוך זה עונה על "לאיזה גולש הסרטון שייך?". שיוך זה אינו קובע את מבצעי האירועים בסרטון.'),
      h('div', { style: { marginTop: '8px' } },
        h('label', { class: 'f' }, 'גולש משויך:'),
        h('select', {
          id: 'src-owner-select',
          'data-testid': 'src-owner-select',
          style: { width: '100%', marginBottom: '8px' },
          onchange: async e => {
            const newOwner = e.target.value || null;
            const reassign = !!S.src.owner_athlete_id && S.src.owner_athlete_id !== newOwner;
            if (reassign && !confirm(`הסרטון משויך כרגע ל-${athName(S.src.owner_athlete_id)}. לשנות את השיוך? (השינוי יתועד בהיסטוריה)`)) { e.target.value = S.src.owner_athlete_id; return; }
            try {
              const res = await api(`/api/sources/${S.src.id}/catalog-owner`, {
                method: 'POST',
                body: { owner_athlete_id: newOwner, reason: 'שינוי במפקח', expected_version: S.src.owner_version ?? 0, confirm_reassign: reassign }
              });
              S.src.owner_athlete_id = res.owner_athlete_id;
              S.src.owner_status = res.owner_status;
              S.src.owner_athlete_label = res.athlete?.label || null;
              S.src.owner_version = res.owner_version;
              toast(res.owner_athlete_id ? `הסרטון שויך ל-${res.athlete?.label}` : 'השיוך הוסר');
              paintStatus();
              refresh();
            } catch (err) {
              if (err.code === 'VERSION_CONFLICT' || err.status === 409) {
                toast(err.message || 'השיוך שונה במקביל — מרענן נתוני שיוך...', true);
                const fresh = await api(`/api/sources/${S.src.id}/catalog-owner`);
                S.src.owner_athlete_id = fresh.owner_athlete_id;
                S.src.owner_status = fresh.owner_status;
                S.src.owner_athlete_label = fresh.athlete?.label || null;
                S.src.owner_version = fresh.owner_version;
                paintStatus();
                refresh();
              } else {
                toast(err.message, true);
              }
            }
          }
        },
          h('option', { value: '' }, '— לא משויך (Unassigned) —'),
          S.athletes.map(a => h('option', { value: a.id, selected: a.id === S.src.owner_athlete_id }, a.label))
        )
      ),
      h('div', { style: { display: 'flex', gap: '6px' } },
        h('input', { type: 'text', id: 'new-owner-name', placeholder: 'גולש חדש...', style: { flex: 1 } }),
        h('button', {
          class: 'btn sm primary',
          onclick: async () => {
            const v = $('#new-owner-name').value.trim();
            if (!v) return toast('הזן שם גולש', true);
            if (S.src.owner_athlete_id && !confirm(`הסרטון משויך כרגע ל-${athName(S.src.owner_athlete_id)}. ליצור גולש חדש ולשייך אליו?`)) return;
            try {
              const created = await api('/api/athletes', { method: 'POST', body: { label: v } });
              S.athletes.push(created);
              const res = await api(`/api/sources/${S.src.id}/catalog-owner`, {
                method: 'POST',
                body: { owner_athlete_id: created.id, reason: 'גולש חדש שנוצר במפקח', expected_version: S.src.owner_version ?? 0, confirm_reassign: !!S.src.owner_athlete_id }
              });
              S.src.owner_athlete_id = res.owner_athlete_id;
              S.src.owner_status = res.owner_status;
              S.src.owner_athlete_label = created.label;
              S.src.owner_version = res.owner_version;
              toast(`הגולש "${created.label}" נוצר ושויך לסרטון`);
              paintStatus();
              refresh();
            } catch (err) {
              if (err.code === 'VERSION_CONFLICT' || err.status === 409) {
                toast(err.message || 'השיוך שונה במקביל — מרענן נתוני שיוך...', true);
                const fresh = await api(`/api/sources/${S.src.id}/catalog-owner`);
                S.src.owner_athlete_id = fresh.owner_athlete_id;
                S.src.owner_status = fresh.owner_status;
                S.src.owner_athlete_label = fresh.athlete?.label || null;
                S.src.owner_version = fresh.owner_version;
                paintStatus();
                refresh();
              } else {
                toast(err.message, true);
              }
            }
          }
        }, '＋ צור ושייך')
      )
    ),

    h('div', { class: 'section', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px' } },
      h('strong', { style: { fontSize: '14px', display: 'block', marginBottom: '6px' } }, 'אנשים המופיעים בסרטון'),
      h('p', { class: 'meta', style: { marginTop: 0 } }, 'גולשים שנראים בסרטון — גם אם אינם בעלי הסרטון ואינם מבצעים אירוע. הוספה כאן אינה יוצרת אירוע ואינה משנה את הבעלות.'),
      h('div', { class: 'fieldrow', 'data-testid': 'visible-people', style: { display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' } },
        (S.appearances ?? []).length ? (S.appearances ?? []).map(ap => {
          const isPerformer = C().segments.some(seg => seg.athlete_id === ap.athlete_id);
          const isOwner = S.src.owner_athlete_id === ap.athlete_id;
          return h('div', { class: 'card', 'data-testid': 'visible-person', style: { padding: '6px 10px', display: 'flex', alignItems: 'center', gap: '8px' } },
            h('span', { class: 'swatch', style: { background: athColor(ap.athlete_id) } }), h('span', {}, athName(ap.athlete_id)),
            ap.uncertain ? pill('נראה — לא ודאי', 'warn') : pill('נראה', 'ok'),
            isOwner ? pill('בעלים', 'ok') : null, isPerformer ? pill('מבצע אירוע', 'warn') : null);
        }) : h('div', { class: 'meta' }, 'לא סומנו גולשים נראים.')),
      h('div', { style: { display: 'flex', gap: '6px', marginTop: '8px' } },
        h('select', { id: 'add-visible', 'data-testid': 'add-visible-select', style: { flex: 1 } }, h('option', { value: '' }, '— הוסף גולש שנראה בסרטון —'),
          S.athletes.filter(a => !(S.appearances ?? []).some(x => x.athlete_id === a.id)).map(a => h('option', { value: a.id }, a.label))),
        h('label', { class: 'meta', style: { display: 'flex', gap: '4px', alignItems: 'center' } }, h('input', { type: 'checkbox', id: 'add-visible-unc' }), 'לא ודאי'),
        h('button', { class: 'btn sm', 'data-testid': 'add-visible', onclick: async () => {
          const id = $('#add-visible').value; if (!id) return toast('בחר גולש', true);
          try { await api(`/api/sources/${S.src.id}/appearances`, { method: 'POST', body: { athlete_id: id, uncertain: $('#add-visible-unc').checked } }); S.appearances = (await api(`/api/sources/${S.src.id}/appearances`)).items; toast(`${athName(id)} סומן כנראה בסרטון`); refresh(); } catch (e) { toast(e.message, true); }
        } }, '＋ נראה בסרטון'))
    ),

    h('button', { class: 'btn primary', onclick: () => { S.inspTab = 'event'; refresh(); } }, '← חזרה לתיוג אירוע')
  );
}

// Inspector Tab 3: Box QA & Temporal Verification
/** One human decision about the box at `frame` (bound to that exact box and the current performer). */
/** Management by exception: after looking over the strip, every box not marked wrong/hidden is accepted at once. */
function acceptRest(s) {
  if (!s.athlete_id) return toast('בחר קודם מי ביצע את האירוע', true);
  let n = 0;
  edit(c => {
    for (const k of c.keyframes.filter(k => k.segment_id === s.id).sort((a, b) => a.frame - b.frame)) {
      if (latestVerification(c, s.id, k.frame)) continue;
      appendVerification(c, s, k.frame, 'verified_correct', { method: 'exception_review' }); n++;
    }
  });
  toast(`${n} תיבות סומנו כתקינות (כל מה שלא סימנת כשגוי)`);
}
function decideAt(s, frame, status) {
  const cur = boxAt(s.id, frame);
  if (frame < s.start_frame || frame >= s.end_frame) return toast('הפריים מחוץ לאירוע', true);
  if (status === 'verified_correct') {
    if (!s.athlete_id) return toast('לא ניתן לאשר BOX לפני שבוחרים מי ביצע את האירוע', true);
    if (!cur?.bbox) return toast(`אין BOX בפריים ${frame} — אין מה לאשר`, true);
  }
  if (status === 'wrong_performer' && !cur?.bbox) return toast(`אין BOX בפריים ${frame}`, true);
  edit(c => {
    if (status === 'wrong_performer') { const tp = trackOf(c, s.athlete_id ?? null)?.points.find(p => p.frame === frame && p.origin === 'suggested'); if (tp) tp.flag = 'wrong'; }
    let kf = c.keyframes.find(k => k.segment_id === s.id && k.frame === frame);
    if (status === 'verified_correct' && !kf) {
      // The operator checked the estimated position at this exact frame: materialize it, keeping its origin.
      kf = { id: uid(), segment_id: s.id, frame, bbox: { ...cur.bbox }, visibility: 'visible', origin: 'interpolated', verification_status: 'unreviewed' };
      c.keyframes.push(kf);
    }
    if (status === 'occluded' && kf) kf.visibility = 'occluded';
    const NOTE = { verified_correct: 'אושר על הגולש הנכון', wrong_performer: 'גולש שגוי / סטייה', occluded: 'הגולש מוסתר / לא נראה', indeterminate: 'לא ניתן לקבוע' };
    appendVerification(c, s, frame, status, { bbox: (kf?.bbox ?? cur?.bbox) ? { ...(kf?.bbox ?? cur.bbox) } : undefined, notes: NOTE[status] });
  });
}

// ---- BOX track strip: zoomed thumbnails of the box along the whole event, each decided with one click ----
const thumbs = new Map();   // `${src}|${frame}|${bbox}` -> canvas
let thumbVid = null, thumbQueue = Promise.resolve();
function stripFrames(s, cps) {
  const out = new Set(cps.map(c => c.frame));
  for (const k of C().keyframes) if (k.segment_id === s.id && k.origin !== 'suggested') out.add(k.frame);   // tracked points are covered by the even spread
  const span = s.end_frame - s.start_frame, n = Math.min(16, span);
  for (let i = 0; i < n; i++) out.add(s.start_frame + Math.floor((i + 0.5) * span / n));
  return [...out].filter(f => f >= s.start_frame && f < s.end_frame && boxAt(s.id, f)?.bbox).sort((a, b) => a - b).slice(0, 36);
}
function grabThumb(frame, bbox, color) {
  const key = `${S.src.id}|${frame}|${[bbox.x, bbox.y, bbox.w, bbox.h].map(v => v.toFixed(4)).join(',')}`;
  if (thumbs.has(key)) return Promise.resolve(thumbs.get(key));
  const srcId = S.src.id, url = S.quality === 'original' ? S.src.playback_url : mediaUrl(), fps = S.fps;
  const job = thumbQueue.then(async () => {
    while (S?.playing) await new Promise(r => setTimeout(r, 250));   // thumbnails wait while the video plays
    if (!thumbVid || thumbVid.dataset.src !== url) {
      thumbVid = document.createElement('video'); thumbVid.muted = true; thumbVid.preload = 'metadata'; thumbVid.dataset.src = url; thumbVid.src = url;
      await new Promise((res, rej) => { thumbVid.onloadedmetadata = res; thumbVid.onerror = () => rej(new Error('video')); });
    }
    await new Promise(res => { thumbVid.onseeked = res; thumbVid.currentTime = (frame + 0.5) / fps; });
    const vw = thumbVid.videoWidth, vh = thumbVid.videoHeight;
    const bx = bbox.x * vw, by = bbox.y * vh, bw = bbox.w * vw, bh = bbox.h * vh;
    let cw = Math.max(bw * 2.4, bh * 2.4 * 4 / 3, vh * 0.2), ch = cw * 3 / 4;
    cw = Math.min(cw, vw); ch = Math.min(ch, vh);
    const cx = Math.min(Math.max(bx + bw / 2 - cw / 2, 0), vw - cw), cy = Math.min(Math.max(by + bh / 2 - ch / 2, 0), vh - ch);
    const cv = document.createElement('canvas'); cv.width = 240; cv.height = 180;
    const g = cv.getContext('2d'); g.drawImage(thumbVid, cx, cy, cw, ch, 0, 0, 240, 180);
    const k = 240 / cw; g.strokeStyle = color; g.lineWidth = 2; g.strokeRect((bx - cx) * k, (by - cy) * k, bw * k, bh * k);
    thumbs.set(key, cv); return srcId === S?.src.id ? cv : null;
  });
  thumbQueue = job.catch(() => {});
  return job;
}
function trackStrip(s, cps) {
  const frames = stripFrames(s, cps);
  if (!frames.length) return null;
  const cpSet = new Set(cps.map(c => c.frame)), color = s.athlete_id ? athColor(s.athlete_id) : '#ffffff';
  const MARK = { verified_correct: '✓ נכון', corrected: '✓ תוקן', wrong_performer: '✕ שגוי', occluded: '◌ מוסתר', indeterminate: '? לא ידוע', unreviewed: 'לא נבדק' };
  const done = frames.filter(f => (latestVerification(C(), s.id, f)?.status ?? 'unreviewed') !== 'unreviewed').length;
  return h('div', { 'data-testid': 'track-strip' },
    h('label', { class: 'f' }, `מסלול ה-BOX לאורך האירוע. סמן רק תמונה שבה המסגרת לא על ${athName(s.athlete_id) ?? 'הגולש'} (✕), או לחץ "תקן" וגרור. כל השאר נחשב תקין.`),
    (() => {
      const open = C().keyframes.filter(k => k.segment_id === s.id && !latestVerification(C(), s.id, k.frame)).length;
      return h('div', { style: { display: 'flex', gap: '6px', alignItems: 'center', margin: '6px 0', flexWrap: 'wrap' } },
        h('button', { class: `btn ${open ? 'primary' : ''}`, 'data-testid': 'accept-rest', disabled: !open, onclick: () => acceptRest(s) }, open ? `✓ עברתי על הרצועה - כל השאר תקין (${open})` : '✓ הרצועה נבדקה'),
        h('span', { class: 'meta' }, `${done}/${frames.length} תמונות סומנו`));
    })(),
    h('div', { class: 'strip' }, frames.map(f => {
      const b = boxAt(s.id, f), st = latestVerification(C(), s.id, f)?.status ?? 'unreviewed';
      const cv = h('canvas', { width: 240, height: 180, title: `מעבר לפריים ${f}`, onclick: () => seekFrame(f) });
      grabThumb(f, b.bbox, color).then(t => { if (t) cv.getContext('2d').drawImage(t, 0, 0); }).catch(() => {});
      const btn = (label, status, title, testid) => h('button', { class: 'btn sm', title, 'data-testid': testid, onclick: () => decideAt(s, f, status) }, label);
      return h('div', { class: `tile${S.frame === f ? ' cur' : ''}`, 'data-testid': 'strip-tile', 'data-frame': f, 'data-status': st },
        cv,
        h('div', { class: 'tlab' }, h('span', { class: 'ltr' }, `f${f}${cpSet.has(f) ? ' •' : ''}${b.kf ? '' : ' משוער'}`), h('span', {}, MARK[st] ?? st)),
        h('div', { class: 'tb' },
          // Exceptions only: mark what is wrong; everything not marked is accepted with one click below.
          btn('✕', 'wrong_performer', 'ה-BOX לא על הגולש בפריים הזה', 'tile-wrong'),
          btn('◌', 'occluded', 'הגולש מוסתר', 'tile-occluded'),
          h('button', { class: 'btn sm', 'data-testid': 'tile-fix', title: 'עבור לפריים וגרור את ה-BOX לגולש', onclick: () => { seekFrame(f); toast('גרור את ה-BOX על הגולש - המעקב יתוקן לפני ואחרי'); } }, 'תקן')));
    })),
    h('div', { class: 'meta' }, '• = נקודת בדיקה חשובה (התחלה, אמצע, סוף, קפיצה, הצטלבות). "משוער" = מיקום מהמעקב האוטומטי. מסמנים רק מה שלא תקין: ✕ אם ה-BOX לא על הגולש, או "תקן" כדי לגרור אותו. כל השאר נחשב תקין.'));
}

function renderBoxQATab() {
  const s = selSeg();
  if (!s) {
    return h('div', { class: 'empty', style: { padding: '16px' } },
      'בחר מקטע בציר הזמן כדי לבדוק ולאמת את ה-BOX של הגולש.',
      h('p', {}, h('button', { class: 'btn primary sm', onclick: () => { S.inspTab = 'event'; refresh(); } }, 'חזרה לתיוג אירוע'))
    );
  }

  // Ensure current playhead is within segment bounds when checking box QA
  if (S.frame < s.start_frame || S.frame >= s.end_frame) {
    seekFrame(s.start_frame);
  }

  const athlete = S.athletes.find(a => a.id === s.athlete_id);
  const curBox = boxAt(s.id, S.frame);
  const curVer = latestVerification(C(), s.id, S.frame);
  const kf = (C().keyframes || []).find(k => k.segment_id === s.id && k.frame === S.frame);
  // Required checkpoints and track status are computed by the server from the saved draft (single source of truth).
  const qa = S.states?.box_qa?.per_segment?.find(q => q.segment_id === s.id) ?? null;
  const stale = S.save !== 'saved';
  const REASON_HE = { start: 'תחילה', middle: 'אמצע', end: 'סוף', movement: 'שינוי תנועה', large_jump: 'קפיצה חדה', crossing: 'הצטלבות', crossing_exit: 'יציאה מהצטלבות', visibility_partial: 'נראות חלקית', visibility_occluded: 'הסתרה', visibility_not_visible: 'יצא מהפריים' };
  const TRACK_HE = { not_checked: ['טרם נבדק', 'warn'], partially_checked: ['נבדק חלקית', 'warn'], verified_in_checked_range: ['אומת בטווח שנבדק', 'ok'], needs_correction: ['דורש תיקון', 'bad'], cannot_determine: ['לא ניתן לקבוע', 'warn'] };
  const DEC_HE = { verified_correct: '✓', corrected: '✎', wrong_performer: '✕', occluded: '◌', indeterminate: '?', unreviewed: '·', stale: '⟳' };
  const st = curVer?.status ?? 'unreviewed';
  const statusCls = st === 'verified_correct' || st === 'corrected' ? 'ok' : st === 'wrong_performer' ? 'bad' : 'warn';
  const statusMsg = !curBox
    ? 'אין BOX בפריים זה — צייר BOX על הגולש (כלי B) כדי לבדוק אותו'
    : st === 'verified_correct' || st === 'corrected'
      ? '✓ פריים זה נבדק: ה-BOX על הגולש הנכון (חל על פריים זה בלבד)'
      : st === 'wrong_performer'
        ? '✕ דורש תיקון: ה-BOX אינו על הגולש — גרור/צייר מחדש ואז אמת'
        : st === 'occluded' ? '◌ סומן: הגולש מוסתר / לא נראה בפריים זה'
          : st === 'indeterminate' ? '? סומן: לא ניתן לקבוע בפריים זה'
            : curVer?.invalidation ? '⟳ ה-BOX או הגולש השתנו אחרי הבדיקה — נדרשת בדיקה מחדש'
              : kf && kf.origin === 'manual' ? 'טרם נבדק — BOX שצויר ידנית ממתין לבדיקה (ציור ≠ אימות)'
                : '⚠ מיקום משוער (אינטרפולציה) — אינו מאומת עד שתבדוק אותו';
  const [trackText, trackCls] = TRACK_HE[qa?.status] ?? ['—', 'warn'];
  const cps = qa?.required_checkpoints ?? [];

  return h('div', { 'data-testid': 'insp-panel-box', style: { display: 'flex', flexDirection: 'column', gap: '12px' } },
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      h('strong', {}, 'אימות BOX על הגולש'),
      pill(athlete?.label || 'לא נבחר גולש מבצע', athlete ? 'ok' : 'warn')
    ),
    !s.athlete_id ? h('div', { class: 'banner warn' }, 'כדי לאמת BOX יש לבחור קודם מי ביצע את הפעולה (לשונית "תיוג אירוע").') : null,

    h('div', { class: `banner ${statusCls}`, 'data-testid': 'box-verify-banner' }, statusMsg),
    trackStrip(s, cps),

    h('div', { class: 'stats', style: { margin: '4px 0' } },
      h('div', { class: 'stat', 'data-testid': 'track-qa-status', 'data-status': qa?.status ?? '' }, h('b', {}, h('span', { class: `pill ${trackCls}` }, trackText)), h('span', {}, stale ? 'מצב המעקב (יתעדכן אחרי שמירה)' : 'מצב מעקב ה-BOX במקטע')),
      h('div', { class: 'stat' }, h('b', { class: 'ltr' }, qa ? `${qa.checked_frames}/${qa.box_frames}` : '—'), h('span', {}, 'פריימים שנבדקו / פריימי BOX')),
      h('div', { class: 'stat' }, h('b', { class: 'ltr' }, qa?.checked_range ? `f${qa.checked_range[0]}–f${qa.checked_range[1]}` : '—'), h('span', {}, 'טווח שנבדק')),
      h('div', { class: 'stat' }, h('b', { class: 'ltr' }, qa ? `${Math.round((qa.event_span_checked_ratio ?? 0) * 100)}%` : '—'), h('span', {}, 'מאורך האירוע בין פריימים שנבדקו')),
      h('div', { class: 'stat' }, h('b', {}, `f${S.frame}`), h('span', {}, 'פריים נוכחי'))
    ),
    qa?.crossings ? h('div', { class: 'banner warn' }, `זוהו ${qa.crossings} הצטלבויות עם גולשים אחרים — חובה לבדוק את הפריימים המסומנים.`) : null,

    h('div', {},
      h('label', { class: 'f' }, 'נקודות בדיקה נדרשות (כולל נקודות סיכון):'),
      cps.length ? h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' }, 'data-testid': 'checkpoints' },
        cps.map(cp => h('button', {
          class: `btn sm ${S.frame === cp.frame ? 'primary' : ''}`,
          title: cp.reasons.map(r => REASON_HE[r] ?? r).join(', '),
          onclick: () => seekFrame(cp.frame)
        }, `${DEC_HE[cp.decision] ?? '·'} ${cp.reasons.map(r => REASON_HE[r] ?? r).join('/')} (f${cp.frame})`))
      ) : h('div', { class: 'meta' }, 'אין עדיין BOX במקטע זה. BOX הוא אופציונלי; אם תצייר — יש לבדוק בתחילה, באמצע, בסוף ובנקודות סיכון.')
    ),

    // Verification Action Controls
    h('div', { class: 'section', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' } },
      h('strong', { style: { fontSize: '13px' } }, 'החלטת אימות לפריים הנוכחי:'),
      h('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' } },
        h('button', {
          class: 'btn primary sm',
          'data-testid': 'verify-box-confirm',
          disabled: !curBox?.bbox || !s.athlete_id || S.frame < s.start_frame || S.frame >= s.end_frame,
          title: !s.athlete_id ? 'יש לבחור גולש מבצע לפני אימות' : !curBox?.bbox ? 'אין BOX בפריים זה — צייר BOX קודם' : '',
          onclick: () => {
            if (!s.athlete_id) return toast('לא ניתן לאמת BOX ללא גולש מבצע ידוע', true);
            if (!curBox?.bbox) return toast('אין BOX בפריים זה — אין מה לאמת', true);
            edit(c => {
              let kf = c.keyframes.find(k => k.segment_id === s.id && k.frame === S.frame);
              if (!kf) {
                // The operator checked the interpolated position at this exact frame: materialize it, keeping its origin.
                kf = { id: uid(), segment_id: s.id, frame: S.frame, bbox: { ...curBox.bbox }, visibility: 'visible', origin: 'interpolated', verification_status: 'unreviewed' };
                c.keyframes.push(kf);
              }
              appendVerification(c, s, S.frame, 'verified_correct', { bbox: { ...kf.bbox }, notes: 'אושר על הגולש הנכון' });
            });
            toast(`פריים ${S.frame} אומת ידנית על הגולש (פריים זה בלבד)`);
          }
        }, '✓ נכון — על הגולש'),
        h('button', {
          class: 'btn danger sm',
          'data-testid': 'verify-box-wrong',
          disabled: !curBox?.bbox || S.frame < s.start_frame || S.frame >= s.end_frame,
          onclick: () => {
            edit(c => appendVerification(c, s, S.frame, 'wrong_performer', { bbox: { ...curBox.bbox }, notes: 'גולש שגוי / סטייה' }));
            toast(`פריים ${S.frame} סומן "דורש תיקון" — תקן את ה-BOX ואמת מחדש`, true);
          }
        }, '✕ גולש שגוי / לא על הגולש'),
        h('button', {
          class: 'btn sm',
          'data-testid': 'verify-box-occluded',
          disabled: S.frame < s.start_frame || S.frame >= s.end_frame,
          onclick: () => {
            edit(c => {
              const kf = c.keyframes.find(k => k.segment_id === s.id && k.frame === S.frame);
              if (kf) kf.visibility = 'occluded';
              appendVerification(c, s, S.frame, 'occluded', { bbox: curBox?.bbox ? { ...curBox.bbox } : undefined, notes: 'הגולש מוסתר / לא נראה' });
            });
            toast(`פריים ${S.frame}: הגולש מוסתר / לא נראה`);
          }
        }, '◌ מוסתר / לא נראה'),
        h('button', {
          class: 'btn sm',
          'data-testid': 'verify-box-indeterminate',
          disabled: S.frame < s.start_frame || S.frame >= s.end_frame,
          onclick: () => {
            edit(c => appendVerification(c, s, S.frame, 'indeterminate', { bbox: curBox?.bbox ? { ...curBox.bbox } : undefined, notes: 'לא ניתן לקבוע' }));
            toast(`פריים ${S.frame}: לא ניתן לקבוע`);
          }
        }, '? לא ניתן לקבוע')
      ),
      h('button', {
        class: 'btn sm',
        'data-testid': 'verify-box-correct',
        onclick: () => {
          S.tool = 'box';
          toast('מצב תיקון פעיל: גרור את התיבה או צייר מחדש על גבי הוידאו');
          refresh();
        }
      }, '✥ תקן BOX — גרור מלבן על הגולש')
    ),

    h('div', { class: 'meta', style: { fontSize: '11px', lineHeight: '1.4' } },
      'כלל מחייב: אימות חל אך ורק על פריימים שנבדקו פיזית על ידי המפעיל. פריימים משוערים באינטרפולציה אינם נחשבים מאומתים.'
    ),

    h('button', { class: 'btn primary', onclick: () => { S.inspTab = 'event'; refresh(); } }, '← חזרה לתיוג אירוע')
  );
}

async function restoreRevision(r) {
  const full = await api(`/api/revisions/${r.id}`); snapshot(); S.draft.content = full.content; S.sel = null; changed(); refresh(); toast(`נטענה גרסה v${r.seq} כטיוטה (הגרסה המאושרת לא שונתה)`);
}
function field(label, ctl, id) { return h('div', {}, h('label', { class: 'f', for: id }, label), ctl); }

function segForm(s) {
  const upd = (k, v) => edit(c => { const x = c.segments.find(y => y.id === s.id); x[k] = v; });
  const kfs = C().keyframes.filter(k => k.segment_id === s.id).sort((a, b) => a.frame - b.frame);

  const usabilityChoices = [
    ['usable', '✓ כן, שימושי'],
    ['partially_usable', '◐ רק חלק'],
    ['unusable', '✕ לא שמיש'],
    ['uncertain', '? לא יודע עדיין']
  ];

  const reasonList = REASON_LIST;
  const needReason = ['partially_usable', 'unusable'].includes(s.usability) || s.decision === 'exclude' || (s.reason_codes ?? []).length > 0;

  return h('div', { 'data-testid': 'segform', style: { display: 'flex', flexDirection: 'column', gap: '12px' } },
    h('div', { class: 'meta' }, h('span', { class: 'mono ltr' }, `[${s.start_frame}, ${s.end_frame})`), ` · ${s.end_frame - s.start_frame} פריימים · `, ltr(`${timecode(s.start_frame, S.fps)} → ${timecode(s.end_frame, S.fps)}`)),

    // Section 1: What happened
    h('div', { class: 'section', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px' } },
      h('strong', { style: { fontSize: '13px', display: 'block', marginBottom: '8px' } }, '1. מי ביצע ומה קרה?'),
      // One click for the common case: the video's owner performed the event (never applied automatically).
      !s.athlete_id && S.src.owner_athlete_id ? h('button', { class: 'btn primary sm', 'data-testid': 'performer-owner', style: { marginBottom: '6px' }, onclick: () => { setSegmentAthlete(s.id, S.src.owner_athlete_id); refresh(); } }, `זה ${S.src.owner_athlete_label ?? 'בעל הסרטון'} (בעל הסרטון)`) : null,
      field('מי ביצע את הפעולה?', h('div', { style: { display: 'flex', gap: '6px' } },
        h('select', { id: 'f-athlete', 'data-testid': 'athlete-select', onchange: e => { setSegmentAthlete(s.id, e.target.value || null); refresh(); } },
          h('option', { value: '' }, 'לא ידוע'),
          S.athletes.map((a, i) => h('option', { value: a.id, selected: a.id === s.athlete_id }, `${i + 1}. ${a.label}`))
        ),
        h('button', { class: 'btn sm', 'data-testid': 'new-athlete', onclick: newAthlete }, '＋ חדש')
      ), 'f-athlete'),
      // Addendum §3: a usable event names its primary person, or says explicitly that there is none / it is uncertain.
      !s.athlete_id ? field('אם אין גולש מבצע ידוע:', h('select', { id: 'f-primary', 'data-testid': 'primary-status', onchange: e => upd('primary_status', e.target.value || null) },
        h('option', { value: '' }, '— לא נקבע —'),
        [['uncertain_primary', 'לא ברור מי ביצע'], ['no_primary_action', 'אין מבצע ראשי לאירוע']].map(([k, l]) => h('option', { value: k, selected: s.primary_status === k }, l))), 'f-primary') : null,
      field('סוג אירוע', h('select', { id: 'f-type', 'data-testid': 'event-type', onchange: e => upd('event_type', e.target.value) },
        eventOptions(effSport(s), s.event_type).map(t => h('option', { value: t.key, selected: t.key === s.event_type }, t.label_he))
      ), 'f-type'),
      (effSport(s) != null || LEGACY.includes(s.event_type)) && !eventOptions(effSport(s), null).some(t => t.key === s.event_type)
        ? h('div', { class: 'banner bad', role: 'alert', 'data-testid': 'event-mismatch' }, `סוג האירוע "${s.event_type}" אינו שייך לענף "${sportName(effSport(s))}" — בחר סוג תקין לפני השמירה.`) : null,
      ...(eventInfo(effSport(s), s.event_type)?.required_attrs ?? []).map(a => field(`שדה חובה: ${a}`, h('input', { type: 'text', id: `f-attr-${a}`, 'data-testid': `attr-${a}`, value: s.attrs?.[a] ?? '', onchange: e => edit(c => { const x = c.segments.find(y => y.id === s.id); x.attrs = { ...(x.attrs ?? {}), [a]: e.target.value }; }) }), `f-attr-${a}`)),

    ),

    // Section 2: Usability
    h('div', { class: 'section', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px' } },
      h('strong', { style: { fontSize: '13px', display: 'block', marginBottom: '8px' } }, '2. האם הקטע שימושי לסרטון?', h('span', { class: 'meta', style: { fontWeight: 'normal', marginInlineStart: '6px' } }, 'מסומן שימושי - שנה רק אם לא')),
      h('div', { class: 'rad', role: 'group', 'aria-label': 'שימושיות', style: { gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px' } },
        usabilityChoices.map(([k, label]) => h('button', {
          class: 'btn sm',
          'aria-pressed': String((s.usability ?? 'uncertain') === k), // undecided legacy events never display as usable
          'data-testid': `usability-${k}`,
          onclick: () => upd('usability', k)
        }, label))
      ),
      // Reasons are asked only when they are needed (not usable / partly usable / excluded) or already given.
      !needReason ? null : h('label', { class: 'f', style: { marginTop: '8px' } }, 'למה? (בחר סיבה אחת או יותר)'),
      !needReason ? null : h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' }, 'data-testid': 'reason-codes' },
        reasonList.map(([code, label]) => {
          const codes = s.reason_codes || [];
          const active = codes.includes(code);
          return h('button', {
            class: `btn sm ${active ? 'primary' : ''}`,
            onclick: () => {
              const next = active ? codes.filter(x => x !== code) : [...codes, code];
              upd('reason_codes', next);
            }
          }, (active ? '✓ ' : '') + label);
        })
      )
    ),

    // Section 3: Ground Truth Inclusion Decision
    h('div', { class: 'section', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px' } },
      h('strong', { style: { fontSize: '13px', display: 'block', marginBottom: '8px' } }, '3. להכניס לדאטהסט?', h('span', { class: 'meta', style: { fontWeight: 'normal', marginInlineStart: '6px' } }, 'נכלל - שנה רק אם לא')),
      h('div', { class: 'rad', role: 'group', 'aria-label': 'החלטה' },
        [['include', 'inc', 'כלול', 'E'], ['exclude', 'exc', 'החרג', 'X'], ['uncertain', 'unc', 'לא בטוח', 'U']].map(([k, c, l, key]) =>
          h('button', {
            class: c,
            'aria-pressed': String(s.decision === k),
            'data-testid': `dec-${k}`,
            onclick: () => upd('decision', k)
          }, `${l} `, h('kbd', {}, key))
        )
      )
    ),

    // Boxes drawn before whole-video tracking existed become anchors once, and the athlete is tracked.
    (() => { if (!S.tracking && !(S.autoTried ??= new Set()).has('legacy')) { S.autoTried.add('legacy'); setTimeout(() => S && adoptLegacyBoxes(), 0); } return null; })(),
    // Section 4: BOX on the performer (optional)
    h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      h('strong', {}, '4. BOX על הגולש (רשות)'),
      pill(`${kfs.filter(k => k.origin !== 'suggested').length} תיבות`, kfs.length ? 'ok' : '')
    ),
    h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
      h('button', {
        class: 'btn sm primary',
        'aria-pressed': String(S.tool === 'box'),
        'data-testid': 'tool-box',
        onclick: () => { S.tool = S.tool === 'box' ? 'select' : 'box'; refresh(); }
      }, 'ציור תיבה ', h('kbd', {}, 'B')),
      h('button', { class: 'btn sm', 'data-testid': 'insp-tab-box', disabled: !kfs.length, title: kfs.length ? '' : 'צייר קודם תיבה על הגולש', onclick: () => { S.inspTab = 'box'; refresh(); } }, 'בדוק את ה-BOX לאורך האירוע ←')
    ),
    h('div', { class: 'meta' }, 'צייר תיבה על הגולש בפריים אחד, בכל מקום בסרטון: היא עוקבת אחריו לבד מתחילת הסרטון ועד סופו. אם היא סטתה באיזשהו רגע - גרור אותה לגולש באותו רגע, והמעקב מתוקן לפני ואחרי.'),
    (() => {
      const key = s.athlete_id ?? '', t = trackOf(C(), s.athlete_id ?? null), lost = S.trackLost?.[key];
      const pts = t?.points ?? [], tr = pts.filter(p => p.origin === 'suggested'), an = pts.filter(p => p.origin === 'manual');
      if (S.tracking && (S.tracking.athleteId ?? '') === key) return h('div', { class: 'banner warn', 'data-testid': 'track-running' }, `עוקב אחרי הגולש לאורך הסרטון… ${Math.round(S.tracking.pct * 100)}%`);
      return h('div', { style: { display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap', margin: '6px 0' } },
        pts.length ? pill(`מעקב לאורך הסרטון: ${timecode(pts[0].frame, S.fps)}–${timecode(pts.at(-1).frame, S.fps)} · ${an.length} תיבות ידניות · ${tr.length} משוערות`, 'warn') : null,
        S.trackErr?.[key] ? h('div', { class: 'banner bad', 'data-testid': 'track-failed', style: { width: '100%' } }, S.trackErr[key]) : null,
        lost ? h('button', { class: 'btn sm', 'data-testid': 'track-lost', onclick: () => seekFrame(lost[0]) }, `המעקב איבד את הגולש ב-${timecode(lost[0], S.fps)}: קפוץ לשם וגרור את ה-BOX`) : null,
        an.length ? h('button', { class: 'btn sm', 'data-testid': 'track-auto', onclick: () => retrackHere(s) }, '↻ עקוב שוב') : null);
    })(),
    kfs.length ? h('ul', { class: 'list', 'data-testid': 'kflist', style: { maxHeight: '160px', overflowY: 'auto' } }, kfs.filter(k => k.origin !== 'suggested').map(k => {
      const v = latestVerification(C(), s.id, k.frame);
      const st = v?.status ?? 'unreviewed';
      const ORIGIN = { manual: 'ידני', interpolated: 'אינטרפולציה', suggested: 'הצעה' };
      const ST = { verified_correct: ['✓ נבדק', 'ok'], corrected: ['✎ תוקן', 'ok'], wrong_performer: ['✕ דורש תיקון', 'bad'], occluded: ['◌ מוסתר', 'warn'], indeterminate: ['? לא ניתן לקבוע', 'warn'], unreviewed: [v?.invalidation ? '⟳ לבדיקה מחדש' : '· טרם נבדק', 'warn'] };
      return h('li', { style: { cursor: 'pointer' }, onclick: () => { seekFrame(k.frame); S.inspTab = 'box'; refresh(); } },
        h('span', { class: 'mono ltr' }, `f${k.frame}`), h('span', { class: 'meta', style: { flex: 1 } }, ORIGIN[k.origin] ?? k.origin), pill(ST[st][0], ST[st][1]));
    })) : null,

    // Everything else that can be recorded for the event, closed by default (opens by itself when already filled).
    h('details', { class: 'more', 'data-testid': 'event-more', open: S.moreOpen || !!(s.sport_id || s.notes || Object.values(s.key_moments ?? {}).some(v => v != null)) || undefined, ontoggle: e => { if (S) S.moreOpen = e.target.open; } },
      h('summary', {}, 'פרטים נוספים (רשות): רגעי מפתח, הערות, ענף, אותה פעולה בסרטון אחר'),
      // Key Moments
      h('label', { class: 'f' }, 'רגעי מפתח (סמן בפריים הנוכחי):'),
      h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
        h('button', {
          class: `btn sm ${s.key_moments?.takeoff_frame === S.frame ? 'primary' : ''}`,
          onclick: () => setKeyMoment(s, 'takeoff_frame', 'תחילת רכיבה')
        }, `תחילת רכיבה ${s.key_moments?.takeoff_frame ? `(f${s.key_moments.takeoff_frame})` : ''}`),
        h('button', {
          class: `btn sm ${s.key_moments?.peak_frame === S.frame ? 'primary' : ''}`,
          onclick: () => setKeyMoment(s, 'peak_frame', 'תמרון שיא')
        }, `תמרון שיא ${s.key_moments?.peak_frame ? `(f${s.key_moments.peak_frame})` : ''}`),
        h('button', {
          class: `btn sm ${s.key_moments?.landing_frame === S.frame ? 'primary' : ''}`,
          onclick: () => setKeyMoment(s, 'landing_frame', 'סיום/נפילה')
        }, `סיום/נפילה ${s.key_moments?.landing_frame ? `(f${s.key_moments.landing_frame})` : ''}`)
      ),
      field('הערות לאירוע', h('textarea', { id: 'f-notes', onchange: e => upd('notes', e.target.value) }, s.notes ?? ''), 'f-notes'),
      // Spec §18: an event may belong to a different sport than its source (restored after the V2 rewrite dropped it).
      field('ענף למקטע', h('select', { id: 'f-sport', 'data-testid': 'seg-sport', onchange: e => upd('sport_id', e.target.value || null) },
        h('option', { value: '' }, `כמו המקור (${sportName(S.src.primary_sport_id ?? null)})`),
        sportsList().filter(x => x.enabled || x.id === s.sport_id).map(x => h('option', { value: x.id, selected: x.id === s.sport_id }, x.name_he))), 'f-sport'),
      h('button', { class: 'btn sm', onclick: () => fillInterpolated(s) }, 'מלא BOX בין התיבות (משוער)'),
      S.setId === 'primary' ? actionPanel(s) : null
    ),

    h('div', { style: { marginTop: '10px' } },
      h('button', { class: 'btn danger sm', 'data-testid': 'delete-seg', onclick: deleteSel }, 'מחק אירוע ', h('kbd', {}, 'Del'))
    )
  );
}

function deleteSel() { const s = selSeg(); if (!s) return; edit(c => { c.segments = c.segments.filter(x => x.id !== s.id); c.keyframes = c.keyframes.filter(k => k.segment_id !== s.id); }); S.sel = null; refresh(); }

async function newAthlete() {
  const inp = h('input', { type: 'text', id: 'na-label', placeholder: 'שם / מזהה פסבדונימי' });
  const d = dialog('גולש חדש', h('div', {}, h('label', { class: 'f', for: 'na-label' }, 'תווית'), inp), [
    h('button', { class: 'btn primary', 'data-testid': 'na-ok', onclick: async () => { try { const a = await api('/api/athletes', { method: 'POST', body: { label: inp.value } }); S.athletes.push({ ...a, appearances: [] }); closeDialog(); const s = selSeg(); if (s) setSegmentAthlete(s.id, a.id); refresh(); } catch (e) { toast(e.message, true); } } }, 'צור'),
    h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')]);
  inp.focus(); inp.addEventListener('keydown', e => { if (e.key === 'Enter') $('[data-testid=na-ok]').click(); });
}

// Addendum §4: the same real-world action seen in several videos is ONE physical action with several occurrences.
function actionPanel(s) {
  const mine = (S.actions ?? []).filter(a => a.occurrences.some(o => o.source_id === S.src.id && o.segment_id === s.id));
  const others = (S.allActions ?? []).filter(a => !mine.includes(a) && a.action_type === s.event_type);
  const reload = async () => { const [m, all] = await Promise.all([api(`/api/physical-actions?source=${S.src.id}`), api('/api/physical-actions')]); S.actions = m.items; S.allActions = all.items; refresh(); };
  return h('div', { class: 'section', 'data-testid': 'action-panel', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px' } },
    h('strong', { style: { fontSize: '13px', display: 'block', marginBottom: '6px' } }, 'אותה פעולה בסרטון אחר (פעולה פיזית)'),
    mine.length ? mine.map(a => h('div', { class: 'meta', 'data-testid': 'action-linked' }, `מקושר לפעולה ${a.id.slice(0, 8)} · ${a.lineage_state} · ${a.occurrences.length} מופעים`))
      : h('div', { class: 'meta' }, 'האירוע לא מקושר לפעולה פיזית. קשר רק אם זו בדיוק אותה פעולה שצולמה בסרטון נוסף.'),
    !mine.length ? h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '6px' } },
      h('button', { class: 'btn sm', 'data-testid': 'action-create', onclick: async () => {
        try { if (S.save !== 'saved') await save(); const a = await api('/api/physical-actions', { method: 'POST', body: { action_type: s.event_type, sport_id: s.sport_id ?? S.src.primary_sport_id ?? null, primary_person_id: s.athlete_id ?? null } });
          await api(`/api/physical-actions/${a.id}/occurrences`, { method: 'POST', body: { source_id: S.src.id, segment_id: s.id, occurrence_role: 'canonical_view' } }); toast('נוצרה פעולה פיזית'); await reload(); } catch (e) { toast(e.message, true); }
      } }, '＋ פעולה פיזית חדשה מהאירוע'),
      others.length ? h('select', { id: 'link-action', 'data-testid': 'action-select' }, others.map(a => h('option', { value: a.id }, `${a.id.slice(0, 8)} · ${a.occurrences.length} מופעים`))) : null,
      others.length ? h('button', { class: 'btn sm', 'data-testid': 'action-link', onclick: async () => {
        try { if (S.save !== 'saved') await save(); await api(`/api/physical-actions/${$('#link-action').value}/occurrences`, { method: 'POST', body: { source_id: S.src.id, segment_id: s.id, occurrence_role: 'duplicate_view' } }); toast('האירוע קושר לפעולה'); await reload(); } catch (e) { toast(e.message, true); }
      } }, 'קשר כמבט נוסף') : null) : null);
}
function setPanel() {
  const done = S.draft.queue_status === 'completed';
  return h('div', { class: 'section', 'data-testid': 'set-panel', style: { background: 'var(--panel2)', border: '1px solid var(--line2)', borderRadius: 'var(--radius)', padding: '12px' } },
    h('div', { class: 'banner warn' }, 'זרם תיוג עצמאי: אינך רואה את עבודת הסטים האחרים עד שהסט שלך יוגש. התחלת מטיוטה ריקה.'),
    h('div', { class: 'meta' }, `סט: `, h('span', { class: 'mono ltr' }, S.setId.slice(0, 8)), ` · מצב בתור: ${S.draft.queue_status}`),
    done ? h('div', { class: 'banner ok', 'data-testid': 'set-done' }, 'המקור הוגש בסט זה ואינו ניתן לעריכה.')
      : h('button', { class: 'btn primary', 'data-testid': 'set-complete', onclick: async () => {
        clearTimeout(S.saveTimer); while (S.inflight) await new Promise(r => setTimeout(r, 50));
        if (S.save !== 'saved') await save();
        try { await api(`/api/sets/${S.setId}/assignments/${S.src.id}/complete`, { method: 'POST', body: { expected_version: S.draft.version } }); S.draft.queue_status = 'completed'; toast('המקור הוגש בסט'); refresh(); } catch (e) { toast(e.message, true); }
      } }, 'סיים והגש מקור זה בסט'));
}
const WF_HE = { not_started: ['טרם התחיל', 'warn'], in_progress: ['בעבודה', 'warn'], needs_review: ['דורש בדיקה', 'bad'], ready_for_approval: ['מוכן לאישור', 'ok'], approved: ['מאושר', 'ok'] };
function statesPanel() {
  const st = S.states;
  if (!st) return h('div', { class: 'meta' }, 'טוען מצב…');
  const [wf, wfc] = WF_HE[st.workflow] ?? [st.workflow, 'warn'];
  const owner = st.catalog_owner.athlete_id ? `שויך ל־${athName(st.catalog_owner.athlete_id)}${st.catalog_owner.status === 'uncertain' ? ' (לא ודאי)' : ''}` : 'לא שויך לגולש';
  const u = st.segments.usability, d = st.segments.decision;
  const row = (k, v, testid) => h('li', { 'data-testid': testid }, h('span', { style: { flex: 1 } }, k), h('b', {}, v));
  return h('div', { 'data-testid': 'states-panel' },
    h('ul', { class: 'list' },
      row('מצב עבודה', h('span', { class: `pill ${wfc}`, 'data-testid': 'wf-state', 'data-state': st.workflow }, wf), 'st-wf'),
      row('בעל הסרטון בקטלוג', owner, 'st-owner'),
      row('טיוטה', S.save === 'saved' ? `נשמרה (v${S.draft.version}) — אינה אישור` : SAVE_UI[S.save][0], 'st-draft'),
      row('שימושיות (שימושי / חלקי / לא / לא בטוח)', h('span', { class: 'ltr' }, `${u.usable} / ${u.partially_usable} / ${u.unusable} / ${u.uncertain}`), 'st-usability'),
      row('החלטת דאטהסט (כלול / מוחרג / לא בטוח)', h('span', { class: 'ltr' }, `${d.include} / ${d.exclude} / ${d.uncertain}`), 'st-decision'),
      row('פריימי BOX שאומתו ידנית', String(st.box_qa.frames_verified), 'st-boxes'),
      row('כיסוי צפייה שסומן', `${Math.round(st.reviewed_coverage.ratio * 100)}% מהפריימים (לא אחוז השלמה)`, 'st-coverage'),
      row('Ground Truth מאושר', st.ground_truth.approved ? `v${st.ground_truth.latest_seq}${st.ground_truth.draft_matches_approved ? '' : ' · יש שינויים שלא אושרו'}` : 'לא אושר', 'st-gt'),
      row('בדאטהסט מוקפא', st.datasets.frozen_in.length ? st.datasets.frozen_in.map(x => x.name).join(', ') : 'לא', 'st-frozen'),
    ),
    h('label', { style: { display: 'flex', gap: '6px', marginTop: '6px' } },
      h('input', { type: 'checkbox', 'data-testid': 'request-review', checked: !!C().review_request?.requested, onchange: e => edit(c => { c.review_request = e.target.checked ? { requested: true, at: new Date().toISOString() } : { requested: false }; }) }),
      'סמן את הסרטון "דורש בדיקה" (גם ללא מקטעים)')
  );
}
const UNRES_HE = {
  uncertain_segments: 'מקטעים עם החלטת דאטהסט "לא בטוח"',
  unknown_athlete_included: 'מקטעים שנכללו ללא גולש מבצע',
  usability_undecided: 'מקטעים ששימושיותם טרם נקבעה',
  included_not_usable: 'מקטעים שנכללו אך סומנו לא שמישים',
  missing_reason_codes: 'מקטעים חלקיים/לא שמישים ללא סיבה',
  needs_review_flags: 'מקטעים שסומנו לבדיקה',
  boxes_needing_correction: 'מקטעים עם BOX שסומן כשגוי (חוסם אישור)',
  included_boxes_unverified: 'מקטעים שנכללו עם BOX שלא אומת במלואו (יירשם כהסתייגות)',
};
/** Key moments must lie inside their event (the server refuses the whole draft otherwise). Clicking again clears it. */
function setKeyMoment(s, key, label) {
  const cur = s.key_moments?.[key];
  if (cur === S.frame) { edit(c => { const x = c.segments.find(y => y.id === s.id); const km = { ...(x.key_moments || {}) }; delete km[key]; x.key_moments = km; }); return toast(`${label} הוסר`); }
  if (S.frame < s.start_frame || S.frame > s.end_frame) return toast(`הסמן (פריים ${S.frame}) מחוץ לאירוע שנבחר (${s.start_frame}–${s.end_frame}). הזז את הסמן לתוך האירוע ואז סמן ${label}.`, true);
  edit(c => { const x = c.segments.find(y => y.id === s.id); x.key_moments = { ...(x.key_moments || {}), [key]: S.frame }; });
  toast(`${label} סומן בפריים ${S.frame}`);
}
/**
 * Repairs a draft the server would refuse as a whole because of a value outside its event (e.g. a key moment left
 * behind after the event was moved/trimmed, or a box outside the event). Returns human-readable notes of what was removed.
 */
function repairOutOfRange(c) {
  const notes = [], segs = new Map(c.segments.map(x => [x.id, x]));
  for (const x of c.segments) {
    if (x.end_frame > S.total) { notes.push(`אירוע ${x.start_frame}–${x.end_frame} חרג מסוף הסרטון (${S.total}) וקוצר`); x.end_frame = S.total; }
    if (x.start_frame < 0) { notes.push('אירוע שהתחיל לפני תחילת הסרטון הוזז לפריים 0'); x.start_frame = 0; }
    if (!(x.end_frame > x.start_frame)) { notes.push(`אירוע באורך אפס בפריים ${x.start_frame} הורחב לפריים אחד`); if (x.start_frame >= S.total) x.start_frame = S.total - 1; x.end_frame = x.start_frame + 1; }
  }
  for (const x of c.segments) {
    const km = x.key_moments; if (!km || typeof km !== 'object') continue;
    for (const k of ['takeoff_frame', 'peak_frame', 'landing_frame']) {
      if (km[k] != null && (km[k] < x.start_frame || km[k] > x.end_frame)) { notes.push(`רגע מפתח בפריים ${km[k]} מחוץ לאירוע ${x.start_frame}–${x.end_frame}`); delete km[k]; }
    }
    if (Array.isArray(km.inflection_frames)) km.inflection_frames = km.inflection_frames.filter(f => f >= x.start_frame && f <= x.end_frame);
  }
  const before = c.keyframes.length;
  c.keyframes = c.keyframes.filter(k => { const x = segs.get(k.segment_id); return x && k.frame >= x.start_frame && k.frame < x.end_frame; });
  if (c.keyframes.length < before) notes.push(`${before - c.keyframes.length} תיבות מחוץ לטווח האירוע שלהן`);
  return notes;
}
function approvalForm() {
  let scope = 'source', reason = '', ack = false;
  const pv = S.states?.approval_preview;
  const st = S.states, open = st?.workflow_computed_reasons?.open ?? {}, blocking = st?.workflow_computed_reasons?.blocking ?? {};
  const openItems = Object.entries(open).filter(([, n]) => n), blockItems = Object.entries(blocking).filter(([, n]) => n);
  const btn = h('button', { class: 'btn primary', 'data-testid': 'approve', disabled: blockItems.length > 0, onclick: async () => {
    btn.disabled = true;
    try {
      clearTimeout(S.saveTimer); while (S.inflight) await new Promise(r => setTimeout(r, 50));
      if (S.save !== 'saved') await save();
      if (S.save !== 'saved') throw new Error('יש לשמור את הטיוטה לפני אישור');
      const r = await api(`/api/sources/${S.src.id}/approve`, { method: 'POST', body: { expected_version: S.draft.version, scope, reason, acknowledge_unresolved: ack, accept_by_exception: true } });
      // the approval recorded box decisions in the same transaction: take the server's draft (new version)
      if (r.draft_version != null && r.draft_version !== S.draft.version) { const sel = S.sel; S.draft = await api(S.draftUrl); clearPending(); setSave('saved'); S.sel = sel && seg(sel) ? sel : null; }
      toast(r.unchanged ? 'אין שינוי מאז הגרסה המאושרת' : `גרסה ${r.revision.seq} אושרה${r.accepted_by_exception ? ` · ${r.accepted_by_exception} תיבות BOX נרשמו כתקינות` : ''}${ack ? ' (עם הסתייגויות מתועדות)' : ''}`);
      S.revs = (await api(`/api/sources/${S.src.id}/revisions`)).items; paintStatus(); refreshStates(); refresh();
    } catch (e) { toast(e.message + (e.data?.code === 'UNRESOLVED_ITEMS' ? ' — סמן אישור מפורש של ההסתייגויות' : ''), true); btn.disabled = false; }
  } }, 'אשר גרסת Ground Truth');
  return h('div', { 'data-testid': 'approval-panel' },
    h('div', { class: 'meta' }, 'אישור יוצר גרסה בלתי ניתנת לשינוי של הטיוטה. "נשמר" אינו "מאושר".'),
    pv ? h('div', { class: 'meta', 'data-testid': 'approval-exception-boxes', 'data-to-verify': pv.to_verify, 'data-marked': pv.marked, 'data-not-checked': pv.not_checked },
      h('b', {}, 'מה האישור יעשה עם ה-BOX: '),
      `${pv.to_verify} יאומתו (לא סימנת אותן כשגויות, בחלק שצפית בו)`,
      pv.already_verified ? ` · ${pv.already_verified} כבר מאומתות` : '',
      ` · ${pv.marked} סומנו כשגויות/מוסתרות ולא יאומתו`,
      ` · ${pv.not_checked} לא נבדקו (מחוץ למה שצפית / בלי גולש) ולא יאומתו`,
      ` · ${pv.events_checked} מתוך ${pv.events} אירועים נצפו במלואם. תיבה שגויה: סמן ✕ או גרור אותה לפני האישור.`) : null,
    S.save !== 'saved' ? h('div', { class: 'meta', 'data-testid': 'approval-pending-save', style: { color: 'var(--unc)' } }, S.save === 'failed' ? 'השמירה האחרונה נכשלה — המצב כאן הוא של הגרסה השמורה בשרת.' : 'המצב כאן יתעדכן מיד אחרי השמירה האוטומטית.') : null,
    blockItems.length ? h('div', { class: 'banner bad', 'data-testid': 'approval-blocking' }, h('b', {}, 'חוסם אישור: '), blockItems.map(([k, n]) => `${UNRES_HE[k] ?? k}: ${n}`).join(' · ')) : null,
    openItems.length ? h('ul', { class: 'list', 'data-testid': 'unresolved' }, openItems.map(([k, n]) => h('li', {}, h('span', { style: { flex: 1 } }, UNRES_HE[k] ?? k), h('b', {}, n)))) : h('div', { class: 'meta', 'data-testid': 'unresolved' }, 'אין פריטים פתוחים'),
    (st?.box_qa?.per_segment ?? []).some(q => q.box_frames && q.status !== 'verified_in_checked_range') ? h('div', { class: 'meta' }, UNRES_HE.included_boxes_unverified) : null,
    h('div', { class: 'cols2' }, field('היקף אישור', h('select', { id: 'ap-scope', onchange: e => { scope = e.target.value; } }, [['source', 'כל הסרטון (מסמך מלא)'], ['interval', 'טווח (נרשם כהערה — הגרסה כוללת את כל המסמך)'], ['segment', 'מקטע (נרשם כהערה — הגרסה כוללת את כל המסמך)']].map(([k, l]) => h('option', { value: k }, l))), 'ap-scope'), field('סיבה / הערה', h('input', { type: 'text', id: 'ap-reason', oninput: e => { reason = e.target.value; } }), 'ap-reason')),
    openItems.length ? h('label', { style: { display: 'flex', gap: '6px', margin: '8px 0', color: 'var(--unc)' } }, h('input', { type: 'checkbox', 'data-testid': 'ack', onchange: e => { ack = e.target.checked; } }), `אני מאשר במפורש לאשר עם ${openItems.reduce((a, [, n]) => a + n, 0)} פריטים פתוחים — הם יירשמו כהסתייגויות ולא כאימות`) : null,
    btn);
}

// ---------------- chrome / refresh ----------------
function paintHud() { const a = $('#hudfr'), b = $('#hudtool'); if (a) a.textContent = `f${S.frame}`; if (b) b.textContent = S.tool === 'box' ? 'כלי תיבה פעיל (B)' : ''; if (b) b.style.display = S.tool === 'box' ? '' : 'none'; }
function paintStatus() {
  const rev = S.revs[0];
  const ownerLabel = S.src.owner_athlete_label ? `גולש: ${S.src.owner_athlete_label}` : 'ללא שיוך לגולש';
  const ownerCls = S.src.owner_status === 'needs_review' ? 'warn' : S.src.owner_athlete_id ? 'ok' : '';

  setTopbar(
    S.setId === 'primary' ? h('a', { class: 'btn sm', href: `#/catalog/${S.src.id}`, 'data-testid': 'back-to-catalog', onclick: async e => {
      e.preventDefault();
      clearTimeout(S.saveTimer); commitWatched(); while (S.inflight) await new Promise(r => setTimeout(r, 50));
      if (S.save !== 'saved') await save();
      if (S.save !== 'saved') return toast('השינויים לא נשמרו עדיין — פתור את הודעת השמירה לפני החזרה לקטלוג', true);
      location.hash = `#/catalog/${S.src.id}`;
    } }, '→ חזרה לקטלוג') : null,
    h('strong', {}, 'סימון'),
    h('span', { class: 'ltr mono', title: S.src.sha256, 'data-testid': 'srcname' }, S.src.display_name),
    pill(ownerLabel, ownerCls),
    S.src.provider === 'cloud-r2' ? null : S.src.ingest_state === 'ready' ? pill('ארכיון מאומת', 'ok') : pill('ארכיון לא מאומת', 'bad'),
    pill(rev ? `גרסה מאושרת v${rev.seq}` : 'אין גרסה מאושרת', rev ? 'ok' : ''),
    sportPicker(),
    ...cloudPills(),
    h('span', { class: 'spacer' }),
    h('span', { id: 'savepill', 'data-testid': 'savepill', 'aria-live': 'polite' }),
    h('button', { id: 'savebtn', 'data-testid': 'save-now', title: 'שמור עכשיו (Ctrl+S). השמירה גם אוטומטית.', onclick: saveNow })
  );
  paintSave($('#savepill'));
}

function refresh() {
  if (!S) return;
  paintStatus(); paintControls(); paintTimeline(); paintOverlay(); paintInspector(); paintHud();
}

// ---------------- keyboard ----------------
function helpDialog() {
  const rows = [
    ['Space', 'ניגון / השהיה'],
    ['← / →', 'פריים אחורה / קדימה'],
    ['Shift + ← / →', '10 פריימים'],
    ['I / O', 'תחילת / סוף מקטע (יוצר מקטע)'],
    ['[ / ]', 'מקטע קודם / הבא'],
    ['1–9', 'שיוך גולש למקטע'],
    ['E / X / U', 'כלול / החרג / לא בטוח'],
    ['B', 'כלי ציור תיבה'],
    ['N', 'הפריט הלא פתור הבא'],
    ['Q / W', 'האט / האץ'],
    ['+ / −', 'זום ציר זמן'],
    ['Del', 'מחק מקטע'],
    ['Ctrl + Z / Y', 'בטל / חזור'],
    ['Ctrl + S', 'שמירה מיידית'],
    ['?', 'עזרה']
  ];
  dialog('קיצורי מקלדת', h('div', { class: 'keys' }, rows.flatMap(([k, d]) => [h('kbd', { dir: 'ltr' }, k), d])), [h('button', { class: 'btn', onclick: closeDialog }, 'סגור')]);
}

function bindKeys() {
  on(window, 'keydown', e => {
    if (!S || $('#dlg').open) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); saveNow(); return; }
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
      e: () => s && edit(c => { c.segments.find(x => x.id === s.id).decision = 'include'; }),
      x: () => s && edit(c => { c.segments.find(x => x.id === s.id).decision = 'exclude'; }),
      u: () => s && edit(c => { c.segments.find(x => x.id === s.id).decision = 'uncertain'; }),
      q: () => setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(S.speed) - 1)]),
      w: () => setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(S.speed) + 1)]),
      '+': () => zoom(1.4), '=': () => zoom(1.4), '-': () => zoom(0.7), '?': helpDialog, Delete: deleteSel, Backspace: deleteSel,
      Escape: () => { if (S.mark.in != null) { S.mark = { in: null, out: null }; paintMarks(); paintControls(); paintMarkLive(); return; } S.tool = 'select'; S.sel = null; refresh(); },
    };
    if (/^[1-9]$/.test(k) && s) { const a = S.athletes[+k - 1]; if (a) { e.preventDefault(); setSegmentAthlete(s.id, a.id); } return; }
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
  if (S.save !== 'saved' || S.inflight) {                     // background saves (tracking) are normal: wait for them
    clearTimeout(S.saveTimer); for (let i = 0; i < 100 && S.inflight; i++) await new Promise(r => setTimeout(r, 50));
    if (S.save !== 'saved') await save();
    if (S.save !== 'saved') { toast('השמירה נכשלה - פתור את הודעת השמירה ואז בחר ענף שוב', true); return refresh(); }
  }
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

// ---------------- cloud sources (used in place from R2, read-only) ----------------
function cloudPills() {
  if (S.src.provider !== 'cloud-r2') return [];
  const v = S.src.verify_state;
  return [pill('☁ ענן (קריאה בלבד)', ''),
    v === 'verified' ? pill('זהות אומתה', 'ok') : v === 'mismatch' ? pill('אי-התאמת SHA-256!', 'bad')
      : h('button', { class: 'btn sm', 'data-testid': 'verify-cloud', title: 'נדרש לפני אישור Ground Truth', onclick: async e => {
        e.target.disabled = true;
        try { const j = await awaitJob(await api('/api/cloud/verify', { method: 'POST', body: { source_id: S.src.id } })); toast(j.state === 'done' && j.report.verified ? 'הזהות אומתה' : 'האימות נכשל', !(j.state === 'done' && j.report.verified)); const root = S.root, id = S.src.id; teardownAnnotate(); await renderAnnotate(root, id); }
        catch (x) { toast(x.message, true); e.target.disabled = false; }
      } }, 'אמת זהות (SHA-256)'),
    S.src.proxy_state === 'building' ? pill('מכין עותק תיוג מדויק…', 'warn') : S.src.proxy_state === 'failed' ? pill('בניית עותק התיוג נכשלה — מנגן את המקור', 'bad') : null].filter(Boolean);
}

function watchCloudProxy() {
  if (S.src.provider !== 'cloud-r2' || S.src.proxy_state !== 'building') return;
  if (S.src.codec && S.src.codec !== 'h264') toast('הסרטון בפורמט (' + S.src.codec + ') שאולי לא מתנגן בדפדפן עד שעותק התיוג יהיה מוכן', false);
  const id = S.src.id, root = S.root;
  const t = setInterval(async () => {
    try {
      const cur = await api(`/api/sources/${id}`);
      if (cur.proxy_state === 'building') return;
      clearInterval(t);
      if (S && S.src.id === id) { teardownAnnotate(); await renderAnnotate(root, id); toast(cur.proxy_state === 'ready' ? 'עותק התיוג מוכן' : 'בניית עותק התיוג נכשלה', cur.proxy_state !== 'ready'); }
    } catch { /* transient */ }
  }, 4000);
  cleanup.push(() => clearInterval(t));
}
