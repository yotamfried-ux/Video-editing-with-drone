import { h, api, ltr, pill, toast, fmtBytes, timecode, fpsOf, STATUS_HE, STATUS_CLASS } from './ui.js';
import { setTopbar } from './main.js';

export async function renderLibrary(root) {
  setTopbar(h('strong', {}, 'ספרייה'), h('span', { class: 'pill' }, 'סרטוני מקור'));
  const [batches, first] = await Promise.all([api('/api/batches'), api('/api/sources?limit=200')]);
  const f = { q: '', status: '', batch: '', view: 'grid' };
  const out = h('div'); const stats = h('div', { class: 'stats' });
  let items = first.items;

  const render = () => {
    const list = items.filter(s => (!f.q || s.display_name.toLowerCase().includes(f.q.toLowerCase()) || s.sha256.startsWith(f.q)) && (!f.status || s.annotation_status === f.status || s.ingest_state === f.status) && (!f.batch || s.batches.includes(f.batch)));
    stats.replaceChildren(...[['סה״כ', first.totals.all], ['מאושרים', first.totals.approved], ['ללא סימון', first.totals.not_annotated], ['שגיאות ארכיון', items.filter(s => s.ingest_state !== 'ready').length]].map(([l, n]) => h('div', { class: 'stat' }, h('b', {}, n), h('span', {}, l))));
    if (!list.length) return out.replaceChildren(h('div', { class: 'empty' }, items.length ? 'אין תוצאות לסינון' : 'עדיין אין סרטונים. הרץ סנכרון קליטה.'));
    out.replaceChildren(f.view === 'grid'
      ? h('div', { class: 'grid' }, list.map(card))
      : h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['קובץ', 'משך', 'סטטוס', 'ארכיון', 'התקדמות', 'אצווה', ''].map(x => h('th', {}, x)))),
        h('tbody', {}, list.map(s => h('tr', {}, h('td', {}, ltr(s.display_name)), h('td', {}, ltr(timecode(s.frame_count, fpsOf(s)))), h('td', {}, pill(STATUS_HE[s.annotation_status], STATUS_CLASS[s.annotation_status])), h('td', {}, archBadge(s)), h('td', {}, `${Math.round(s.reviewed_ratio * 100)}%`), h('td', {}, s.batches.join(', ')), h('td', {}, h('a', { class: 'btn sm', href: `#/annotate/${s.id}` }, 'פתח')))))));
  };
  const archBadge = s => s.ingest_state === 'ready' ? pill('ארכיון מאומת', 'ok') : pill(STATUS_HE[s.ingest_state], STATUS_CLASS[s.ingest_state]);
  const card = s => h('div', { class: 'card', 'data-testid': 'source-card' },
    h('div', { class: 'thumb', style: s.has_thumb ? { backgroundImage: `url(/media/${s.id}/thumb)` } : {} }, s.has_thumb ? null : 'אין תמונה ממוזערת', h('span', { class: 'tag' }, pill(STATUS_HE[s.annotation_status], STATUS_CLASS[s.annotation_status]))),
    h('div', { class: 'body' }, h('div', { class: 'name', title: s.display_name }, s.display_name),
      h('div', { class: 'meta' }, ltr(`${s.width}×${s.height}`), ltr(`${(fpsOf(s)).toFixed(2)}fps`), ltr(timecode(s.frame_count, fpsOf(s))), ltr(fmtBytes(s.byte_size))),
      h('div', { class: 'meta' }, archBadge(s), s.revision_seq ? pill(`גרסה ${s.revision_seq}`) : null),
      h('div', { class: 'bar', title: 'נבדק' }, h('i', { style: { width: `${Math.round(s.reviewed_ratio * 100)}%` } })),
      h('div', { class: 'meta' }, `${s.segment_count} מקטעים · נבדק ${Math.round(s.reviewed_ratio * 100)}%`),
      h('a', { class: 'btn primary', href: `#/annotate/${s.id}`, 'aria-label': `${s.annotation_status === 'not_annotated' ? 'התחל' : 'המשך'} סימון ${s.display_name}` }, s.annotation_status === 'not_annotated' ? 'התחל סימון' : 'המשך סימון')));

  const sel = (opts, key) => { const el = h('select', { 'aria-label': key, onchange: e => { f[key] = e.target.value; render(); } }, opts.map(([v, l]) => h('option', { value: v }, l))); return el; };
  const next = items.find(s => s.annotation_status === 'not_annotated' && s.ingest_state === 'ready');
  root.append(h('div', { class: 'page' }, h('h1', {}, 'ספריית סרטוני מקור'), h('div', { class: 'sub' }, 'זהות הסרטון קבועה (SHA-256), בלתי תלויה בנתיב או בשם הקובץ.'),
    stats,
    h('div', { class: 'toolbar' },
      h('input', { type: 'search', placeholder: 'חיפוש שם / hash', 'aria-label': 'חיפוש', oninput: e => { f.q = e.target.value; render(); } }),
      sel([['', 'כל הסטטוסים'], ['not_annotated', 'לא סומן'], ['in_progress', 'בעבודה'], ['needs_review', 'דורש בדיקה'], ['approved', 'מאושר'], ['archive_error', 'שגיאת ארכיון']], 'status'),
      sel([['', 'כל האצוות'], ...batches.items.map(b => [b.label, `${b.label} (${b.sources})`])], 'batch'),
      h('button', { class: 'btn', 'aria-pressed': 'true', onclick: e => { f.view = f.view === 'grid' ? 'table' : 'grid'; e.target.textContent = f.view === 'grid' ? 'תצוגת טבלה' : 'תצוגת כרטיסים'; render(); } }, 'תצוגת טבלה'),
      h('span', { class: 'spacer' }),
      next ? h('a', { class: 'btn primary', href: `#/annotate/${next.id}`, 'data-testid': 'next-unannotated' }, 'הסרטון הבא ללא סימון ←') : null,
      h('button', { class: 'btn', onclick: async e => { e.target.disabled = true; try { const j = await api('/api/ingestion/reconcile', { method: 'POST', body: {} }); let s; do { await new Promise(r => setTimeout(r, 300)); s = await api(`/api/jobs/${j.job_id}`); } while (s.state === 'running'); toast(s.state === 'done' ? `סנכרון הושלם: ${s.report.ingested} חדשים, ${s.report.duplicates} כפולים, ${s.report.errors.length} שגיאות` : `נכשל: ${s.error}`, s.state !== 'done'); } catch (x) { toast(x.message, true); } e.target.disabled = false; } }, 'סנכרון קליטה'),
      h('button', { class: 'btn', onclick: async e => { e.target.disabled = true; try { const r = await api('/api/archive/verify', { method: 'POST', body: {} }); toast(`אימות ארכיון: ${r.ok}/${r.checked} תקינים`, r.failed.length > 0); } catch (x) { toast(x.message, true); } e.target.disabled = false; } }, 'אמת ארכיון')),
    out));
  render();
}
