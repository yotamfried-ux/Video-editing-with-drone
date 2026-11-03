// Quick catalog ("קטלוג מהיר"): one video at a time, three short questions, then a checklist of every remaining field.
// Nothing here is a second copy of the data: owner, sport and the draft are read and written through the same APIs the
// library and the workbench use, so no catalogued detail can be lost or diverge. Details of each event (performer,
// usability, decision, reasons, key moments, BOX) are edited in the workbench, opened directly at the right event/tab.
import { h, api, toast, pill, sportsList, sportName, eventHe } from './ui.js';
import { setTopbar } from './main.js';

const VIDEO_HE = { owner: 'של מי הסרטון', sport: 'ענף', triage: 'יש אירועים?', watched: 'צפייה בכל הסרטון', opened: 'פתיחה בסטודיו' };
const EVENT_HE = { event_type: 'סוג', performer: 'מי ביצע', usability: 'שימושיות', decision: 'החלטה', reasons: 'סיבה', key_moments: 'רגעי מפתח', box: 'BOX על הגולש' };
const BOX_HE = { none: 'אין BOX (רשות)', not_checked: 'BOX לא נבדק', partially_checked: 'BOX נבדק חלקית', needs_correction: 'BOX דורש תיקון', cannot_determine: 'BOX — לא ניתן לקבוע', verified_in_checked_range: 'BOX נבדק' };
const TRIAGE_HE = { not_started: 'לא נענה', has_events: 'יש אירועים', no_events: 'אין אירועים', unsure: 'לא בטוח — לבדיקה' };
const FILTERS = [['todo', 'לטיפול'], ['done', 'הושלמו'], ['all', 'הכל']];

/** Opens the workbench at one event and inspector tab, with a way back to this queue. */
export function openInWorkbench(sourceId, segId = null, tab = 'event') {
  try { sessionStorage.setItem('studio.focus', JSON.stringify({ source: sourceId, seg: segId, tab })); sessionStorage.setItem('studio.fromCatalog', sourceId); } catch {}
  location.hash = `#/annotate/${sourceId}`;
}

