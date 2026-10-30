import { h, api, ltr, pill, toast, fmtDate, EVENT_HE, STATUS_HE, STATUS_CLASS, dialog, closeDialog } from './ui.js';
import { setTopbar } from './main.js';

// ---------------- Athletes ----------------
export async function renderAthletes(root) {
  setTopbar(h('strong', {}, 'ניהול גולשים'), pill('זהות פסבדונימית — ללא זיהוי פנים'));
  const draw = async () => {
    const { items } = await api('/api/athletes');
    root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'גולשים'), h('div', { class: 'sub' }, 'כל גולש הוא מזהה קבוע (UUID). קישור בין סרטונים נעשה רק באישור ידני של המפעיל. תיקון זהות מתבצע בגרסה מאושרת חדשה — גרסאות קיימות אינן משתנות.'),
      h('div', { class: 'toolbar' }, h('input', { type: 'text', id: 'newath', placeholder: 'תווית לגולש חדש', style: { maxWidth: '260px' }, 'aria-label': 'תווית גולש חדש' }),
        h('button', { class: 'btn primary', 'data-testid': 'add-athlete', onclick: async () => { const v = root.querySelector('#newath').value; try { await api('/api/athletes', { method: 'POST', body: { label: v } }); await draw(); } catch (e) { toast(e.message, true); } } }, 'הוסף גולש')),
      items.length ? h('div', { class: 'grid' }, items.map(a => h('div', { class: 'card', 'data-testid': 'athlete-card' }, h('div', { class: 'body' },
        h('div', { style: { display: 'flex', gap: '6px' } }, h('input', { type: 'text', value: a.label, 'aria-label': 'תווית', onchange: async e => { try { await api(`/api/athletes/${a.id}`, { method: 'PATCH', body: { label: e.target.value } }); toast('עודכן'); } catch (x) { toast(x.message, true); } } })),
        h('div', { class: 'meta' }, ltr(a.id.slice(0, 8)), ` · ${a.appearances.length} הופעות`),
        h('ul', { class: 'list' }, a.appearances.length ? a.appearances.map(ap => h('li', {}, h('a', { href: `#/annotate/${ap.source_id}`, class: 'ltr mono', style: { flex: 1, color: 'var(--accent)' } }, ap.display_name),
          h('label', { class: 'meta', title: 'הופעה לא וודאית' }, h('input', { type: 'checkbox', checked: !!ap.uncertain, onchange: e => api(`/api/athletes/${a.id}/appearances/${ap.source_id}`, { method: 'PATCH', body: { uncertain: e.target.checked ? 1 : 0 } }).catch(x => toast(x.message, true)) }), ' לא בטוח'),
          h('label', { class: 'meta', title: 'זהות אושרה ידנית' }, h('input', { type: 'checkbox', checked: !!ap.confirmed, onchange: e => api(`/api/athletes/${a.id}/appearances/${ap.source_id}`, { method: 'PATCH', body: { confirmed: e.target.checked ? 1 : 0 } }).catch(x => toast(x.message, true)) }), ' אושר'))) : [h('li', {}, 'אין הופעות עדיין')]))))) : h('div', { class: 'empty' }, 'אין גולשים עדיין')));
  };
  await draw();
}

