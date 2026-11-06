import { h, api, ltr, pill, toast, fmtDate, fmtBytes, timecode, EVENT_HE, STATUS_HE, STATUS_CLASS, dialog, closeDialog, loadSports, sportName } from './ui.js';
import { setTopbar } from './main.js';

// ---------------- Athletes & Surfer Workspace (Precision Studio V2) ----------------
export async function renderAthletes(root) {
  setTopbar(h('strong', {}, 'ספריית גולשים (Surfer Workspace)'), pill('זהות פסבדונימית · ללא זיהוי פנים'));
  let search = '', selectedAthleteId = null, activeFilter = 'owner';

  const draw = async () => {
    const { items: athletes } = await api('/api/athletes');
    const filteredAthletes = search
      ? athletes.filter(a => a.label.toLowerCase().includes(search.toLowerCase()) || a.id.toLowerCase().includes(search.toLowerCase()))
      : athletes;

    if (!selectedAthleteId && filteredAthletes.length) {
      selectedAthleteId = filteredAthletes[0].id;
    }

    let athleteSourcesData = null;
    if (selectedAthleteId) {
      try {
        athleteSourcesData = await api(`/api/athletes/${selectedAthleteId}/sources?filter=${activeFilter}`);
      } catch (e) {
        console.error('Failed to load athlete sources:', e);
      }
    }

    const selAthlete = athletes.find(a => a.id === selectedAthleteId);
    const lineage = await api('/api/person-lineage').catch(() => ({ relations: [], mapping: [] }));

    // Addendum §6: identity merge/split is a revisioned, append-only relation — never an edit of history.
    const nameOf = id => athletes.find(a => a.id === id)?.label ?? id.slice(0, 8);
    const REL_HE = { merge: 'מיזוג (אותו אדם)', split: 'פיצול (שני אנשים)', equivalent: 'שקילות', retire: 'הוצאה משימוש' };
    const lineagePanel = h('details', { class: 'section', 'data-testid': 'person-lineage', style: { marginTop: '18px' } },
      h('summary', {}, `מיזוג / פיצול זהויות (${lineage.relations.length} קשרים)`),
      h('div', { class: 'meta' }, 'מיזוג: כמה תוויות → גולש אחד. פיצול: תווית אחת → כמה גולשים (קשר לכל יורש). ההיסטוריה נשמרת ודאטהסטים קפואים ממשיכים להשתמש במיפוי שהיה בזמן ההקפאה.'),
      h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center', margin: '8px 0' } },
        h('select', { id: 'lin-type', 'data-testid': 'lin-type' }, Object.entries(REL_HE).map(([k, l]) => h('option', { value: k }, l))),
        h('select', { id: 'lin-from', 'data-testid': 'lin-from' }, athletes.map(a => h('option', { value: a.id }, a.label))), '→',
        h('select', { id: 'lin-to', 'data-testid': 'lin-to' }, h('option', { value: '' }, '—'), athletes.map(a => h('option', { value: a.id }, a.label))),
        h('input', { type: 'text', id: 'lin-reason', 'data-testid': 'lin-reason', placeholder: 'סיבה (חובה)' }),
        h('button', { class: 'btn sm', 'data-testid': 'lin-add', onclick: async () => {
          const v = n => root.querySelector(`#${n}`).value;
          if (v('lin-type') !== 'retire' && !v('lin-to')) return toast('בחר יורש', true);
          if (!confirm('קשר זהויות נרשם לצמיתות (אפשר רק להוסיף קשרים חדשים). להמשיך?')) return;
          try { await api('/api/person-lineage', { method: 'POST', body: { relation_type: v('lin-type'), from_person_id: v('lin-from'), to_person_id: v('lin-to') || null, reason_code: v('lin-reason') } }); toast('נרשם'); draw(); } catch (e) { toast(e.message, true); }
        } }, 'רשום קשר')),
      h('ul', { class: 'list' }, lineage.relations.map(r => h('li', {}, pill(REL_HE[r.relation_type], 'warn'), h('span', { style: { flex: 1 } }, `${nameOf(r.from_person_id)}${r.to_person_id ? ` → ${nameOf(r.to_person_id)}` : ''} · ${r.reason_code}`), h('span', { class: 'meta ltr' }, fmtDate(r.created_at))))));
    root.replaceChildren(h('div', { class: 'page', 'data-testid': 'surfer-workspace' },
      h('h1', {}, 'ספריית גולשים (Surfer Workspace)'),
      h('div', { class: 'sub' }, 'שיוך סרטונים לגולש מתבצע כחלק מהקטלוג העצמאי, ללא תלות בקיומם של אירועים או תיבות. סרטון יכול להיות שייך לגולש גם אם טרם סומן בו אירוע.'),
      h('div', { class: 'toolbar' },
        h('input', {
          type: 'search',
          id: 'search-athlete',
          placeholder: 'חיפוש גולש...',
          value: search,
          'aria-label': 'חיפוש גולש',
          style: { maxWidth: '240px' },
          oninput: e => { search = e.target.value; draw(); }
        }),
        h('input', { type: 'text', id: 'newath', placeholder: 'תווית לגולש חדש (למשל: גולש 1)', style: { maxWidth: '260px' }, 'aria-label': 'תווית גולש חדש' }),
        h('button', {
          class: 'btn primary',
          'data-testid': 'add-athlete',
          onclick: async () => {
            const v = root.querySelector('#newath').value;
            if (!v || !v.trim()) return toast('חובה להזין שם או תווית לגולש', true);
            try {
              const created = await api('/api/athletes', { method: 'POST', body: { label: v.trim() } });
              selectedAthleteId = created.id;
              root.querySelector('#newath').value = '';
              toast(`הגולש "${created.label}" נוצר בהצלחה`);
              await draw();
            } catch (e) { toast(e.message, true); }
          }
        }, '＋ הוסף גולש חדש')
      ),

      athletes.length ? h('div', { style: { display: 'grid', gridTemplateColumns: '320px 1fr', gap: '20px', alignItems: 'start' } },
        // Left column: list of surfers
        h('div', { class: 'panel', style: { background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 'var(--radius)', padding: '14px' } },
          h('h3', { style: { marginTop: 0, fontSize: '15px', color: 'var(--text)' } }, `גולשים (${athletes.length})`),
          h('div', { class: 'list', style: { maxHeight: '65vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' } },
            filteredAthletes.map(a => h('div', {
              class: 'card',
              'data-testid': 'athlete-item',
              style: {
                padding: '10px',
                cursor: 'pointer',
                border: a.id === selectedAthleteId ? '2px solid var(--accent)' : '1px solid var(--line)',
                background: a.id === selectedAthleteId ? 'var(--panel2)' : 'var(--panel)',
              },
              onclick: () => { selectedAthleteId = a.id; draw(); }
            },
              h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between' } },
                h('strong', { style: { fontSize: '14px', color: 'var(--text)' } }, a.label),
                a.id === selectedAthleteId ? pill('נבחר', 'ok') : null
              ),
              h('div', { class: 'meta', style: { marginTop: '6px', fontSize: '11px', display: 'flex', gap: '8px', flexWrap: 'wrap' } },
                pill(`${a.assigned_sources_count ?? 0} סרטונים משויכים`, a.assigned_sources_count ? 'ok' : ''),
                pill(`${a.appearances?.length ?? 0} הופעות`, '')
              ),
              h('div', { class: 'meta ltr mono', style: { fontSize: '10px', marginTop: '4px', color: 'var(--muted)' } }, a.id.slice(0, 8))
            ))
          )
        ),

        // Right column: Surfer detail workspace
        selAthlete ? h('div', { class: 'panel', style: { background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 'var(--radius)', padding: '16px' } },
          h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--line)', paddingBottom: '12px', marginBottom: '14px' } },
            h('div', {},
              h('h2', { style: { margin: 0, fontSize: '18px', color: 'var(--text)' } }, `ספריית סרטונים: ${selAthlete.label}`),
              h('div', { class: 'meta ltr mono', style: { marginTop: '4px', color: 'var(--muted)' } }, `UUID: ${selAthlete.id}`)
            ),
            h('div', { style: { display: 'flex', gap: '8px' } },
              h('input', {
                type: 'text',
                value: selAthlete.label,
                style: { maxWidth: '160px' },
                'aria-label': 'עריכת שם גולש',
                onchange: async e => {
                  try {
                    await api(`/api/athletes/${selAthlete.id}`, { method: 'PATCH', body: { label: e.target.value.trim() } });
                    toast('שם הגולש עודכן');
                    await draw();
                  } catch (err) { toast(err.message, true); }
                }
              })
            )
          ),

          // Surfer Stats Bar
          h('div', { class: 'stats', style: { marginBottom: '16px' } },
            h('div', { class: 'stat' }, h('b', {}, athleteSourcesData?.totals?.owned_sources ?? 0), h('span', {}, 'סרטונים משויכים (בעלים)')),
            h('div', { class: 'stat' }, h('b', {}, athleteSourcesData?.totals?.appearance_sources ?? 0), h('span', {}, 'סרטונים שמופיע בהם')),
            h('div', { class: 'stat' }, h('b', {}, (athleteSourcesData?.items || []).reduce((acc, s) => acc + (s.events_count || 0), 0)), h('span', {}, 'אירועים שבוצעו')),
            h('div', { class: 'stat' }, h('b', {}, (athleteSourcesData?.items || []).reduce((acc, s) => acc + (s.track_qa_count || 0), 0)), h('span', {}, 'נקודות מעקב שאומתו'))
          ),

          // Filter tabs
          h('div', { class: 'toolbar', style: { marginBottom: '16px' } },
            h('button', {
              class: `btn ${activeFilter === 'owner' ? 'primary' : ''}`,
              'data-testid': 'tab-owner-sources',
              onclick: () => { activeFilter = 'owner'; draw(); }
            }, `סרטונים משויכים (${athleteSourcesData?.totals?.owned_sources ?? 0})`),
            h('button', {
              class: `btn ${activeFilter === 'appearance' ? 'primary' : ''}`,
              'data-testid': 'tab-appearance-sources',
              onclick: () => { activeFilter = 'appearance'; draw(); }
            }, `סרטונים שבהם הגולש מופיע (${athleteSourcesData?.totals?.appearance_sources ?? 0})`),
            h('button', {
              class: `btn ${activeFilter === 'all' ? 'primary' : ''}`,
              'data-testid': 'tab-all-sources',
              onclick: () => { activeFilter = 'all'; draw(); }
            }, `הכול (${athleteSourcesData?.totals?.total_unique_sources ?? 0})`)
          ),

          // Video list for this athlete
          athleteSourcesData?.items?.length ? h('div', { class: 'grid', style: { gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '14px' } },
            athleteSourcesData.items.map(s => h('div', { class: 'card', 'data-testid': 'surfer-video-card' },
              h('div', { class: 'thumb', style: s.thumb_path ? { backgroundImage: `url(/media/${s.id}/thumb)` } : {} },
                s.thumb_path ? null : 'אין תמונה',
                h('span', { class: 'tag' }, s.is_owner ? pill('בעלים', 'ok') : pill('מופיע בסרטון', 'warn'))
              ),
              h('div', { class: 'body' },
                h('div', { class: 'name', title: s.display_name }, s.display_name),
                h('div', { class: 'meta' },
                  s.duration_ms ? ltr(timecode(Math.round(s.duration_ms / 1000 * 30), 30)) : '—',
                  s.byte_size ? ltr(fmtBytes(s.byte_size)) : null,
                  sportName(s.primary_sport_id)
                ),
                h('div', { class: 'meta', style: { gap: '6px' } },
                  pill(`${s.events_count} אירועים`, s.events_count > 0 ? 'ok' : ''),
                  pill(`${s.track_qa_count} אומתו`, s.track_qa_count > 0 ? 'ok' : '')
                ),
                h('a', { class: 'btn primary sm', href: `#/annotate/${s.id}`, 'data-testid': 'open-workbench-btn' }, 'פתח ב-Workbench ←')
              )
            ))
          ) : h('div', { class: 'empty', 'data-testid': 'no-surfer-videos' },
            activeFilter === 'owner'
              ? 'טרם שויכו סרטונים לגולש זה. עבור לספרייה או לקטלוג הענן ולחץ על "שייך לגולש".'
              : 'אין סרטונים להצגה בסינון זה.'
          )
        ) : h('div', { class: 'empty' }, 'בחר גולש מהרשימה')
      ) : h('div', { class: 'empty' }, 'אין גולשים עדיין. הזן תווית ולחץ "הוסף גולש חדש".')
    ));
    root.firstChild?.append(lineagePanel);
  };

  await draw();
}

