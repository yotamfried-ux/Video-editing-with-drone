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
  const e = await api(`/api/evaluations/${id}`);
  const r = e.report;
  root.replaceChildren(h('div', { class: 'page' }, h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } }, h('a', { class: 'btn sm', href: '#/evaluations' }, '→ חזרה לרשימה'), h('h1', { style: { margin: 0 } }, `דוח הערכה · ${r.pipeline_version}`)),
    h('div', { class: 'sub' }, `ריצה ${ltr(r.run_id)} מול דאטהסט "${r.dataset_name}" (נוצר ${fmtDate(r.created_at)}) · דיג׳סט ${ltr(e.digest.slice(0, 12))}`),
    h('div', { class: 'stats' },
      h('div', { class: 'stat' }, h('b', {}, pct(r.metrics.event_recall)), h('span', {}, 'Event Recall')),
      h('div', { class: 'stat' }, h('b', {}, pct(r.metrics.event_precision)), h('span', {}, 'Event Precision')),
      h('div', { class: 'stat' }, h('b', {}, pct(r.metrics.identity_accuracy)), h('span', {}, 'Identity Accuracy')),
      h('div', { class: 'stat' }, h('b', {}, pct(r.metrics.temporal_iou_mean)), h('span', {}, 'Mean IoU')),
      h('div', { class: 'stat' }, h('b', {}, pct(r.metrics.box_iou_mean)), h('span', {}, 'Mean Box IoU'))),
    h('h2', { style: { fontSize: '15px' } }, 'פירוט שגיאות ואי-התאמות'),
    r.discrepancies?.length ? h('table', { class: 't' }, h('thead', {}, h('tr', {}, ['סרטון', 'סוג שגיאה', 'פריימים GT', 'פריימים חיזוי', 'IoU', 'הערות'].map(x => h('th', {}, x)))),
      h('tbody', {}, r.discrepancies.map(d => h('tr', {}, h('td', {}, ltr(d.source_name || d.source_sha256.slice(0, 8))), h('td', {}, pill(ERR_HE[d.type] ?? d.type, d.type === 'missed_event' ? 'bad' : 'warn')), h('td', {}, d.gt_interval ? ltr(`${d.gt_interval.start_frame}–${d.gt_interval.end_frame}`) : '—'), h('td', {}, d.pred_interval ? ltr(`${d.pred_interval.start_frame}–${d.pred_interval.end_frame}`) : '—'), h('td', {}, d.iou != null ? pct(d.iou) : '—'), h('td', {}, d.details || '—'))))) : h('div', { class: 'empty' }, 'אין אי-התאמות שנמצאו')));
}

// ---------------- Settings ----------------
export async function renderSettings(root) {
  setTopbar(h('strong', {}, 'הגדרות ענפים וסוגי אירועים'), pill('קונפיגורציה בלבד'));
  await loadSports();
  const list = sportsList();
  root.replaceChildren(h('div', { class: 'page' },
    h('h1', {}, 'ענפי ספורט וסוגי אירועים'),
    h('div', { class: 'sub' }, 'הענפים וסוגי האירועים מוגדרים במסד הנתונים ואינם נמחקים לעולם (פנסיה = השבתה). שינוי ענף לא דורס גרסאות ישנות.'),
    h('div', { class: 'grid' }, list.map(s => h('div', { class: 'card' },
      h('div', { class: 'body' },
        h('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
          h('strong', { style: { fontSize: '16px' } }, s.name_he),
          pill(s.enabled ? 'פעיל' : 'מושבת', s.enabled ? 'ok' : 'muted')
        ),
        h('div', { class: 'meta' }, ltr(s.name_en), ` · גרסה ${s.taxonomy_version}`),
        h('h4', { style: { margin: '8px 0 4px', fontSize: '12px', color: 'var(--muted)' } }, 'סוגי אירועים'),
        h('ul', { class: 'list' }, s.event_types.map(t => h('li', {},
          h('span', { style: { flex: 1 } }, t.label_he),
          h('span', { class: 'meta ltr mono' }, t.key),
          pill(t.enabled ? 'פעיל' : 'מושבת', t.enabled ? 'ok' : 'muted')
        )))
      )
    )))
  ));
}