// ---------------- Datasets ----------------
export async function renderDatasets(root) {
  setTopbar(h('strong', {}, 'ניהול דאטהסטים'), pill('גרסאות קפואות'));
  const [ds, src] = await Promise.all([api('/api/datasets'), api('/api/sources?limit=200&status=approved')]);
  const checks = new Map();
  root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'דאטהסטים'), h('div', { class: 'sub' }, 'קפיאה נועלת (sha256 + גרסה מאושרת) לכל סרטון. פיצול לפי סשן הקלטה; קבוצת המבחן קבועה ולא ניתנת להזזה.'),
    h('h2', { style: { fontSize: '15px' } }, 'קפיאת דאטהסט חדש'),
    src.items.length ? h('div', {}, h('div', { class: 'toolbar' }, h('input', { type: 'text', id: 'dsname', placeholder: 'שם הדאטהסט', style: { maxWidth: '240px' }, 'aria-label': 'שם דאטהסט' }),
      h('button', { class: 'btn primary', 'data-testid': 'freeze', onclick: async () => { const ids = [...checks].filter(([, c]) => c.checked).map(([id]) => id); try { await api('/api/datasets', { method: 'POST', body: { name: root.querySelector('#dsname').value, source_ids: ids } }); toast('הדאטהסט נקפא'); renderDatasets(root); } catch (e) { toast(e.message, true); } } }, 'קפא דאטהסט')),
      h('ul', { class: 'list' }, src.items.map(s => { const c = h('input', { type: 'checkbox', 'aria-label': s.display_name }); checks.set(s.id, c); return h('li', {}, c, ltr(s.display_name), pill(`v${s.revision_seq}`, 'ok')); }))) : h('div', { class: 'empty' }, 'אין סרטונים עם גרסה מאושרת לקפיאה'),
    h('h2', { style: { fontSize: '15px', marginTop: '24px' } }, 'גרסאות קיימות'),
    ds.items.length ? h('table', { class: 't', 'data-testid': 'ds-table' }, h('thead', {}, h('tr', {}, ['שם', 'נוצר', 'train', 'validation', 'test', 'digest', 'ייצוא'].map(x => h('th', {}, x)))), h('tbody', {}, ds.items.map(d => h('tr', {}, h('td', {}, d.name), h('td', {}, fmtDate(d.created_at)), h('td', {}, d.counts.train), h('td', {}, d.counts.validation), h('td', {}, d.counts.test), h('td', {}, ltr(d.digest.slice(0, 12))), h('td', {}, h('a', { class: 'btn sm', href: `/api/datasets/${d.id}/export.jsonl`, download: `${d.name}.jsonl` }, 'JSONL'))))))
      : h('div', { class: 'empty' }, 'אין דאטהסטים קפואים')));
}