export async function renderCatalog(root, selId) {
  let q = await api('/api/catalog/queue');
  let athletes = (await api('/api/athletes')).items;
  let filter = 'todo';
  let sel = selId ? q.items.find(i => i.source_id === selId || i.cloud_object_id === selId) : null;
  const keyOf = i => i.source_id ?? `c:${i.cloud_object_id}`;
  const visible = () => q.items.filter(i => filter === 'all' || (filter === 'done' ? i.complete : !i.complete));
  if (!sel) sel = visible()[0] ?? q.items[0] ?? null;

  async function reload(keepKey) {
    q = await api('/api/catalog/queue');
    sel = q.items.find(i => keyOf(i) === keepKey) ?? sel;
    render();
  }
  function next() {
    const list = q.items.filter(i => !i.complete);
    const idx = list.findIndex(i => keyOf(i) === keyOf(sel));
    const n = list[idx + 1] ?? list.find(i => keyOf(i) !== keyOf(sel));
    if (!n) return toast('כל הסרטונים בתור הושלמו');
    sel = n; render();
  }

  function render() {
    const pct = q.totals.all ? Math.round((q.totals.complete / q.totals.all) * 100) : 0;
    setTopbar(h('strong', {}, 'קטלוג מהיר'), h('span', { class: 'meta' }, `${q.totals.complete} מתוך ${q.totals.all} סרטונים הושלמו`));
    root.replaceChildren(h('div', { class: 'page qc', 'data-testid': 'quick-catalog' },
      h('div', { class: 'qc-head' },
        h('div', { style: { flex: 1 } },
          h('div', { class: 'meta' }, `הושלמו ${q.totals.complete} מתוך ${q.totals.all} (${pct}%) · נשארו ${q.totals.remaining}`),
          h('div', { class: 'bar', 'data-testid': 'qc-progress', 'data-complete': q.totals.complete, 'data-all': q.totals.all }, h('i', { style: { width: `${pct}%` } }))),
        h('div', { class: 'toolbar', style: { margin: 0 } }, FILTERS.map(([k, l]) => h('button', { class: `chip`, 'aria-pressed': String(filter === k), onclick: () => { filter = k; render(); } }, l)))),
      h('div', { class: 'qc-body' },
        h('ul', { class: 'list qc-queue', 'data-testid': 'qc-queue', 'aria-label': 'תור סרטונים' },
          visible().length ? visible().map(i => h('li', { 'aria-selected': String(sel && keyOf(i) === keyOf(sel)), 'data-testid': 'qc-item', 'data-complete': String(i.complete), tabindex: 0,
            onclick: () => { sel = i; render(); }, onkeydown: e => { if (e.key === 'Enter') { sel = i; render(); } } },
            h('span', { class: 'ltr mono qc-name' }, i.name),
            i.complete ? pill('הושלם', 'ok') : pill(`חסרים ${i.missing}`, 'warn'))) : [h('li', {}, filter === 'done' ? 'עוד לא הושלם אף סרטון.' : 'אין סרטונים לטיפול. כל הכבוד.')]),
        sel ? detail(sel) : h('div', { class: 'empty' }, 'אין סרטונים בתור. סנכרן את הענן או ייבא סרטונים בספרייה.'))));
  }

  function detail(i) {
    if (i.kind === 'cloud') {
      return h('div', { class: 'qc-main', 'data-testid': 'qc-detail' },
        h('h2', { class: 'ltr mono' }, i.name),
        h('div', { class: 'banner warn' }, 'הסרטון נמצא בענן ועוד לא נפתח בסטודיו. הפתיחה קוראת מהענן בלבד (בלי לשנות דבר) ויוצרת עותק צפייה במחשב. בסרטון 4K זה לוקח כרבע דקה.'),
        h('button', { class: 'btn primary', 'data-testid': 'qc-open-cloud', onclick: async e => {
          e.target.disabled = true; e.target.textContent = 'פותח…';
          try {
            let j = await api(`/api/cloud/objects/${i.cloud_object_id}/open`, { method: 'POST', body: {} });
            do { await new Promise(r => setTimeout(r, 600)); j = await api(`/api/jobs/${j.job_id ?? j.id}`); } while (j.state === 'running');
            if (j.state !== 'done') throw new Error(j.error ?? 'הפתיחה נכשלה');
            await reload(j.report.source_id);
            sel = q.items.find(x => x.source_id === j.report.source_id) ?? sel; render();
          } catch (err) { toast(err.message, true); e.target.disabled = false; e.target.textContent = 'פתח את הסרטון'; }
        } }, 'פתח את הסרטון'));
    }
    const main = h('div', { class: 'qc-main', 'data-testid': 'qc-detail', 'data-source': i.source_id });
    const vid = h('video', { class: 'qc-video', controls: true, preload: 'metadata', 'data-testid': 'qc-video' });
    api(`/api/sources/${i.source_id}`).then(s => { vid.src = s.playback_url; }).catch(() => {});
    const ok = k => i.video.find(x => x.key === k)?.ok;
    main.append(
      h('div', { class: 'qc-title' }, h('h2', { class: 'ltr mono' }, i.name), i.complete ? pill('הקטלוג של הסרטון הושלם', 'ok') : pill(`חסרים ${i.missing} פריטים`, 'warn'), i.approved ? pill('Ground Truth מאושר', 'ok') : null),
      h('div', { class: 'qc-split' },
        h('div', { class: 'qc-steps' },
          step(1, 'של מי הסרטון?', ok('owner'), ownerControl(i)),
          step(2, 'איזה ענף?', ok('sport'), sportControl(i)),
          step(3, 'יש בסרטון אירועים (גלים, נפילות וכד׳)?', ok('triage'), triageControl(i))),
        vid),
      i.triage === 'has_events' ? step(4, `אירועים (${i.events.length})`, i.events.every(e => e.complete) && ok('watched'), eventsControl(i)) : null,
      h('div', { class: 'qc-foot' },
        i.triage === 'has_events' ? h('button', { class: 'btn', onclick: () => openInWorkbench(i.source_id) }, 'פתח בעמוד הסימון') : null,
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn primary', 'data-testid': 'qc-next', onclick: next }, 'לסרטון הבא ←')));
    return main;
  }

  function step(n, title, done, body) {
    return h('section', { class: `qc-step${done ? ' done' : ''}`, 'data-step': n, 'data-done': String(!!done) },
      h('h3', {}, h('span', { class: 'qc-num' }, done ? '✓' : n), title), body);
  }

  function ownerControl(i) {
    let newName = '';
    const sel = h('select', { 'data-testid': 'qc-owner', 'aria-label': 'בעל הסרטון', onchange: e => setOwner(i, e.target.value || null) },
      h('option', { value: '' }, '— בחר גולש —'), athletes.map(a => h('option', { value: a.id, selected: a.id === i.owner.athlete_id }, a.label)));
    return h('div', { class: 'qc-row' }, sel,
      h('input', { type: 'text', placeholder: 'או שם גולש חדש', 'data-testid': 'qc-new-athlete', oninput: e => { newName = e.target.value; },
        onkeydown: e => { if (e.key === 'Enter') add(); } }),
      h('button', { class: 'btn sm', 'data-testid': 'qc-add-athlete', onclick: () => add() }, 'הוסף ושייך'),
      i.owner.status === 'needs_review' ? pill('השיוך מסומן לבדיקה', 'warn') : null);
    async function add() {
      if (!newName.trim()) return toast('כתוב שם לגולש החדש', true);
      const a = await api('/api/athletes', { method: 'POST', body: { label: newName.trim() } });
      athletes = (await api('/api/athletes')).items;
      await setOwner(i, a.id);
    }
  }
  async function setOwner(i, athleteId) {
    const prev = i.owner.label;
    if (i.owner.athlete_id && athleteId !== i.owner.athlete_id && !confirm(`הסרטון משויך כעת ל-${prev}. להחליף?`)) return render();
    try {
      await api(`/api/sources/${i.source_id}/catalog-owner`, { method: 'POST', body: { owner_athlete_id: athleteId, expected_version: i.owner.version, confirm_reassign: !!i.owner.athlete_id } });
      toast(athleteId ? 'השיוך נשמר' : 'השיוך הוסר');
    } catch (e) { toast(e.code === 'VERSION_CONFLICT' ? 'השיוך שונה במקום אחר בינתיים — טענתי את המצב העדכני. בחר שוב.' : e.message, true); }
    await reload(i.source_id);
  }

  function sportControl(i) {
    const sports = sportsList();
    return h('div', { class: 'qc-row' },
      h('select', { 'data-testid': 'qc-sport', 'aria-label': 'ענף', onchange: async e => {
        try { await api(`/api/sources/${i.source_id}/sport`, { method: 'PATCH', body: { sport_id: e.target.value || null, reason: 'quick-catalog' } }); toast('הענף נשמר'); }
        catch (err) { toast(err.message, true); }
        await reload(i.source_id);
      } }, h('option', { value: '' }, '— בחר ענף —'), sports.map(s => h('option', { value: s.id, selected: s.id === i.sport_id }, s.name_he))),
      !i.sport_id && i.suggested_sport_id ? h('span', { class: 'meta' }, `הצעה מהמערכת: ${sportName(i.suggested_sport_id)} (נשמרת רק אם תבחר)`) : null);
  }

  function triageControl(i) {
    if (i.triage === 'has_events') return h('div', { class: 'meta' }, 'יש אירועים מסומנים. ההשלמה שלהם מופיעה בשלב 4.');
    const post = async (result, extra = {}) => {
      try { await api(`/api/catalog/sources/${i.source_id}/triage`, { method: 'POST', body: { result, expected_version: i.draft_version, ...extra } }); }
      catch (e) { toast(e.message, true); }
      await reload(i.source_id);
    };
    return h('div', {},
      h('div', { class: 'qc-row' },
        h('button', { class: 'btn primary', 'data-testid': 'qc-has-events', onclick: () => openInWorkbench(i.source_id) }, 'כן — לסימון האירועים'),
        h('button', { class: `btn${i.triage === 'no_events' ? ' primary' : ''}`, 'data-testid': 'qc-no-events', 'aria-pressed': String(i.triage === 'no_events'), onclick: () => post('no_events', { watched_all: true }) }, 'אין — צפיתי בכל הסרטון'),
        h('button', { class: `btn${i.triage === 'unsure' ? ' primary' : ''}`, 'data-testid': 'qc-unsure', 'aria-pressed': String(i.triage === 'unsure'), onclick: () => post('unsure') }, 'לא בטוח — לבדיקה')),
      h('div', { class: 'meta' }, `תשובה נוכחית: ${TRIAGE_HE[i.triage] ?? i.triage}. "אין" מסמן את כל הסרטון כנבדק, לכן לחץ עליו רק אחרי שצפית בו עד הסוף.`));
  }

  function eventsControl(i) {
    const watched = i.video.find(x => x.key === 'watched');
    return h('div', {},
      h('table', { class: 't qc-events', 'data-testid': 'qc-events' },
        h('thead', {}, h('tr', {}, h('th', {}, 'אירוע'), h('th', {}, 'מה חסר / מה מולא'))),
        h('tbody', {}, i.events.map((e, n) => h('tr', { 'data-testid': 'qc-event', 'data-complete': String(e.complete) },
          h('td', {}, h('b', {}, `${n + 1}. ${eventHe(e.event_type, i.sport_id)}`), h('div', { class: 'meta ltr' }, `f${e.start_frame}–f${e.end_frame}`), h('div', { class: 'meta' }, e.athlete_label ?? 'מבצע לא נבחר')),
          h('td', {}, h('div', { class: 'qc-checks' }, e.checklist.map(c => h('button', {
            class: `ck ${c.ok ? 'ok' : c.required ? 'miss' : 'opt'}`, 'data-testid': `qc-ck-${c.key}`, 'data-ok': String(c.ok),
            title: c.ok ? 'מולא — לחץ לעריכה' : c.required ? 'חסר — לחץ למילוי' : 'רשות',
            onclick: () => openInWorkbench(i.source_id, e.id, c.key === 'box' ? 'box' : 'event'),
          }, `${c.ok ? '✓' : c.required ? '✕' : '○'} ${c.key === 'box' ? BOX_HE[c.state] ?? EVENT_HE.box : EVENT_HE[c.key]}`)))))))),
      h('div', { class: 'qc-row', style: { marginTop: '8px' } },
        watched?.ok ? pill('צפית בכל הסרטון', 'ok') : pill(`נבדק ${Math.round((watched?.ratio ?? 0) * 100)}% מהסרטון`, 'warn'),
        watched?.ok ? null : h('span', { class: 'meta' }, 'כדי שאירועים לא יוחמצו: בעמוד הסימון לחץ "כל הסרטון נבדק" אחרי שצפית בו עד הסוף.'),
        h('button', { class: 'btn sm', onclick: () => openInWorkbench(i.source_id) }, 'הוסף אירוע בעמוד הסימון')));
  }

  render();
}
