// Tiny DOM + formatting helpers shared by all views.
export const $ = (s, r = document) => r.querySelector(s);
export function h(tag, attrs = {}, ...kids) {
  const el = tag === 'svg' ? document.createElementNS('http://www.w3.org/2000/svg', 'svg') : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') el.innerHTML = v;
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
export const EVENT_HE = { wave_ride: 'רכיבה על גל', failed_takeoff: 'עמידה כושלת', wipeout: 'נפילה', paddle_out: 'חתירה החוצה', other: 'אחר' };
export const DECISION_HE = { include: 'כלול', exclude: 'החרג', uncertain: 'לא בטוח' };
export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now());
