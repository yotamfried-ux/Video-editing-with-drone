// Cloud catalog: SportReel's existing source videos in R2, used in place (read-only; nothing is downloaded up front).
import { h, api, ltr, pill, toast, fmtBytes, fmtDate, timecode, sportName, STATUS_HE, STATUS_CLASS, dialog, closeDialog } from './ui.js';
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
  const [status, athRes] = await Promise.all([
    api('/api/cloud/status'),
    api('/api/athletes')
  ]);
  let athletes = athRes.items || [];

  if (!status.configured) {
    root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'סרטוני הענן'),
      h('div', { class: 'banner bad', 'data-testid': 'cloud-unconfigured' }, 'החיבור לענן אינו מוגדר. צור טוקן R2 לקריאה בלבד והגדר אותו לפי '), h('code', { class: 'ltr' }, 'docs/annotation-studio/CLOUD-QUICKSTART.md')));
    return;
  }
  const f = { q: '', avail: '', pipe: '', owner: '' };
  const out = h('div'), stats = h('div', { class: 'stats' });
  let items = [];
  const busy = async (btn, fn) => { btn.disabled = true; try { await fn(); } catch (e) { toast(e.message, true); } btn.disabled = false; };

  const render = () => {
    const list = items.filter(o =>
      (!f.q || o.name.toLowerCase().includes(f.q.toLowerCase()) || o.key.toLowerCase().includes(f.q.toLowerCase())) &&
      (!f.avail || o.availability === f.avail) &&
      (!f.pipe || o.pipeline_state === f.pipe) &&
      (!f.owner || (f.owner === 'unassigned' ? !o.owner_athlete_id : o.owner_athlete_id === f.owner))
    );
    stats.replaceChildren(...[
      ['בקטלוג', items.length],
      ['שויכו לגולש', items.filter(o => o.owner_athlete_id != null).length],
      ['ללא שיוך', items.filter(o => o.owner_athlete_id == null).length],
      ['זמינים ב-raw/', items.filter(o => o.availability === 'available').length],
      ['רק ב-processed/', items.filter(o => o.availability === 'legacy_processed').length],
      ['חסרים', items.filter(o => o.availability === 'missing').length],
      ['נפתחו לתיוג', items.filter(o => o.opened).length]
    ].map(([l, n]) => h('div', { class: 'stat' }, h('b', {}, n), h('span', {}, l))));

    if (!list.length) return out.replaceChildren(h('div', { class: 'empty' }, items.length ? 'אין תוצאות לסינון' : 'הקטלוג ריק. לחץ "סנכרן קטלוג מהענן".'));

    out.replaceChildren(h('table', { class: 't', 'data-testid': 'cloud-table' },
      h('thead', {}, h('tr', {}, ['שם', 'שיוך לגולש', 'הועלה', 'גודל', 'משך', 'ענף', 'מצב פייפליין', 'מיקום / זמינות', 'זהות', 'תיוג', 'פעולות'].map(x => h('th', {}, x)))),
      h('tbody', {}, list.map(o => {
        const [aText, aCls] = AVAIL[o.availability];
        const ownerPill = o.owner_athlete_id
          ? pill(`גולש: ${o.owner_athlete_label || o.owner_athlete_id.slice(0, 8)}`, o.owner_status === 'needs_review' ? 'warn' : 'ok')
          : pill('טרם שויך', 'muted');

        return h('tr', { 'data-testid': 'cloud-row', 'data-key': o.key },
          h('td', {}, ltr(o.name)),
          h('td', {}, ownerPill),
          h('td', {}, o.uploaded_at ? fmtDate(o.uploaded_at) : '—'),
          h('td', {}, ltr(fmtBytes(o.size))),
          h('td', {}, o.duration_ms != null ? ltr(timecode(Math.round(o.duration_ms / 1000 * 30), 30)) : '—'),
          h('td', {}, sportName(o.sport_id)),
          h('td', {}, PIPE[o.pipeline_state] ?? o.pipeline_state),
          h('td', {}, pill(aText, aCls), ' ', ltr(o.location)),
          h('td', {}, o.verify_state === 'verified' ? pill('אומתה', 'ok') : o.verify_state === 'mismatch' ? pill('אי-התאמה!', 'bad') : o.opened ? pill('לא אומתה', 'warn') : o.identity === 'recorded' ? pill('ברשומה', '') : pill('תחושב בפתיחה', 'warn')),
          h('td', {}, o.annotation_status ? pill(STATUS_HE[o.annotation_status], STATUS_CLASS[o.annotation_status]) : '—'),
          h('td', { style: { display: 'flex', gap: '6px' } },
            h('button', {
              class: 'btn sm',
              'data-testid': 'cloud-assign-owner',
              onclick: () => openCloudAssignDialog(o)
            }, 'שייך לגולש'),
            o.opened ? h('a', { class: 'btn sm primary', href: `#/annotate/${o.source_id}`, 'data-testid': 'cloud-annotate' }, 'המשך תיוג')
              : o.availability === 'missing' ? '—'
              : h('button', { class: 'btn sm primary', 'data-testid': 'cloud-open', onclick: e => busy(e.target, async () => {
                toast('פותח… (נקרא מהענן, ללא הורדה מלאה)');
                const j = await poll((await api(`/api/cloud/objects/${o.id}/open`, { method: 'POST', body: {} })).job_id);
                if (j.state !== 'done') throw new Error(j.error ?? 'הפתיחה נכשלה');
                location.hash = `#/annotate/${j.report.source_id}`;
              }) }, 'פתח לתיוג')
          )
        );
      }))));
  };

  function openCloudAssignDialog(o) {
    let selectedAth = o.owner_athlete_id || '';
    let status = o.owner_status || (o.owner_athlete_id ? 'assigned' : 'unassigned');
    let reason = '';

    const athSelect = h('select', {
      id: 'cloud-dlg-athlete',
      'aria-label': 'בחר גולש',
      style: { width: '100%', marginBottom: '10px' },
      onchange: e => {
        selectedAth = e.target.value;
        if (selectedAth && status === 'unassigned') status = 'assigned';
        if (!selectedAth) status = 'unassigned';
      }
    },
      h('option', { value: '' }, '— ללא שיוך לגולש (Unassigned) —'),
      athletes.map(a => h('option', { value: a.id, selected: a.id === selectedAth }, a.label))
    );

    const newAthInput = h('input', {
      type: 'text',
      placeholder: 'שם גולש חדש (למשל: יובל)',
      style: { flex: 1 },
      'aria-label': 'שם גולש חדש'
    });

    const createBtn = h('button', {
      class: 'btn sm primary',
      onclick: async () => {
        const val = newAthInput.value.trim();
        if (!val) return toast('הזן שם גולש', true);
        try {
          const created = await api('/api/athletes', { method: 'POST', body: { label: val } });
          athletes.push(created);
          athSelect.append(h('option', { value: created.id, selected: true }, created.label));
          selectedAth = created.id;
          status = 'assigned';
          newAthInput.value = '';
          toast(`הגולש "${created.label}" נוצר ושויך`);
        } catch (err) { toast(err.message, true); }
      }
    }, '＋ צור גולש');

    dialog('שיוך קובץ ענן לגולש', h('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } },
      h('div', { class: 'meta' }, `קובץ בענן: ${o.name}`),
      o.owner_athlete_id ? h('div', { class: 'banner warn' }, `הקובץ משויך כרגע ל: ${o.owner_athlete_label || o.owner_athlete_id}.`) : null,
      h('label', { class: 'f' }, 'בחר גולש:'),
      athSelect,
      h('label', { class: 'f' }, 'או צור גולש חדש:'),
      h('div', { style: { display: 'flex', gap: '8px', marginBottom: '10px' } }, newAthInput, createBtn),
      h('label', { class: 'f' }, 'הערה (אופציונלי):'),
      h('input', {
        type: 'text',
        placeholder: 'סיבה / הערה',
        style: { width: '100%' },
        oninput: e => { reason = e.target.value; }
      })
    ), [
      h('button', {
        class: 'btn primary',
        'data-testid': 'cloud-dlg-save',
        onclick: async () => {
          try {
            const res = await api(`/api/cloud/objects/${o.id}/catalog-owner`, {
              method: 'POST',
              body: {
                owner_athlete_id: selectedAth || null,
                status,
                reason: reason || null,
                expected_version: o.owner_version ?? 0,
              }
            });
            o.owner_athlete_id = selectedAth || null;
            o.owner_status = status;
            o.owner_version = res.owner_version;
            const found = athletes.find(a => a.id === selectedAth);
            o.owner_athlete_label = found ? found.label : null;
            closeDialog();
            toast(selectedAth ? `הקובץ בענן שויך ל-${o.owner_athlete_label}` : 'השיוך הוסר');
            render();
          } catch (err) {
            if (err.code === 'VERSION_CONFLICT' || err.status === 409) {
              closeDialog();
              dialog('התנגשות שיוך בענן', h('div', {},
                h('div', { class: 'banner bad' }, err.message || 'קובץ הענן עודכן במקביל.'),
                h('p', {}, 'יש לרענן את רשימת הענן כדי לקבל את הגרסה העדכנית.')
              ), [
                h('button', { class: 'btn primary', onclick: async () => { closeDialog(); await reload(); } }, 'רענן ענן'),
                h('button', { class: 'btn', onclick: closeDialog }, 'סגור')
              ]);
            } else {
              toast(err.message, true);
            }
          }
        }
      }, 'שמור שיוך'),
      h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')
    ]);
  }

  const reload = async () => { items = (await api('/api/cloud/objects')).items; render(); };
  const sel = (opts, key, label) => h('select', { 'aria-label': label, onchange: e => { f[key] = e.target.value; render(); } }, opts.map(([v, l]) => h('option', { value: v }, l)));

  root.replaceChildren(h('div', { class: 'page' },
    h('h1', {}, 'סרטוני המקור בענן'),
    h('div', { class: 'sub' }, `באקט ${status.bucket} · גישת קריאה בלבד: הסטודיו לא כותב, לא מוחק ולא מעלה מחדש. הסרטונים נטענים לפי דרישה עם גלילה (Range).`),
    stats,
    h('div', { class: 'toolbar' },
      h('input', { type: 'search', placeholder: 'חיפוש שם / מפתח', 'aria-label': 'חיפוש בענן', oninput: e => { f.q = e.target.value; render(); } }),
      sel([['', 'כל המיקומים'], ['available', 'זמין ב-raw/'], ['legacy_processed', 'רק ב-processed/'], ['missing', 'חסר']], 'avail', 'זמינות'),
      sel([['', 'כל מצבי הפייפליין'], ['new', 'לא עובד'], ['processed', 'עובד'], ['processed_legacy', 'עובד (ישן)']], 'pipe', 'מצב פייפליין'),
      sel([['', 'כל הגולשים'], ['unassigned', 'ללא שיוך לגולש'], ...athletes.map(a => [a.id, a.label])], 'owner', 'שיוך לגולש'),
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
      }) }, 'אמת זהות (SHA-256)')
    ),
    out
  ));
  await reload();
}