// ---------------- Datasets ----------------
export async function renderDatasets(root) {
  setTopbar(h('strong', {}, 'ניהול דאטהסטים'), pill('גרסאות קפואות'));
  const [ds, src] = await Promise.all([api('/api/datasets'), api('/api/sources?limit=200&status=approved')]);
  const checks = new Map();
  // Leak-free by default (operator, 2026-11-06): every athlete in one split, whole recording days held out as the test set,
  // so the pipeline is never judged on people or footage it trained on.
  const sessions = [...new Set(src.items.map(s => s.session_key).filter(Boolean))].sort();
  const testDays = new Map(sessions.map((d, i) => [d, h('input', { type: 'checkbox', 'data-testid': `test-day-${d}`, checked: i === sessions.length - 1 && sessions.length > 1 })]));
  const method = h('select', { id: 'ds-method', 'data-testid': 'split-method' },
    h('option', { value: 'athlete', selected: true }, 'לפי גולש, בלי דליפה (מומלץ)'), h('option', { value: 'session' }, 'לפי יום צילום (ישן)'));
  const allBox = h('input', { type: 'checkbox', 'data-testid': 'select-all', onchange: e => { for (const c of checks.values()) c.checked = e.target.checked; } });
  const freeze = async () => {
    const ids = [...checks].filter(([, c]) => c.checked).map(([id]) => id);
    const policy = { seed: 'sportreel-v1', ratios: { train: 0.7, validation: 0.15, test: 0.15 } };
    if (method.value === 'athlete') { policy.group_by = 'athlete'; policy.test_sessions = [...testDays].filter(([, c]) => c.checked).map(([d]) => d); }
    const days = policy.test_sessions?.length ? ` ימי הבדיקה (${policy.test_sessions.join(', ')}) יישמרו לבדיקה בלבד, לתמיד.` : '';
    if (!confirm(`לקפוא ${ids.length} סרטונים?${days}`)) return;
    try { await api('/api/datasets', { method: 'POST', body: { name: root.querySelector('#dsname').value, source_ids: ids, policy } }); toast('הדאטהסט נקפא'); renderDatasets(root); } catch (e) { toast(e.message, true); }
  };
  root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'דאטהסטים'), h('div', { class: 'sub' }, 'קפיאה נועלת (sha256 + גרסה מאושרת) לכל סרטון. חלוקה לפי גולש: כל גולש כולו באימון, בוולידציה או בבדיקה, ויום צילום שלם נשמר לבדיקה. קבוצת המבחן קבועה ולא ניתנת להזזה.'),
    h('h2', { style: { fontSize: '15px' } }, 'קפיאת דאטהסט חדש'),
    src.items.length ? h('div', {}, h('div', { class: 'toolbar' }, h('input', { type: 'text', id: 'dsname', placeholder: 'שם הדאטהסט', style: { maxWidth: '240px' }, 'aria-label': 'שם דאטהסט' }),
      method, sessions.length ? h('span', { class: 'meta' }, 'ימי בדיקה: ', ...sessions.flatMap(d => [h('label', {}, testDays.get(d), ' ', ltr(d)), ' '])) : null,
      h('button', { class: 'btn primary', 'data-testid': 'freeze', onclick: freeze }, 'קפא דאטהסט')),
      h('label', { class: 'meta' }, allBox, ' בחר הכול'),
      h('ul', { class: 'list' }, src.items.map(s => { const c = h('input', { type: 'checkbox', 'aria-label': s.display_name }); checks.set(s.id, c); return h('li', {}, c, ltr(s.display_name), pill(`v${s.revision_seq}`, 'ok'), s.session_key ? pill(s.session_key) : null, s.owner_athlete_label ? pill(s.owner_athlete_label) : null); }))) : h('div', { class: 'empty' }, 'אין סרטונים עם גרסה מאושרת לקפיאה'),
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
const ERR_HE = { missed: 'אירוע שהוחמץ', missed_event: 'אירוע שהוחמץ', wrong_attribution: 'גולש שגוי', unreviewed_prediction: 'חיזוי באזור שלא נבדק', uncertain_overlap: 'חפיפה עם אירוע לא בטוח', false_positive: 'תוצאה שגויה (FP)', duplicate: 'פלט כפול', wrong_athlete: 'גולש שגוי', predicted_excluded: 'חזה אירוע מוחרג' };
// Restored pre-V2 report (reads the evaluator's real per_source/by_sport output; the V2 rewrite read a non-existent field).
async function renderEvalDetail(root, id) {
  const { report: r, digest } = await api(`/api/evaluations/${id}`);
  const m = r.metrics, t = r.totals;
  root.replaceChildren(h('div', { class: 'page' }, h('a', { href: '#/evaluations', class: 'btn sm' }, '→ חזרה'),
    h('h1', { style: { marginTop: '10px' } }, 'דוח הערכה'), h('div', { class: 'sub' }, ltr(`${r.pipeline_version} · ${r.run_id}`), ' · ', ltr(`evaluator ${r.evaluator_version}`), ' · digest ', ltr(digest.slice(0, 12))),
    h('div', { class: 'stats' }, [['Recall', pct(m.event_recall)], ['Precision', pct(m.event_precision)], ['דיוק זהות', pct(m.identity_accuracy)], ['חסרים', t.missed], ['כפולים', t.duplicates], ['FP', t.false_positives], ['לא נבדק', t.unreviewed_predictions], ['שגיאת התחלה ממוצעת (פריימים)', m.mean_abs_start_error_frames == null ? '—' : m.mean_abs_start_error_frames.toFixed(1)]].map(([l, v]) => h('div', { class: 'stat' }, h('b', {}, v), h('span', {}, l)))),
    r.by_sport && Object.keys(r.by_sport).length ? h('div', {}, h('h3', { style: { fontSize: '14px' } }, 'לפי ענף ספורט (ללא התאמה בין ענפים)'),
      h('table', { class: 't', 'data-testid': 'by-sport' }, h('thead', {}, h('tr', {}, ['ענף', 'GT', 'תחזיות', 'הותאמו', 'הוחמצו', 'FP', 'recall', 'precision'].map(x => h('th', {}, x)))),
        h('tbody', {}, Object.entries(r.by_sport).map(([sp, c]) => h('tr', { 'data-sport': sp }, h('td', {}, sp === 'unknown' ? 'לא מסווג' : sp === 'unspecified' ? 'תחזית ללא ענף' : sportName(sp)), h('td', {}, c.gt_included), h('td', {}, c.predictions), h('td', {}, c.matched), h('td', {}, c.missed), h('td', {}, c.false_positives), h('td', {}, pct(c.event_recall)), h('td', {}, pct(c.event_precision))))))) : null,
    h('div', { class: 'legend' }, `IoU ≥ ${r.params.iou_threshold} · פיצולים: ${r.params.splits.join(', ')} · שיוך גולשים לפי מיפוי התאמות דטרמיניסטי`),
    h('div', { 'data-testid': 'error-review' }, h('div', { class: 'empty' }, 'טוען סקירת טעויות…')),
    h('h2', { style: { fontSize: '15px', marginTop: '22px' } }, 'פירוט טכני לפי מקור'),
    r.per_source.map(p => h('div', { style: { marginBottom: '18px' } }, h('h3', { style: { fontSize: '14px' } }, ltr(p.sha256.slice(0, 12)), ' · ', p.split, p.has_prediction ? '' : ' · אין תחזית למקור זה'),
      p.errors.length ? h('table', { class: 't', 'data-testid': 'eval-errors' }, h('thead', {}, h('tr', {}, ['סוג', 'פריימים', 'מקטע/תחזית'].map(x => h('th', {}, x)))), h('tbody', {}, p.errors.map(e => h('tr', {}, h('td', {}, pill(ERR_HE[e.type] ?? e.type, e.type === 'missed_event' || e.type === 'wrong_athlete' ? 'bad' : 'warn')), h('td', {}, ltr(`${e.start_frame}–${e.end_frame}`)), h('td', {}, ltr(e.segment_id ?? `pred#${e.pred_index}`)))))) : h('div', { class: 'banner warn', style: { color: 'var(--inc)' } }, 'אין שגיאות לסרטון זה')))));
  renderErrorReview(root.querySelector('[data-testid=error-review]'), id);
}

