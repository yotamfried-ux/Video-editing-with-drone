import { $, h, api, toast, loadSports } from './ui.js';
import { renderLibrary } from './library.js';
import { renderAnnotate, teardownAnnotate } from './annotate.js';
import { renderAthletes, renderDatasets, renderEvaluations, renderSettings, renderSets } from './others.js';
import { renderEditing, teardownEditing } from './editing.js';
import { renderCloud } from './cloud.js';
import { renderCatalog } from './catalog.js';

// One cataloguing process: the catalog queue leads through every field; the marking workbench is its event/BOX step
// (opened from the catalog, highlighted under it). Library and cloud are source-management tools reached from the catalog.
const NAV = [['catalog', 'קטלוג', '☰'], ['athletes', 'גולשים', '☺'], ['sets', 'סטים והכרעה', '⇄'], ['datasets', 'דאטהסטים', '❖'], ['evaluations', 'הערכות AI', '≋'], ['editing', 'בקרת עריכה', '▶'], ['settings', 'הגדרות ענפים', '⚙']];
let lastSource = localStorage.getItem('studio.lastSource');
let VERSION = null;   // the running code's commit, so the operator can see whether the updated version is the one open

function chrome(active) {
  $('#sidebar').replaceChildren(
    h('div', { class: 'brand' }, h('i'), h('span', {}, 'SportReel Studio')),
    h('div', { class: 'nav' }, NAV.map(([k, label, ic]) => h('a', { href: `#/${k}`, 'aria-current': k === active || (k === 'catalog' && ['annotate', 'library', 'cloud'].includes(active)) ? 'page' : null, title: label }, h('span', { 'aria-hidden': 'true' }, ic), h('span', { class: 'lbl' }, label)))),
    h('div', { class: 'spacer' }),
    h('div', { class: 'meta ltr', 'data-testid': 'app-version', title: 'גרסת הקוד שרצה כעת', style: { padding: '0 12px 6px' } }, VERSION ? `v ${VERSION}` : ''),
    h('button', { class: 'btn sm', 'aria-label': 'כווץ תפריט', onclick: () => $('#app').classList.toggle('collapsed') }, '⇔'));
}
/** Shown when this browser is not signed in yet: the access code goes in a POST body (never in the address bar). */
function loginForm() {
  let code = '';
  const err = h('div', { class: 'banner bad', 'data-testid': 'login-error', style: { display: 'none' } });
  const submit = async e => {
    e?.preventDefault();
    const r = await fetch('/auth/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token: code }), credentials: 'same-origin' });
    if (r.ok) { location.reload(); return; }
    err.textContent = r.status === 401 ? 'קוד הכניסה שגוי. בדוק שהעתקת אותו במלואו.' : 'הכניסה נכשלה. נסה שוב.';
    err.style.display = '';
  };
  return h('div', { class: 'page' }, h('form', { class: 'qc-step', style: { maxWidth: '460px', margin: '40px auto' }, 'data-testid': 'login-form', onsubmit: submit },
    h('h3', {}, 'כניסה לסטודיו'),
    h('p', { class: 'meta' }, 'הדבק את קוד הכניסה של הסטודיו. אחרי הכניסה הדפדפן הזה יישאר מחובר.'),
    h('input', { type: 'password', autocomplete: 'current-password', 'aria-label': 'קוד כניסה', 'data-testid': 'login-code', oninput: e => { code = e.target.value; }, style: { width: '100%', margin: '8px 0' } }),
    err,
    h('button', { class: 'btn primary', type: 'submit', 'data-testid': 'login-submit' }, 'כניסה')));
}
export function setTopbar(...kids) { $('#topbar').replaceChildren(...kids.filter(Boolean)); }
export function rememberSource(id) { lastSource = id; try { localStorage.setItem('studio.lastSource', id); } catch {} }

async function route() {
  teardownAnnotate(); teardownEditing();
  const [, view = 'catalog', arg] = location.hash.split('/');
  chrome(view);
  // Each navigation renders into its own container: a slower screen that finishes after the user moved on writes into a
  // detached element instead of overwriting the screen that is now open.
  const host = $('#main');
  const main = h('div', { style: { display: 'contents' } });
  host.replaceChildren(main);
  setTopbar(h('strong', {}, 'SportReel Annotation Studio'));
  try {
    await loadSports();
    if (view === 'library') await renderLibrary(main);
    else if (view === 'cloud') await renderCloud(main);
    else if (view === 'catalog') await renderCatalog(main, arg);
    else if (view === 'annotate') await renderAnnotate(main, arg);
    else if (view === 'athletes') await renderAthletes(main);
    else if (view === 'sets') await renderSets(main);
    else if (view === 'datasets') await renderDatasets(main);
    else if (view === 'evaluations') await renderEvaluations(main, arg);
    else if (view === 'editing') await renderEditing(main, arg);
    else if (view === 'settings') await renderSettings(main);
    else main.append(h('div', { class: 'page' }, h('div', { class: 'empty' }, 'עמוד לא נמצא')));
  } catch (e) {
    if (e.status === 401) main.replaceChildren(loginForm());
    else { toast(e.message, true); main.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'banner bad' }, e.message))); }
  }
  host.focus({ preventScroll: true });
}
addEventListener('hashchange', route);
api('/api/version').then(v => { VERSION = v.commit ?? v.version ?? null; const el = $('[data-testid=app-version]'); if (el) el.textContent = VERSION ? `v ${VERSION}` : ''; }).catch(() => {});
if (!location.hash) location.hash = '#/catalog'; else route();