// ---------------- Evaluations ----------------
const pct = v => v == null ? '—' : `${(v * 100).toFixed(1)}%`;
export async function renderEvaluations(root, id) {
  setTopbar(h('strong', {}, 'הערכת AI'), pill('הערכה עיוורת · דטרמיניסטית'));
  if (id) return renderEvalDetail(root, id);
  const [ev, ds, pr] = await Promise.all([api('/api/evaluations'), api('/api/datasets'), api('/api/predictions')]);
  let dsel, psel;
  root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'אמת מידה מול תחזיות הפייפליין'), h('div', { class: 'sub' }, 'הפייפליין לא רואה תוויות. ההערכה מושווה לגרסה הקפואה בלבד; אזורים לא נבדקים ופריטים לא בטוחים אינם נספרים כשגיאה.'),
    h('div', { class: 'toolbar' },
      dsel = h('select', { 'aria-label': 'דאטהסט' }, ds.items.map(d => h('option', { value: d.id }, d.name))),
      psel = h('select', { 'aria-label': 'תחזיות' }, pr.items.map(p => h('option', { value: p.id }, `${p.pipeline_version} · ${p.run_id}`))),
      h('button', { class: 'btn primary', 'data-testid': 'run-eval', disabled: !ds.items.length || !pr.items.length, onclick: async () => { try { const r = await api('/api/evaluations', { method: 'POST', body: { dataset_id: dsel.value, prediction_id: psel.value } }); location.hash = `#/evaluations/${r.id}`; } catch (e) { toast(e.message, true); } } }, 'הרץ הערכה'),
      h('button', { class: 'btn', onclick: importPredictions }, 'ייבוא תחזיות (JSON)')),
    h('h2', { style: { fontSize: '15px' } }, 'היסטוריה בין גרסאות פייפליין'),
    ev.items.length ? h('table', { class: 't', 'data-testid': 'eval-table' }, h('thead', {}, h('tr', {}, ['גרסת פייפליין', 'ריצה', 'דאטהסט', 'recall', 'precision', 'זהות', 'חסרים', 'כפולים', 'גולש שגוי', 'digest', ''].map(x => h('th', {}, x)))),
      h('tbody', {}, ev.items.map(e => h('tr', {}, h('td', {}, ltr(e.pipeline_version)), h('td', {}, ltr(e.run_id)), h('td', {}, e.dataset_name), h('td', {}, pct(e.metrics.event_recall)), h('td', {}, pct(e.metrics.event_precision)), h('td', {}, pct(e.metrics.identity_accuracy)), h('td', {}, e.totals.missed), h('td', {}, e.totals.duplicates), h('td', {}, e.totals.attributable - e.totals.correct_attribution), h('td', {}, ltr(e.digest.slice(0, 10))), h('td', {}, h('a', { class: 'btn sm', href: `#/evaluations/${e.id}` }, 'פירוט')))))) : h('div', { class: 'empty' }, 'עדיין אין הערכות')));
}
function importPredictions() {
  const ta = h('textarea', { id: 'predjson', style: { minHeight: '200px', direction: 'ltr' }, placeholder: '{"run_id":"…","pipeline_version":"…","sources":[{"source_sha256":"…","events":[{"start_frame":0,"end_frame":90,"athlete_key":"T1"}]}]}' });
  dialog('ייבוא תחזיות פייפליין', h('div', {}, h('label', { class: 'f', for: 'predjson' }, 'JSON (קריאה בלבד — מפלט הפייפליין)'), ta), [
    h('button', { class: 'btn primary', onclick: async () => { try { await api('/api/predictions', { method: 'POST', body: JSON.parse(ta.value) }); closeDialog(); toast('יובא'); location.reload(); } catch (e) { toast(e.message, true); } } }, 'ייבא'), h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')]);
}
const ERR_HE = { missed_event: 'אירוע שהוחמץ', false_positive: 'תוצאה שגויה (FP)', duplicate: 'פלט כפול', wrong_athlete: 'גולש שגוי', predicted_excluded: 'חזה אירוע מוחרג' };
async function renderEvalDetail(root, id) {
  const { report: r, digest } = await api(`/api/evaluations/${id}`);
  const m = r.metrics, t = r.totals;
  root.replaceChildren(h('div', { class: 'page' }, h('a', { href: '#/evaluations', class: 'btn sm' }, '→ חזרה'),
    h('h1', { style: { marginTop: '10px' } }, 'דוח הערכה'), h('div', { class: 'sub' }, ltr(`${r.pipeline_version} · ${r.run_id}`), ' · ', ltr(`evaluator ${r.evaluator_version}`), ' · digest ', ltr(digest.slice(0, 12))),
    h('div', { class: 'stats' }, [['Recall', pct(m.event_recall)], ['Precision', pct(m.event_precision)], ['דיוק זהות', pct(m.identity_accuracy)], ['חסרים', t.missed], ['כפולים', t.duplicates], ['FP', t.false_positives], ['לא נבדק', t.unreviewed_predictions], ['שגיאת התחלה ממוצעת (פריימים)', m.mean_abs_start_error_frames == null ? '—' : m.mean_abs_start_error_frames.toFixed(1)]].map(([l, v]) => h('div', { class: 'stat' }, h('b', {}, v), h('span', {}, l)))),
    h('div', { class: 'legend' }, `IoU ≥ ${r.params.iou_threshold} · פיצולים: ${r.params.splits.join(', ')} · שיוך גולשים לפי מיפוי התאמות דטרמיניסטי`),
    r.per_source.map(p => h('div', { style: { marginBottom: '18px' } }, h('h3', { style: { fontSize: '14px' } }, ltr(p.sha256.slice(0, 12)), ' · ', p.split, p.has_prediction ? '' : ' · אין תחזית למקור זה'),
      p.errors.length ? h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['סוג', 'פריימים', 'מקטע/תחזית'].map(x => h('th', {}, x)))), h('tbody', {}, p.errors.map(e => h('tr', {}, h('td', {}, pill(ERR_HE[e.type] ?? e.type, e.type === 'missed_event' || e.type === 'wrong_athlete' ? 'bad' : 'warn')), h('td', {}, ltr(`${e.start_frame}–${e.end_frame}`)), h('td', {}, ltr(e.segment_id ?? `pred#${e.pred_index}`)))))) : h('div', { class: 'banner warn', style: { color: 'var(--inc)' } }, 'אין שגיאות לסרטון זה')))));
}