const REVIEW_CAT = {
  selection_wrong_use: ['השתמש ולא היה צריך', 'קטעים שהפייפליין בחר אבל לפי האמת אין בהם גל, הם מוחרגים או כפולים'],
  selection_missed: ['לא השתמש והיה צריך', 'גלים מתויגים שלא נבחרו — נפסלו, לא זוהו בכלל, או נחתכו רחוק מדי'],
  identity: ['זיהוי גולשים', 'שיוך גל לגולש, ועקביות הזהות לאורך כל הריצה'],
  assembly: ['שילוב קליפים', 'איזה גלים נכנסו לאיזה סרטון פלט'],
  trim: ['עריכה וחיתוך', 'תחילת וסוף החיתוך מול הגל המתויג (הקמה / סיום)'],
  framing: ['מרכוז ופריימינג', 'הגולש בתוך החיתוך בפלט, מרכוז וקפיצות — הבוקסים הם הכוונה, לא אמת מוחלטת'],
};
const SEV = { bad: ['טעות', 'bad'], warn: ['אזהרה', 'warn'], info: ['מידע', ''] };
const mmss = s => s == null ? '' : `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
async function renderErrorReview(box, id) {
  let rv;
  try { rv = await api(`/api/evaluations/${id}/review`); } catch (e) { box.replaceChildren(h('div', { class: 'banner warn' }, `סקירת הטעויות לא נטענה: ${e.message}`)); return; }
  const s = rv.summary, by = c => rv.items.filter(i => i.category === c);
  const row = i => h('tr', { 'data-type': i.type, 'data-severity': i.severity },
    h('td', {}, pill(SEV[i.severity][0], SEV[i.severity][1])),
    h('td', {}, i.video ? (i.video.source_id ? h('a', { href: `#/annotate/${i.video.source_id}${i.start_frame != null ? `?f=${i.start_frame}` : ''}`, 'data-testid': 'review-jump' }, ltr(i.video.name)) : ltr(i.video.name)) : '—'),
    h('td', {}, i.start_sec != null ? ltr(`${mmss(i.start_sec)}–${mmss(i.end_sec)}`) : ''),
    h('td', {}, i.athlete?.label ?? ''),
    h('td', {}, i.explain_he));
  const section = c => { const its = by(c); const bad = its.filter(i => i.severity === 'bad').length;
    return h('details', { class: 'card', open: bad > 0, 'data-testid': `review-${c}`, style: { marginBottom: '10px' } },
      h('summary', { style: { padding: '10px', cursor: 'pointer' } }, h('strong', {}, REVIEW_CAT[c][0]), ' ', pill(`${its.length}`, bad ? 'bad' : its.length ? 'warn' : ''), h('span', { class: 'meta' }, ` · ${REVIEW_CAT[c][1]}`)),
      h('div', { class: 'body' }, its.length ? h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['חומרה', 'סרטון', 'זמן', 'גולש', 'מה קרה'].map(x => h('th', {}, x)))), h('tbody', {}, its.map(row)))
        : h('div', { class: 'meta' }, 'לא נמצאו בעיות בקטגוריה הזו'),
        c === 'identity' && rv.identity_map.length ? h('table', { class: 't', 'data-testid': 'identity-map', style: { marginTop: '8px' } }, h('thead', {}, h('tr', {}, ['זהות בפייפליין', 'מופתה ל', 'בפועל הופיעו'].map(x => h('th', {}, x)))),
          h('tbody', {}, rv.identity_map.map(m => h('tr', {}, h('td', {}, ltr(m.pipeline_athlete_key)), h('td', {}, m.mapped_to?.label ?? '—'), h('td', {}, m.seen_as.map(a => `${a.label} (${a.events})`).join(', ')))))) : null,
        c === 'assembly' && rv.outputs.length ? h('table', { class: 't', 'data-testid': 'outputs-table', style: { marginTop: '8px' } }, h('thead', {}, h('tr', {}, ['סרטון פלט', 'גלים', 'גולשים'].map(x => h('th', {}, x)))),
          h('tbody', {}, rv.outputs.map(o => h('tr', {}, h('td', {}, ltr(o.output_id)), h('td', {}, o.events), h('td', {}, o.athletes.map(a => `${a.label} (${a.events})`).join(', ') || '—'))))) : null,
        c === 'framing' ? h('div', { class: 'meta', style: { marginTop: '6px' } }, rv.framing.length ? `נבדקו ${s.framing_outputs_evaluated} מתוך ${rv.framing.length} סרטוני פלט (רק פלטים שכל הקליפים שלהם מסרטוני ההערכה). מרכוז ללא יעד שהוגדר בתיוג נמדד מול מרכז הפריים — לאבחון בלבד.` : 'לא יובאו קובצי EDL של הריצה הזו — אי אפשר לבדוק מרכוז. ייבא EDL ב"בקרת עריכה".') : null));
  };
  box.replaceChildren(h('h2', { style: { fontSize: '15px', marginTop: '18px' } }, 'סקירת טעויות — כל הבחירות של הפייפליין מול האמת'),
    h('div', { class: 'sub' }, `${s.videos} סרטונים (${rv.splits.join(', ')}) · ${s.gt_events} גלים מתויגים · ${s.matched} נמצאו, מתוכם ${s.matched_without_issue} בלי שום הערה`),
    h('div', { class: 'stats', 'data-testid': 'review-summary' }, [['השתמש ולא היה צריך', s.used_wrongly], ['לא השתמש והיה צריך', s.missed], ['· נפסלו', s.missed_rejected], ['· לא זוהו', s.missed_never_detected], ['זיהוי גולשים', s.identity_issues], ['שילוב קליפים', s.assembly_issues], ['חיתוך', s.trim_issues], ['מרכוז', s.framing_issues]]
      .map(([l, v]) => h('div', { class: 'stat' }, h('b', {}, v), h('span', {}, l)))),
    ...Object.keys(REVIEW_CAT).map(section));
}

