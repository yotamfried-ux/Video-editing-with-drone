// Cloud catalog: SportReel's existing source videos in R2, used in place (read-only; nothing is downloaded up front).
import { h, api, ltr, pill, toast, fmtBytes, fmtDate, timecode, sportName, STATUS_HE, STATUS_CLASS } from './ui.js';
import { setTopbar } from './main.js';

const AVAIL = { available: ['זמין ב-raw/', 'ok'], legacy_processed: ['רק ב-processed/ (נדרש שחזור)', 'warn'], missing: ['חסר בענן', 'bad'] };
const PIPE = { new: 'לא עובד', processed: 'עובד', processed_legacy: 'עובד (ישן)', unknown: 'לא ידוע' };

async function poll(jobId) {
  for (;;) {
    const j = await api(`/api/jobs/${jobId}`);
    if (j.state !== 'running') return j;
    await new Promise(r => setTimeout(r, 400));
  }
}

export async function renderCloud(root) {
  setTopbar(h('strong', {}, 'ענן'), pill('קריאה בלבד · R2'));
  const status = await api('/api/cloud/status');
  if (!status.configured) {
    root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'סרטוני הענן'),
      h('div', { class: 'banner bad', 'data-testid': 'cloud-unconfigured' }, 'החיבור לענן אינו מוגדר. צור טוקן R2 לקריאה בלבד והגדר אותו לפי '), h('code', { class: 'ltr' }, 'docs/annotation-studio/CLOUD-QUICKSTART.md')));
    return;
  }
  const f = { q: '', avail: '', pipe: '' };
  const out = h('div'), stats = h('div', { class: 'stats' });
  let items = [];
  const busy = async (btn, fn) => { btn.disabled = true; try { await fn(); } catch (e) { toast(e.message, true); } btn.disabled = false; };

  const render = () => {
    const list = items.filter(o => (!f.q || o.name.toLowerCase().includes(f.q.toLowerCase()) || o.key.toLowerCase().includes(f.q.toLowerCase()))
      && (!f.avail || o.availability === f.avail) && (!f.pipe || o.pipeline_state === f.pipe));
    stats.replaceChildren(...[['בקטלוג', items.length], ['זמינים ב-raw/', items.filter(o => o.availability === 'available').length],
      ['רק ב-processed/', items.filter(o => o.availability === 'legacy_processed').length], ['חסרים', items.filter(o => o.availability === 'missing').length],
      ['נפתחו לתיוג', items.filter(o => o.opened).length]].map(([l, n]) => h('div', { class: 'stat' }, h('b', {}, n), h('span', {}, l))));
    if (!list.length) return out.replaceChildren(h('div', { class: 'empty' }, items.length ? 'אין תוצאות לסינון' : 'הקטלוג ריק. לחץ "סנכרן קטלוג מהענן".'));
    out.replaceChildren(h('table', { class: 't', 'data-testid': 'cloud-table' },
      h('thead', {}, h('tr', {}, ['שם', 'הועלה', 'גודל', 'משך', 'ענף', 'מצב פייפליין', 'מיקום / זמינות', 'זהות', 'תיוג', ''].map(x => h('th', {}, x)))),
      h('tbody', {}, list.map(o => {
        const [aText, aCls] = AVAIL[o.availability];
        return h('tr', { 'data-testid': 'cloud-row', 'data-key': o.key },
          h('td', {}, ltr(o.name)), h('td', {}, o.uploaded_at ? fmtDate(o.uploaded_at) : '—'), h('td', {}, ltr(fmtBytes(o.size))),
          h('td', {}, o.duration_ms != null ? ltr(timecode(Math.round(o.duration_ms / 1000 * 30), 30)) : '—'),
          h('td', {}, sportName(o.sport_id)), h('td', {}, PIPE[o.pipeline_state] ?? o.pipeline_state),
          h('td', {}, pill(aText, aCls), ' ', ltr(o.location)),
          h('td', {}, o.verify_state === 'verified' ? pill('אומתה', 'ok') : o.verify_state === 'mismatch' ? pill('אי-התאמה!', 'bad') : o.opened ? pill('לא אומתה', 'warn') : o.identity === 'recorded' ? pill('ברשומה', '') : pill('תחושב בפתיחה', 'warn')),
          h('td', {}, o.annotation_status ? pill(STATUS_HE[o.annotation_status], STATUS_CLASS[o.annotation_status]) : '—'),
          h('td', {}, o.opened ? h('a', { class: 'btn sm primary', href: `#/annotate/${o.source_id}`, 'data-testid': 'cloud-annotate' }, 'המשך תיוג')
            : o.availability === 'missing' ? '—'
            : h('button', { class: 'btn sm primary', 'data-testid': 'cloud-open', onclick: e => busy(e.target, async () => {
              toast('פותח… (נקרא מהענן, ללא הורדה מלאה)');
              const j = await poll((await api(`/api/cloud/objects/${o.id}/open`, { method: 'POST', body: {} })).job_id);
              if (j.state !== 'done') throw new Error(j.error ?? 'הפתיחה נכשלה');
              location.hash = `#/annotate/${j.report.source_id}`;
            }) }, 'פתח לתיוג')));
      }))));
  };

  const reload = async () => { items = (await api('/api/cloud/objects')).items; render(); };
  const sel = (opts, key, label) => h('select', { 'aria-label': label, onchange: e => { f[key] = e.target.value; render(); } }, opts.map(([v, l]) => h('option', { value: v }, l)));
  root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'סרטוני המקור בענן'),
    h('div', { class: 'sub' }, `באקט ${status.bucket} · גישת קריאה בלבד: הסטודיו לא כותב, לא מוחק ולא מעלה מחדש. הסרטונים נטענים לפי דרישה עם גלילה (Range).`),
    stats,
    h('div', { class: 'toolbar' },
      h('input', { type: 'search', placeholder: 'חיפוש שם / מפתח', 'aria-label': 'חיפוש בענן', oninput: e => { f.q = e.target.value; render(); } }),
      sel([['', 'כל המיקומים'], ['available', 'זמין ב-raw/'], ['legacy_processed', 'רק ב-processed/'], ['missing', 'חסר']], 'avail', 'זמינות'),
      sel([['', 'כל מצבי הפייפליין'], ['new', 'לא עובד'], ['processed', 'עובד'], ['processed_legacy', 'עובד (ישן)']], 'pipe', 'מצב פייפליין'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn primary', 'data-testid': 'cloud-sync', onclick: e => busy(e.target, async () => {
        const j = await poll((await api('/api/cloud/sync', { method: 'POST', body: {} })).job_id);
        if (j.state !== 'done') throw new Error(j.error ?? 'הסנכרון נכשל');
        toast(`הקטלוג עודכן: ${j.report.raw} ב-raw/, ${j.report.processed_legacy} ב-processed/, ${j.report.missing} חסרים`, j.report.missing > 0);
        await reload();
      }) }, 'סנכרן קטלוג מהענן'),
      h('button', { class: 'btn', 'data-testid': 'cloud-verify', title: 'מוריד בזרימה ומחשב SHA-256 לכל סרטון שנפתח; נדרש לפני אישור Ground Truth', onclick: e => busy(e.target, async () => {
        const j = await poll((await api('/api/cloud/verify', { method: 'POST', body: {} })).job_id);
        if (j.state !== 'done') throw new Error(j.error ?? 'האימות נכשל');
        toast(`אומתו ${j.report.verified}/${j.report.checked}${j.report.mismatched.length ? ` · ${j.report.mismatched.length} אי-התאמות!` : ''}`, j.report.mismatched.length > 0);
        await reload();
      }) }, 'אמת זהות (SHA-256)')),
    out));
  await reload();
}
