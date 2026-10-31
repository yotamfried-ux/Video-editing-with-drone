import { h, api, ltr, pill, toast, fmtBytes, timecode, fpsOf, STATUS_HE, STATUS_CLASS, backupStatus, backupBanner, backupPill, sportsList, sportName, dialog, closeDialog } from './ui.js';
import { setTopbar } from './main.js';

export async function renderLibrary(root) {
  setTopbar(h('strong', {}, 'ספרייה'), h('span', { class: 'pill' }, 'סרטוני מקור'));
  const [batches, first, bk, athRes] = await Promise.all([
    api('/api/batches'),
    api('/api/sources?limit=200'),
    backupStatus(),
    api('/api/athletes')
  ]);
  let athletes = athRes.items || [];
  const f = { q: '', status: '', batch: '', sport: '', owner: '', view: 'grid' };
  const out = h('div'); const stats = h('div', { class: 'stats' });
  let items = first.items;

  const render = () => {
    const list = items.filter(s =>
      (!f.q || s.display_name.toLowerCase().includes(f.q.toLowerCase()) || s.sha256.startsWith(f.q)) &&
      (!f.status || s.annotation_status === f.status || s.ingest_state === f.status || s.owner_status === f.status) &&
      (!f.batch || s.batches.includes(f.batch)) &&
      (!f.sport || (s.primary_sport_id ?? 'unknown') === f.sport) &&
      (!f.owner || (f.owner === 'unassigned' ? !s.owner_athlete_id : s.owner_athlete_id === f.owner))
    );
    const unknownN = items.filter(s => s.primary_sport_id == null).length;
    const unassignedN = items.filter(s => s.owner_athlete_id == null).length;

    bulkBar.replaceChildren(
      ...(list.length ? [
        h('select', { id: 'bulk-sport', 'data-testid': 'bulk-sport', 'aria-label': 'ענף לשיוך המוצגים' },
          h('option', { value: '' }, 'שייך את המוצגים לענף…'),
          sportsList().filter(x => x.enabled).map(x => h('option', { value: x.id }, x.name_he))
        ),
        h('button', { class: 'btn sm', 'data-testid': 'bulk-apply', onclick: () => bulkAssignSport(list) }, `שייך ${list.length} לענף`),
        h('span', { class: 'sep' }),
        h('select', { id: 'bulk-owner-select', 'data-testid': 'bulk-owner-select', 'aria-label': 'גולש לשיוך המוצגים' },
          h('option', { value: '' }, 'שייך את המוצגים לגולש…'),
          athletes.map(a => h('option', { value: a.id }, a.label))
        ),
        h('button', { class: 'btn sm primary', 'data-testid': 'bulk-owner-apply', onclick: () => bulkAssignOwner(list) }, `שייך ${list.length} לגולש`)
      ] : []),
      h('span', { class: 'meta', 'data-testid': 'unknown-count' }, `סיווג: ${unknownN} ללא ענף · ${unassignedN} ללא שיוך לגולש`)
    );

    stats.replaceChildren(...[
      ['סה״כ', first.totals.all],
      ['שויכו לגולש', items.filter(s => s.owner_athlete_id != null).length],
      ['ללא שיוך לגולש', items.filter(s => s.owner_athlete_id == null).length],
      ['מאושרים', first.totals.approved],
      ['ללא סימון', first.totals.not_annotated],
      ['שגיאות ארכיון', items.filter(s => s.ingest_state !== 'ready').length]
    ].map(([l, n]) => h('div', { class: 'stat' }, h('b', {}, n), h('span', {}, l))));

    if (!list.length) return out.replaceChildren(h('div', { class: 'empty' }, items.length ? 'אין תוצאות לסינון' : 'עדיין אין סרטונים. הרץ סנכרון קליטה.'));

    out.replaceChildren(f.view === 'grid'
      ? h('div', { class: 'grid' }, list.map(card))
      : h('table', { class: 't' },
        h('thead', {}, h('tr', {}, ['קובץ', 'שיוך לגולש', 'ענף', 'משך', 'סטטוס', 'ארכיון', 'התקדמות', 'פעולות'].map(x => h('th', {}, x)))),
        h('tbody', {}, list.map(s => h('tr', {},
          h('td', {}, ltr(s.display_name)),
          h('td', {}, ownerPill(s)),
          h('td', {}, sportName(s.primary_sport_id)),
          h('td', {}, ltr(timecode(s.frame_count, fpsOf(s)))),
          h('td', {}, pill(STATUS_HE[s.annotation_status], STATUS_CLASS[s.annotation_status])),
          h('td', {}, archBadge(s)),
          h('td', {}, `${Math.round(s.reviewed_ratio * 100)}%`),
          h('td', { style: { display: 'flex', gap: '6px' } },
            h('button', { class: 'btn sm', 'data-testid': 'table-assign-owner', onclick: () => openAssignDialog(s) }, 'שייך לגולש'),
            h('a', { class: 'btn sm primary', href: `#/annotate/${s.id}` }, 'פתח')
          )
        )))
      )
    );
  };

  const archBadge = s => s.provider === 'cloud-r2'
    ? pill(s.verify_state === 'verified' ? '☁ ענן · אומת' : '☁ ענן · זהות לא אומתה', s.verify_state === 'verified' ? 'ok' : 'warn')
    : s.ingest_state === 'ready' ? pill('ארכיון מאומת', 'ok') : pill(STATUS_HE[s.ingest_state], STATUS_CLASS[s.ingest_state]);

  const ownerPill = s => s.owner_athlete_id
    ? pill(`גולש: ${s.owner_athlete_label || s.owner_athlete_id.slice(0, 8)}`, s.owner_status === 'needs_review' ? 'warn' : 'ok')
    : pill('טרם שויך לגולש', 'muted');

  const card = s => h('div', { class: 'card', 'data-testid': 'source-card' },
    h('div', { class: 'thumb', style: s.has_thumb ? { backgroundImage: `url(/media/${s.id}/thumb)` } : {} },
      s.has_thumb ? null : 'אין תמונה ממוזערת',
      h('span', { class: 'tag' }, pill(STATUS_HE[s.annotation_status], STATUS_CLASS[s.annotation_status]))
    ),
    h('div', { class: 'meta', style: { padding: '8px 12px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      h('span', { 'data-testid': 'sport-badge', class: `pill${s.primary_sport_id ? ' ok' : ' warn'}` },
        h('span', { class: 'dot' }), sportName(s.primary_sport_id)
      ),
      h('span', { 'data-testid': 'owner-badge' }, ownerPill(s))
    ),
    h('div', { class: 'body' },
      h('div', { class: 'name', title: s.display_name }, s.display_name),
      h('div', { class: 'meta' }, ltr(`${s.width}×${s.height}`), ltr(`${(fpsOf(s)).toFixed(2)}fps`), ltr(timecode(s.frame_count, fpsOf(s))), ltr(fmtBytes(s.byte_size))),
      h('div', { class: 'meta' }, archBadge(s), s.revision_seq ? pill(`גרסה ${s.revision_seq}`) : null),
      h('div', { class: 'bar', title: 'נבדק' }, h('i', { style: { width: `${Math.round(s.reviewed_ratio * 100)}%` } })),
      h('div', { class: 'meta' }, `${s.segment_count} מקטעים · נבדק ${Math.round(s.reviewed_ratio * 100)}%`),
      h('div', { style: { display: 'flex', gap: '8px', marginTop: '6px' } },
        h('button', {
          class: 'btn sm',
          'data-testid': 'assign-owner-btn',
          onclick: () => openAssignDialog(s)
        }, 'שייך לגולש'),
        h('a', {
          class: 'btn primary sm',
          style: { flex: 1, textAlign: 'center', justifyContent: 'center' },
          href: `#/annotate/${s.id}`,
          'aria-label': `${s.annotation_status === 'not_annotated' ? 'התחל' : 'המשך'} סימון ${s.display_name}`
        }, s.annotation_status === 'not_annotated' ? 'התחל סימון' : 'המשך סימון')
      )
    )
  );

  function openAssignDialog(s) {
    let selectedAth = s.owner_athlete_id || '';
    let status = s.owner_status || (s.owner_athlete_id ? 'assigned' : 'unassigned');
    let reason = '';

    const athSelect = h('select', {
      id: 'dlg-athlete-select',
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

    const statusSelect = h('select', {
      id: 'dlg-status-select',
      'aria-label': 'סטטוס שיוך',
      style: { width: '100%', marginBottom: '10px' },
      onchange: e => { status = e.target.value; }
    },
      h('option', { value: 'assigned', selected: status === 'assigned' }, 'שויך בהצלחה (Assigned)'),
      h('option', { value: 'needs_review', selected: status === 'needs_review' }, 'דורש בירור / בדיקה (Needs Review)'),
      h('option', { value: 'unassigned', selected: status === 'unassigned' }, 'לא משויך (Unassigned)')
    );

    const reasonInput = h('input', {
      type: 'text',
      placeholder: s.owner_athlete_id ? 'סיבת שינוי שיוך (מומלץ לתיעוד היסטורי)' : 'הערת שיוך (אופציונלי)',
      style: { width: '100%', marginBottom: '10px' },
      'aria-label': 'סיבת שיוך',
      oninput: e => { reason = e.target.value; }
    });

    dialog('שיוך סרטון לגולש', h('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px' } },
      h('div', { class: 'meta' }, `קובץ: ${s.display_name}`),
      s.owner_athlete_id ? h('div', { class: 'banner warn' }, `הסרטון משויך כרגע ל: ${s.owner_athlete_label || s.owner_athlete_id}. שינוי שיוך יתועד בהיסטוריית השיוכים ללא מחיקת נתונים.`) : null,
      h('label', { class: 'f' }, 'בחר גולש קיים:'),
      athSelect,
      h('label', { class: 'f' }, 'או צור גולש חדש במקום:'),
      h('div', { style: { display: 'flex', gap: '8px', marginBottom: '10px' } }, newAthInput, createBtn),
      h('label', { class: 'f' }, 'סטטוס שיוך:'),
      statusSelect,
      h('label', { class: 'f' }, 'סיבה / הערה:'),
      reasonInput
    ), [
      h('button', {
        class: 'btn primary',
        'data-testid': 'dlg-save-owner',
        onclick: async () => {
          try {
            const res = await api(`/api/sources/${s.id}/catalog-owner`, {
              method: 'POST',
              body: {
                owner_athlete_id: selectedAth || null,
                status,
                reason: reason || null,
              }
            });
            s.owner_athlete_id = res.owner_athlete_id;
            s.owner_status = res.owner_status;
            s.owner_athlete_label = res.athlete ? res.athlete.label : null;
            closeDialog();
            toast(res.owner_athlete_id ? `הסרטון שויך בהצלחה ל-${res.athlete?.label}` : 'השיוך בוטל');
            render();
          } catch (err) { toast(err.message, true); }
        }
      }, 'שמור שיוך'),
      h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')
    ]);
  }

  const bulkBar = h('div', { class: 'toolbar', 'data-testid': 'bulk-bar' });

  async function bulkAssignSport(list) {
    const sport = document.getElementById('bulk-sport').value;
    if (!sport) return toast('בחר ענף לשיוך', true);
    dialog('שיוך קבוצתי לענף', h('p', {}, `לשייך ${list.length} סרטונים לענף "${sportName(sport)}"? (מתועד ביומן; גרסאות מאושרות לא משתנות)`), [
      h('button', { class: 'btn primary', 'data-testid': 'bulk-confirm', onclick: async () => {
        closeDialog();
        try {
          const r = await api('/api/sources/bulk-sport', { method: 'POST', body: { source_ids: list.map(s => s.id), sport_id: sport, reason: 'bulk' } });
          const ok = new Set(list.map(s => s.id)); for (const k of r.skipped) ok.delete(k.id);
          for (const s of items) if (ok.has(s.id)) s.primary_sport_id = sport;
          toast(`${r.updated} עודכנו${r.skipped.length ? `, ${r.skipped.length} דולגו (דורשים מיפוי אירועים — פתח ושנה ענף ידנית)` : ''}`, r.skipped.length > 0); render();
        } catch (x) { toast(x.message, true); }
      } }, 'אשר'), h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')]);
  }

  async function bulkAssignOwner(list) {
    const ownerId = document.getElementById('bulk-owner-select').value;
    if (!ownerId) return toast('בחר גולש לשיוך', true);
    const targetAth = athletes.find(a => a.id === ownerId);

    try {
      const preview = await api('/api/sources/catalog-owners/bulk', {
        method: 'POST',
        body: {
          source_ids: list.map(s => s.id),
          owner_athlete_id: ownerId,
          preview: true
        }
      });

      const conflictWarning = preview.conflicts_count > 0
        ? h('div', { class: 'banner warn', style: { marginTop: '8px' } },
            `אזהרה: מתוך ${list.length} הסרטונים שנבחרו, ${preview.conflicts_count} כבר משויכים לגולש אחר! שיוך זה ידרוס את השיוך הקיים ויתועד בהיסטוריה.`,
            h('ul', { class: 'list', style: { maxHeight: '100px', overflowY: 'auto', marginTop: '6px' } },
              preview.conflicts.map(c => h('li', {}, `${c.display_name} (משויך ל-${athletes.find(a => a.id === c.current_owner_id)?.label || c.current_owner_id})`))
            )
          )
        : null;

      dialog('שיוך מרוכז לגולש', h('div', {},
        h('p', {}, `האם לשייך ${list.length} סרטונים לגולש "${targetAth?.label || ownerId}"?`),
        conflictWarning
      ), [
        h('button', {
          class: 'btn primary',
          'data-testid': 'bulk-owner-confirm',
          onclick: async () => {
            closeDialog();
            try {
              const applied = await api('/api/sources/catalog-owners/bulk', {
                method: 'POST',
                body: {
                  source_ids: list.map(s => s.id),
                  owner_athlete_id: ownerId,
                  preview: false,
                  reason: 'שיוך מרוכז בספרייה'
                }
              });
              const targetLabel = targetAth?.label;
              for (const s of items) {
                if (list.some(x => x.id === s.id)) {
                  s.owner_athlete_id = ownerId;
                  s.owner_status = 'assigned';
                  s.owner_athlete_label = targetLabel;
                }
              }
              toast(`שויכו ${applied.updated_count} סרטונים ל-${targetLabel}`);
              render();
            } catch (err) { toast(err.message, true); }
          }
        }, 'אשר שיוך מרוכז'),
        h('button', { class: 'btn', onclick: closeDialog }, 'ביטול')
      ]);
    } catch (e) { toast(e.message, true); }
  }

  const sel = (opts, key) => h('select', { 'aria-label': key, onchange: e => { f[key] = e.target.value; render(); } }, opts.map(([v, l]) => h('option', { value: v }, l)));
  const next = items.find(s => s.annotation_status === 'not_annotated' && s.ingest_state === 'ready');

  root.append(h('div', { class: 'page' },
    h('h1', {}, 'ספריית סרטוני מקור'),
    h('div', { class: 'sub' }, 'זהות הסרטון קבועה (SHA-256), בלתי תלויה בנתיב או בשם הקובץ.'),
    backupBanner(bk),
    h('div', { style: { marginBottom: '10px' } }, backupPill(bk)),
    stats,
    h('div', { class: 'toolbar' },
      h('input', { type: 'search', placeholder: 'חיפוש שם / hash', 'aria-label': 'חיפוש', oninput: e => { f.q = e.target.value; render(); } }),
      sel([['', 'כל הסטטוסים'], ['not_annotated', 'לא סומן'], ['in_progress', 'בעבודה'], ['needs_review', 'דורש בדיקה'], ['approved', 'מאושר'], ['archive_error', 'שגיאת ארכיון']], 'status'),
      sel([['', 'כל הענפים'], ['unknown', 'לא מסווג'], ...sportsList().map(x => [x.id, x.name_he])], 'sport'),
      sel([['', 'כל הגולשים'], ['unassigned', 'ללא שיוך לגולש'], ...athletes.map(a => [a.id, a.label])], 'owner'),
      sel([['', 'כל האצוות'], ...batches.items.map(b => [b.label, `${b.label} (${b.sources})`])], 'batch'),
      h('button', { class: 'btn', 'aria-pressed': 'true', onclick: e => { f.view = f.view === 'grid' ? 'table' : 'grid'; e.target.textContent = f.view === 'grid' ? 'תצוגת טבלה' : 'תצוגת כרטיסים'; render(); } }, 'תצוגת טבלה'),
      h('span', { class: 'spacer' }),
      next ? h('a', { class: 'btn primary', href: `#/annotate/${next.id}`, 'data-testid': 'next-unannotated' }, 'הסרטון הבא ללא סימון ←') : null,
      h('button', { class: 'btn', onclick: async e => {
        e.target.disabled = true;
        try {
          const j = await api('/api/ingestion/reconcile', { method: 'POST', body: {} });
          let s; do { await new Promise(r => setTimeout(r, 300)); s = await api(`/api/jobs/${j.job_id}`); } while (s.state === 'running');
          toast(s.state === 'done' ? `סנכרון הושלם: ${s.report.ingested} חדשים, ${s.report.duplicates} כפולים, ${s.report.errors.length} שגיאות` : `נכשל: ${s.error}`, s.state !== 'done');
        } catch (x) { toast(x.message, true); }
        e.target.disabled = false;
      } }, 'סנכרון קליטה'),
      h('button', { class: 'btn', onclick: async e => {
        e.target.disabled = true;
        try {
          const r = await api('/api/archive/verify', { method: 'POST', body: {} });
          toast(`אימות ארכיון: ${r.ok}/${r.checked} תקינים`, r.failed.length > 0);
        } catch (x) { toast(x.message, true); }
        e.target.disabled = false;
      } }, 'אמת ארכיון')
    ),
    bulkBar,
    out
  ));
  render();
}