// ---------------- Settings ----------------
// Restored from the pre-V2 Studio (spec §18): adding sports/event types and enabling/disabling them needs no code change.
export async function renderSettings(root) {
  setTopbar(h('strong', {}, 'הגדרות ענפי ספורט'), pill('טקסונומיה מגורסת · ללא מחיקה'));
  const draw = async () => {
    const sports = await loadSports();
    const val = id => root.querySelector(`#${id}`).value.trim();
    const act = async (fn, okMsg) => { try { await fn(); toast(okMsg); await draw(); } catch (e) { toast(e.message, true); } };
    root.replaceChildren(h('div', { class: 'page' }, h('h1', {}, 'ענפי ספורט וסוגי אירועים'),
      h('div', { class: 'sub' }, 'ענפים וסוגי אירועים הם נתונים, לא קוד: הוספה נרשמת ביומן ומעלה את גרסת הטקסונומיה. הסרת סוג אירוע (השבתה) לא פוסלת תיוגים קיימים.'),
      h('h2', { style: { fontSize: '15px' } }, 'ענף חדש'),
      h('div', { class: 'toolbar' },
        h('input', { id: 'ns-id', type: 'text', placeholder: 'מזהה (a-z, למשל volleyball)', 'aria-label': 'מזהה ענף', style: { direction: 'ltr', maxWidth: '200px' } }),
        h('input', { id: 'ns-he', type: 'text', placeholder: 'שם בעברית', 'aria-label': 'שם ענף בעברית', style: { maxWidth: '160px' } }),
        h('input', { id: 'ns-en', type: 'text', placeholder: 'English name', 'aria-label': 'שם ענף באנגלית', style: { direction: 'ltr', maxWidth: '160px' } }),
        h('button', { class: 'btn primary', 'data-testid': 'add-sport', onclick: () => act(() => api('/api/sports', { method: 'POST', body: { id: val('ns-id'), name_he: val('ns-he'), name_en: val('ns-en') } }), 'הענף נוסף') }, 'הוסף ענף')),
      sports.map(sp => h('div', { class: 'card', 'data-testid': 'sport-card', 'data-sport': sp.id, style: { marginBottom: '14px' } }, h('div', { class: 'body' },
        h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } }, h('strong', {}, sp.name_he), ltr(sp.id), pill(`טקסונומיה v${sp.taxonomy_version}`),
          h('label', { class: 'meta' }, h('input', { type: 'checkbox', checked: sp.enabled, onchange: e => act(() => api(`/api/sports/${sp.id}`, { method: 'PATCH', body: { enabled: e.target.checked } }), 'עודכן') }), ' פעיל')),
        h('ul', { class: 'list' }, sp.event_types.map(t => h('li', { 'data-event': t.key }, ltr(t.key), h('span', { style: { flex: 1 } }, t.label_he, t.required_attrs.length ? ` · חובה: ${t.required_attrs.join(', ')}` : ''),
          h('label', { class: 'meta' }, h('input', { type: 'checkbox', checked: t.enabled, 'aria-label': `פעיל ${t.key}`, onchange: e => act(() => api(`/api/sports/${sp.id}/event-types/${t.key}`, { method: 'PATCH', body: { enabled: e.target.checked } }), 'עודכן') }), ' פעיל')))),
        h('div', { class: 'toolbar' },
          h('input', { id: `et-key-${sp.id}`, type: 'text', placeholder: 'מפתח אירוע', 'aria-label': `מפתח אירוע חדש ל-${sp.id}`, style: { direction: 'ltr', maxWidth: '150px' } }),
          h('input', { id: `et-he-${sp.id}`, type: 'text', placeholder: 'תווית בעברית', 'aria-label': `תווית עברית ל-${sp.id}`, style: { maxWidth: '150px' } }),
          h('input', { id: `et-en-${sp.id}`, type: 'text', placeholder: 'English label', 'aria-label': `תווית אנגלית ל-${sp.id}`, style: { direction: 'ltr', maxWidth: '150px' } }),
          h('input', { id: `et-req-${sp.id}`, type: 'text', placeholder: 'שדות חובה (פסיקים)', 'aria-label': `שדות חובה ל-${sp.id}`, style: { direction: 'ltr', maxWidth: '170px' } }),
          h('button', { class: 'btn', 'data-testid': `add-event-${sp.id}`, onclick: () => act(() => api(`/api/sports/${sp.id}/event-types`, { method: 'POST', body: { key: val(`et-key-${sp.id}`), label_he: val(`et-he-${sp.id}`), label_en: val(`et-en-${sp.id}`), required_attrs: val(`et-req-${sp.id}`).split(',').map(x => x.trim()).filter(Boolean) } }), 'סוג האירוע נוסף') }, 'הוסף סוג אירוע')))))));
  };
  await draw();
}

