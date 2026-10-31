// Tiny DOM + formatting helpers shared by all views.
export const $ = (s, r = document) => r.querySelector(s);
export function h(tag, attrs = {}, ...kids) {
  const el = tag === 'svg' ? document.createElementNS('http://www.w3.org/2000/svg', 'svg') : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
export const ltr = (t, cls = '') => h('bdi', { class: `ltr mono ${cls}`, dir: 'ltr' }, t);
export const fpsOf = s => s.fps_num / s.fps_den;
/** mm:ss:ff — the frame field uses the nominal (rounded) rate. */
export function timecode(frame, fps) {
  const n = Math.round(fps), s = Math.floor(frame / n), f = frame - s * n;
  const p = (x, w = 2) => String(x).padStart(w, '0');
  return `${p(Math.floor(s / 60))}:${p(s % 60)}:${p(f)}`;
}
export const fmtBytes = b => b > 1e9 ? (b / 1e9).toFixed(2) + ' GB' : b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : (b / 1e3).toFixed(0) + ' KB';
export const fmtDate = s => s ? new Date(s).toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' }) : '—';

export async function api(path, opts = {}) {
  const res = await fetch(path, { method: opts.method ?? 'GET', headers: opts.body ? { 'content-type': 'application/json' } : {}, body: opts.body ? JSON.stringify(opts.body) : undefined, credentials: 'same-origin' });
  const ct = res.headers.get('content-type') ?? '';
  const data = ct.includes('json') ? await res.json() : await res.text();
  if (!res.ok) throw Object.assign(new Error(data.message ?? 'שגיאה'), { code: data.code, status: res.status, data });
  return data;
}
export function toast(msg, bad = false) {
  const t = h('div', { class: `toast${bad ? ' bad' : ''}`, role: bad ? 'alert' : 'status' }, msg);
  $('#toasts').append(t); setTimeout(() => t.remove(), bad ? 6000 : 3000);
}
export function dialog(title, body, actions = []) {
  const d = $('#dlg'); d.replaceChildren(h('h2', {}, title), body, h('div', { style: { display: 'flex', gap: '8px', marginTop: '14px', justifyContent: 'flex-start' } }, actions));
  d.showModal(); return d;
}
export const closeDialog = () => $('#dlg').close();
export const STATUS_HE = { not_annotated: 'לא סומן', in_progress: 'בעבודה', needs_review: 'דורש בדיקה', approved: 'מאושר',
  ready: 'מוכן', pending_archive: 'ממתין לארכיון', archive_error: 'שגיאת ארכיון', unavailable: 'לא זמין' };
export const STATUS_CLASS = { approved: 'ok', ready: 'ok', in_progress: 'busy', needs_review: 'warn', not_annotated: '', pending_archive: 'warn', archive_error: 'bad', unavailable: 'bad' };
export const pill = (text, cls = '') => h('span', { class: `pill ${cls}` }, h('span', { class: 'dot' }), text);
// Sport registry (served by /api/sports). Labels come from the registry, never from hard-coded enums.
let SPORTS = [];
export async function loadSports() { SPORTS = (await api('/api/sports')).items; return SPORTS; }
export const sportsList = () => SPORTS;
export const sportName = id => id == null ? 'לא מסווג' : (SPORTS.find(s => s.id === id)?.name_he ?? id);
/** Event types a picker may offer for a sport (retired ones only when already in use). Unclassified sources get the legacy keys only. */
export function eventOptions(sportId, current) {
  const base = sportId == null ? Object.entries(EVENT_HE).map(([key, label_he]) => ({ key, label_he, required_attrs: [] }))
    : (SPORTS.find(s => s.id === sportId)?.event_types ?? []).filter(e => e.enabled || e.key === current);
  return base;
}
export function eventHe(key, sportId) {
  const t = sportId != null && SPORTS.find(s => s.id === sportId)?.event_types.find(e => e.key === key);
  return t?.label_he ?? EVENT_HE[key] ?? key;
}
export const eventInfo = (sportId, key) => sportId != null ? SPORTS.find(s => s.id === sportId)?.event_types.find(e => e.key === key) ?? null : null;
export const EVENT_HE = { wave_ride: 'רכיבה על גל', failed_takeoff: 'עמידה כושלת', wipeout: 'נפילה', paddle_out: 'חתירה החוצה', other: 'אחר' };
export const DECISION_HE = { include: 'כלול', exclude: 'החרג', uncertain: 'לא בטוח' };
export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now());

/** External-backup status: Local First only works if the independent copy really exists and is fresh. */
export async function backupStatus() { try { return await api('/api/backup/status'); } catch { return null; } }
export function backupBanner(b) {
  if (!b || b.state === 'ok') return null;
  const msg = b.state === 'never'
    ? 'לא בוצע גיבוי חיצוני. סרטונים וגיבוי שלהם על אותו דיסק אינם גיבוי.'
    : `הגיבוי החיצוני האחרון בוצע לפני ${Math.floor(b.age_days)} ימים (הסף: ${b.stale_after_days}).`;
  return h('div', { class: 'banner bad', role: 'alert', 'data-testid': 'backup-banner' }, msg, ' ', h('code', { class: 'ltr' }, 'node scripts/gt-offsite-backup.mjs run --to <דיסק אחר>'));
}
export function backupPill(b) {
  if (!b) return null;
  return b.state === 'ok' ? pill(`גיבוי חיצוני: לפני ${Math.floor(b.age_days)} ימים`, 'ok') : pill(b.state === 'never' ? 'אין גיבוי חיצוני' : 'גיבוי חיצוני ישן', 'bad');
}
