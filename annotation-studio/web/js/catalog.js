// Catalog ("קטלוג"): THE cataloguing process. One video at a time, three short questions, then a checklist of every
// remaining field; the marking workbench is step 4 of the same process (opened at the right event/tab, with a way back).
// Nothing here is a second copy of the data: owner, sport and the draft are read and written through the same APIs the
// library and the workbench use, so no catalogued detail can be lost or diverge. Details of each event (performer,
// usability, decision, reasons, key moments, BOX) are edited in the workbench, opened directly at the right event/tab.
import { h, api, toast, pill, sportsList, sportName, eventHe, timecode, REASON_HE, USABILITY_HE, DECISION_HE, PRIMARY_HE } from './ui.js';
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

  async function runJob(btn, url, msg) {
    btn.disabled = true;
    try {
      let j = await api(url, { method: 'POST', body: {} });
      do { await new Promise(r => setTimeout(r, 500)); j = await api(`/api/jobs/${j.job_id}`); } while (j.state === 'running');
      if (j.state !== 'done') throw new Error(j.error ?? 'הפעולה נכשלה');
      toast(msg(j.report)); await reload(sel ? keyOf(sel) : null);
    } catch (e) { toast(e.code === 'CLOUD_NOT_CONFIGURED' ? 'הענן לא מוגדר במחשב הזה (.studio-cloud.env)' : e.message, true); }
    btn.disabled = false;
  }

  function render() {
    if (!root.isConnected) return;   // the operator already navigated elsewhere
    const pct = q.totals.all ? Math.round((q.totals.complete / q.totals.all) * 100) : 0;
    setTopbar(h('strong', {}, 'קטלוג'), h('span', { class: 'meta' }, `${q.totals.complete} מתוך ${q.totals.all} סרטונים הושלמו`),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn sm', 'data-testid': 'qc-sync-cloud', title: 'מעדכן את רשימת הסרטונים מהענן (קריאה בלבד)', onclick: e => runJob(e.target, '/api/cloud/sync', r => `נמצאו ${r.raw + r.processed_legacy} סרטונים בענן`) }, 'עדכן מהענן'),
      h('button', { class: 'btn sm', title: 'קולט סרטונים מתיקיות המחשב', onclick: e => runJob(e.target, '/api/ingestion/reconcile', r => `נקלטו ${r.ingested} סרטונים חדשים`) }, 'קלוט מהמחשב'),
      h('a', { class: 'btn sm', href: '#/library', title: 'שיוך/סיווג של הרבה סרטונים יחד, אימות ארכיון' }, 'פעולות מרובות'),
      h('a', { class: 'btn sm', href: '#/cloud', title: 'מצב הסרטונים בענן ואימות זהות' }, 'מצב הענן'));
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
    main.append(...[
      h('div', { class: 'qc-title' }, h('h2', { class: 'ltr mono' }, i.name), i.complete ? pill('הקטלוג של הסרטון הושלם', 'ok') : pill(`חסרים ${i.missing} פריטים`, 'warn'), i.approved ? pill('Ground Truth מאושר', 'ok') : null),
      h('div', { class: 'qc-split' },
        h('div', { class: 'qc-steps' },
          step(1, 'של מי הסרטון?', ok('owner'), ownerControl(i)),
          step(2, 'איזה ענף?', ok('sport'), sportControl(i)),
          step(3, 'מי עוד מופיע בסרטון? (רשות)', i.appearances.length > 0, peopleControl(i)),
          step(4, 'יש בסרטון אירועים (גלים, נפילות וכד׳)?', ok('triage'), triageControl(i))),
        vid),
      i.triage === 'has_events' ? step(5, `האירועים — כל הנתונים (${i.events.length})`, i.events.every(e => e.complete) && ok('watched'), eventsControl(i)) : null,
      step(i.triage === 'has_events' ? 6 : 5, 'מצב הסרטון', null, statusControl(i)),
      h('div', { class: 'qc-foot' },
        i.triage === 'has_events' ? h('button', { class: 'btn', onclick: () => openInWorkbench(i.source_id) }, 'פתח בעמוד הסימון') : null,
        h('span', { class: 'spacer' }),
        h('button', { class: 'btn primary', 'data-testid': 'qc-next', onclick: next }, 'לסרטון הבא ←'))].filter(Boolean));   // DOM append would print "null"
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
      i.owner.athlete_id ? h('label', { class: 'meta', style: { display: 'flex', gap: '4px', alignItems: 'center' } },
        h('input', { type: 'checkbox', 'data-testid': 'qc-owner-unsure', checked: i.owner.status === 'needs_review', onchange: e => setOwner(i, i.owner.athlete_id, e.target.checked ? 'needs_review' : 'assigned') }),
        'לא בטוח בשיוך — לבדיקה') : null);
    async function add() {
      if (!newName.trim()) return toast('כתוב שם לגולש החדש', true);
      const a = await api('/api/athletes', { method: 'POST', body: { label: newName.trim() } });
      athletes = (await api('/api/athletes')).items;
      await setOwner(i, a.id);
    }
  }
  async function setOwner(i, athleteId, status) {
    const prev = i.owner.label, replacing = !!i.owner.athlete_id && athleteId !== i.owner.athlete_id;
    if (replacing && !confirm(`הסרטון משויך כעת ל-${prev}. להחליף?`)) return render();
    try {
      await api(`/api/sources/${i.source_id}/catalog-owner`, { method: 'POST', body: { owner_athlete_id: athleteId, status: status ?? (athleteId ? 'assigned' : 'unassigned'), expected_version: i.owner.version, confirm_reassign: replacing || (!!i.owner.athlete_id && !athleteId) } });
      toast(status === 'needs_review' ? 'השיוך סומן לבדיקה' : athleteId ? 'השיוך נשמר' : 'השיוך הוסר');
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
      !i.sport_id && i.suggested_sport_id ? h('span', { class: 'meta' }, `הצעה מהמערכת: ${sportName(i.suggested_sport_id)} (נשמרת רק אם תבחר)`) : null,
      h('span', { class: 'meta' }, 'ענפים נוספים בסרטון:'),
      ...(i.extra_sports ?? []).filter(x => x !== i.sport_id).map(x => pill(sportName(x))),
      h('select', { 'data-testid': 'qc-extra-sport', 'aria-label': 'הוסף ענף נוסף', onchange: async e => {
        if (!e.target.value) return;
        try { await api(`/api/sources/${i.source_id}/sports`, { method: 'POST', body: { sport_id: e.target.value } }); toast('הענף הנוסף נשמר'); } catch (err) { toast(err.message, true); }
        await reload(i.source_id);
      } }, h('option', { value: '' }, '＋ הוסף'), sports.filter(x => x.id !== i.sport_id && !(i.extra_sports ?? []).includes(x.id)).map(x => h('option', { value: x.id }, x.name_he))));
  }

  // Who is visible in the video (independent of the owner and of any event).
  function peopleControl(i) {
    let unsure = false;
    return h('div', {},
      h('div', { class: 'qc-row', 'data-testid': 'qc-people' },
        i.appearances.length ? i.appearances.map(a => pill(`${a.label ?? 'לא ידוע'}${a.uncertain ? ' (לא ודאי)' : ''}`, a.uncertain ? 'warn' : 'ok')) : h('span', { class: 'meta' }, 'עוד לא נרשם אף אחד. מבצעי אירועים נרשמים כאן אוטומטית.')),
      h('div', { class: 'qc-row', style: { marginTop: '6px' } },
        h('select', { 'data-testid': 'qc-add-person', 'aria-label': 'הוסף אדם שמופיע בסרטון', onchange: async e => {
          if (!e.target.value) return;
          try { await api(`/api/sources/${i.source_id}/appearances`, { method: 'POST', body: { athlete_id: e.target.value, uncertain: unsure } }); toast('נשמר'); } catch (err) { toast(err.message, true); }
          await reload(i.source_id);
        } }, h('option', { value: '' }, '＋ הוסף גולש שמופיע'), athletes.filter(a => !i.appearances.some(x => x.athlete_id === a.id)).map(a => h('option', { value: a.id }, a.label))),
        h('label', { class: 'meta', style: { display: 'flex', gap: '4px', alignItems: 'center' } }, h('input', { type: 'checkbox', onchange: e => { unsure = e.target.checked; } }), 'לא ודאי')));
  }

  function statusControl(i) {
    const idOk = i.identity.verify_state === 'verified';
    return h('div', { class: 'qc-row', 'data-testid': 'qc-status' },
      pill(`נצפה ${Math.round((i.coverage ?? 0) * 100)}% מהסרטון`, i.coverage >= 0.999 ? 'ok' : 'warn'),
      pill(idOk ? 'זהות הקובץ אומתה' : 'זהות הקובץ טרם אומתה (נדרש לפני אישור)', idOk ? 'ok' : 'warn'),
      i.review_requested ? pill('מסומן לבדיקה חוזרת', 'warn') : null,
      pill(i.approved ? 'Ground Truth מאושר' : 'Ground Truth טרם אושר', i.approved ? 'ok' : ''),
      h('button', { class: 'btn sm', onclick: () => openInWorkbench(i.source_id) }, 'לאישור / היסטוריה בעמוד הסימון'));
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
      h('div', { class: 'qc-evlist', 'data-testid': 'qc-events' }, i.events.map((e, n) => eventCard(i, e, n))),
      h('div', { class: 'qc-row', style: { marginTop: '8px' } },
        watched?.ok ? pill('צפית בכל הסרטון', 'ok') : pill(`נבדק ${Math.round((watched?.ratio ?? 0) * 100)}% מהסרטון`, 'warn'),
        watched?.ok ? null : h('span', { class: 'meta' }, 'כדי שאירועים לא יוחמצו: בעמוד הסימון לחץ "כל הסרטון נבדק" אחרי שצפית בו עד הסוף.'),
        h('button', { class: 'btn sm', onclick: () => openInWorkbench(i.source_id) }, 'הוסף אירוע בעמוד הסימון')));
  }

  /** One event: every recorded value, each row opens the workbench at this event (and the right tab) to edit it. */
  function eventCard(i, e, n) {
    const ck = k => e.checklist.find(c => c.key === k);
    const km = e.key_moments, kmTxt = [['takeoff_frame', 'תחילה'], ['peak_frame', 'שיא'], ['landing_frame', 'סיום']].map(([k, l]) => `${l}: ${km[k] != null ? `f${km[k]}` : '—'}`).join(' · ');
    const box = ck('box');
    const rows = [
      ['range', 'טווח', `f${e.start_frame}–f${e.end_frame} (${e.end_frame - e.start_frame} פריימים)`, null],
      ['event_type', 'סוג', `${eventHe(e.event_type, e.effective_sport_id)}${e.sport_id && e.sport_id !== i.sport_id ? ` · ענף: ${sportName(e.sport_id)}` : ''}`, ck('event_type')],
      ['performer', 'מי ביצע', e.athlete_label ?? PRIMARY_HE[e.primary_status] ?? 'לא נבחר', ck('performer')],
      ['usability', 'שימושיות', USABILITY_HE[e.usability] ?? e.usability, ck('usability')],
      ['reasons', 'סיבות', e.reason_codes.length ? e.reason_codes.map(r => REASON_HE[r] ?? r).join(', ') : '—', ck('reasons')],
      ['decision', 'החלטה', DECISION_HE[e.decision] ?? e.decision, ck('decision')],
      ['key_moments', 'רגעי מפתח', kmTxt, ck('key_moments')],
      ...e.required_attrs.map(a => [`attr:${a}`, `שדה חובה: ${a}`, e.attrs?.[a] ?? '—', ck(`attr:${a}`)]),
      ['box', 'BOX על הגולש', `${BOX_HE[box?.state] ?? '—'}${e.boxes ? ` · ${e.boxes} תיבות${box?.box_frames ? ` · נבדקו ${box.checked}/${box.box_frames}` : ''}` : ''}`, box],
      ['action', 'אותה פעולה בסרטון אחר', e.physical_actions.length ? `מקושר (${e.physical_actions.length})` : '—', null],
      ['notes', 'הערות', e.notes || '—', ck('notes')],
    ];
    return h('div', { class: `qc-ev${e.complete ? ' done' : ''}`, 'data-testid': 'qc-event', 'data-complete': String(e.complete) },
      h('div', { class: 'qc-ev-h' }, h('b', {}, `אירוע ${n + 1}`), e.complete ? pill('הושלם', 'ok') : pill(`חסרים ${e.checklist.filter(c => c.required && !c.ok).length}`, 'warn'), e.needs_review ? pill('מסומן לבדיקה', 'warn') : null),
      h('dl', { class: 'qc-fields' }, rows.map(([key, label, value, c]) => h('button', {
        class: `qc-field ${c ? (c.ok ? 'ok' : c.required ? 'miss' : 'opt') : ''}`, 'data-testid': `qc-ck-${key}`, 'data-ok': String(c ? c.ok : true),
        title: c && !c.ok && c.required ? 'חסר — לחץ למילוי' : 'לחץ לעריכה', onclick: () => openInWorkbench(i.source_id, e.id, key === 'box' ? 'box' : 'event'),
      }, h('dt', {}, `${c ? (c.ok ? '✓' : c.required ? '✕' : '○') : '·'} ${label}`), h('dd', {}, value)))));
  }

  render();
}