// ---------------- Independent annotation sets, agreement and adjudication (addendum §2, §8, §9) ----------------
const PURPOSE_HE = { primary: 'ראשי (Ground Truth)', delayed_blind_reannotation: 'תיוג חוזר עיוור', independent_qa: 'בקרת איכות עצמאית', adjudication: 'הכרעה' };
const SET_STATUS_HE = { draft: 'טיוטה', active: 'פעיל', submitted: 'הוגש (נעול)', adjudicating: 'בהכרעה', accepted: 'הכרעה התקבלה', archived: 'בארכיון' };
export async function renderSets(root) {
  setTopbar(h('strong', {}, 'סטים עצמאיים, הסכמה והכרעה'));
  const [sets, sources] = await Promise.all([api('/api/sets'), api('/api/sources?limit=500')]);
  const closed = sets.items.filter(s => s.id === 'primary' || ['submitted', 'accepted', 'archived'].includes(s.status));
  const purpose = h('select', { id: 'set-purpose', 'data-testid': 'set-purpose' }, ['delayed_blind_reannotation', 'independent_qa', 'adjudication'].map(p => h('option', { value: p }, PURPOSE_HE[p])));
  const annot = h('input', { type: 'text', id: 'set-annotator', 'data-testid': 'set-annotator', placeholder: 'מזהה מתייג פסאודונימי (למשל ann-2)' });
  const contrib = h('select', { id: 'set-contrib', multiple: true, 'aria-label': 'סטים תורמים להכרעה', style: { minHeight: '60px' } }, closed.map(s => h('option', { value: s.id }, `${PURPOSE_HE[s.purpose]} · ${s.id.slice(0, 8)}`)));
  const report = h('div', { 'data-testid': 'agreement-report' });
  const pickA = h('select', { id: 'agree-a' }, closed.map(s => h('option', { value: s.id }, `${PURPOSE_HE[s.purpose]} · ${s.id.slice(0, 8)}`)));
  const pickB = h('select', { id: 'agree-b' }, closed.map((s, i) => h('option', { value: s.id, selected: i === 1 }, `${PURPOSE_HE[s.purpose]} · ${s.id.slice(0, 8)}`)));
  const pct = v => (v == null ? '—' : `${Math.round(v * 100)}%`);
  root.replaceChildren(h('div', { class: 'page' },
    h('h1', {}, 'סטים עצמאיים'),
    h('div', { class: 'sub' }, 'כל סט הוא זרם תיוג נפרד: טיוטה, מיקום וגרסאות משלו. סט חדש מתחיל ריק ואינו רואה עבודה של סטים אחרים עד שהוא מוגש. הכרעה נעשית בסט נפרד ואינה משנה את הסטים התורמים.'),
    h('table', { class: 't', 'data-testid': 'sets-table' }, h('thead', {}, h('tr', {}, ['מטרה', 'מזהה', 'מתייג', 'מצב', 'שיוכים', ''].map(x => h('th', {}, x)))),
      h('tbody', {}, sets.items.map(s => h('tr', { 'data-set': s.id }, h('td', {}, PURPOSE_HE[s.purpose]), h('td', {}, ltr(s.id.slice(0, 8))), h('td', {}, s.annotator_id), h('td', {}, pill(SET_STATUS_HE[s.status] ?? s.status, ['submitted', 'accepted'].includes(s.status) ? 'ok' : 'warn')),
        h('td', {}, s.assignments ? s.assignments.map(a => `${a.queue_status}: ${a.n}`).join(' · ') || '0' : '—'),
        h('td', {}, s.id === 'primary' ? '' : h('div', { style: { display: 'flex', gap: '6px' } },
          ['active', 'adjudicating'].includes(s.status) ? h('button', { class: 'btn sm', 'data-testid': 'set-open', onclick: () => openSet(s) }, 'פתח') : null,
          ['active', 'adjudicating'].includes(s.status) ? h('button', { class: 'btn sm', 'data-testid': 'set-submit', onclick: async () => { try { await api(`/api/sets/${s.id}/submit`, { method: 'POST', body: {} }); toast('הסט הוגש וננעל'); renderSets(root); } catch (e) { toast(e.message, true); } } }, 'הגש סט') : null)))))),
    h('h2', { style: { fontSize: '15px' } }, 'סט חדש'),
    h('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' } }, purpose, annot, contrib,
      h('button', { class: 'btn primary', 'data-testid': 'set-create', onclick: async () => {
        try { await api('/api/sets', { method: 'POST', body: { purpose: purpose.value, annotator_id: annot.value, contributing_set_ids: purpose.value === 'adjudication' ? [...contrib.selectedOptions].map(o => o.value) : [] } }); toast('נוצר סט'); renderSets(root); } catch (e) { toast(e.message, true); }
      } }, 'צור סט')),
    h('h2', { style: { fontSize: '15px' } }, 'דוח הסכמה (רק בין סטים שהוגשו)'),
    h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } }, pickA, 'מול', pickB,
      h('button', { class: 'btn', 'data-testid': 'agreement-run', onclick: async () => {
        try {
          const r = await api(`/api/agreement?a=${pickA.value}&b=${pickB.value}`);
          report.replaceChildren(h('div', { class: 'meta' }, `${r.sources} מקורות משותפים · אי-הסכמות חוסמות: ${r.blocking_total} · התאמה ${r.matching_version} · דיג׳סט `, ltr(r.digest.slice(0, 12))),
            h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['מקור', 'הותאמו', 'רק A', 'רק B', 'החלטה', 'שימושיות', 'Jaccard סיבות', 'זהות (זוגות)', 'חוסם'].map(x => h('th', {}, x)))),
              h('tbody', {}, r.per_source.map(p => h('tr', {}, h('td', {}, ltr(p.source_id.slice(0, 8))), h('td', {}, p.matched), h('td', {}, p.only_a?.length ?? 0), h('td', {}, p.only_b?.length ?? 0),
                h('td', {}, pct(p.decision_agreement)), h('td', {}, pct(p.usability_agreement)), h('td', {}, pct(p.reason_jaccard_mean)), h('td', {}, pct(p.identity_pair_agreement)),
                h('td', {}, p.blocking_disagreements?.length ? pill(String(p.blocking_disagreements.length), 'bad') : pill('0', 'ok')))))));
        } catch (e) { toast(e.message, true); }
      } }, 'הפק דוח')),
    report));
  function openSet(s) {
    const pick = h('select', { multiple: true, 'aria-label': 'מקורות לשיוך', style: { minHeight: '120px', width: '100%' } }, sources.items.map(x => h('option', { value: x.id }, x.display_name)));
    dialog(`סט ${PURPOSE_HE[s.purpose]}`, h('div', {},
      h('label', { class: 'f' }, 'הוסף מקורות לסט (יתחילו ריקים):'), pick,
      h('div', { style: { marginTop: '8px' } }, h('button', { class: 'btn sm', 'data-testid': 'set-add-sources', onclick: async () => { try { await api(`/api/sets/${s.id}/assignments`, { method: 'POST', body: { source_ids: [...pick.selectedOptions].map(o => o.value) } }); toast('נוספו'); closeDialog(); renderSets(root); } catch (e) { toast(e.message, true); } } }, 'הוסף')),
      h('p', { class: 'meta' }, 'לעבודה על מקור בסט: '), h('ul', { class: 'list' }, sources.items.map(x => h('li', {}, h('a', { href: `#/annotate/${x.id}?set=${s.id}` }, x.display_name))))),
    [h('button', { class: 'btn', onclick: closeDialog }, 'סגור')]);
  }
}
