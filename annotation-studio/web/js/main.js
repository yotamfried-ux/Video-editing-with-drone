import { $, h, api, toast } from './ui.js';
import { renderLibrary } from './library.js';
import { renderAnnotate, teardownAnnotate } from './annotate.js';
import { renderAthletes, renderDatasets, renderEvaluations } from './others.js';
import { renderEditing, teardownEditing } from './editing.js';

const NAV = [['library', 'ספרייה', '▦'], ['annotate', 'סימון', '✎'], ['athletes', 'גולשים', '☺'], ['datasets', 'דאטהסטים', '❖'], ['evaluations', 'הערכות AI', '≋'], ['editing', 'בקרת עריכה', '▶']];
let lastSource = localStorage.getItem('studio.lastSource');

function chrome(active) {
  $('#sidebar').replaceChildren(
    h('div', { class: 'brand' }, h('i'), h('span', {}, 'SportReel Studio')),
    h('div', { class: 'nav' }, NAV.map(([k, label, ic]) => h('a', { href: k === 'annotate' ? `#/annotate/${lastSource ?? ''}` : `#/${k}`, 'aria-current': k === active ? 'page' : null, title: label }, h('span', { 'aria-hidden': 'true' }, ic), h('span', { class: 'lbl' }, label)))),
    h('div', { class: 'spacer' }),
    h('button', { class: 'btn sm', 'aria-label': 'כווץ תפריט', onclick: () => $('#app').classList.toggle('collapsed') }, '⇔'));
}
export function setTopbar(...kids) { $('#topbar').replaceChildren(...kids); }
export function rememberSource(id) { lastSource = id; try { localStorage.setItem('studio.lastSource', id); } catch {} }

async function route() {
  teardownAnnotate(); teardownEditing();
  const [, view = 'library', arg] = location.hash.split('/');
  chrome(view);
  const main = $('#main'); main.replaceChildren();
  setTopbar(h('strong', {}, 'SportReel Annotation Studio'));
  try {
    if (view === 'library') await renderLibrary(main);
    else if (view === 'annotate') await renderAnnotate(main, arg);
    else if (view === 'athletes') await renderAthletes(main);
    else if (view === 'datasets') await renderDatasets(main);
    else if (view === 'evaluations') await renderEvaluations(main, arg);
    else if (view === 'editing') await renderEditing(main, arg);
    else main.append(h('div', { class: 'page' }, h('div', { class: 'empty' }, 'עמוד לא נמצא')));
  } catch (e) {
    if (e.status === 401) main.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'banner bad' }, 'אין הרשאה — פתח את הסטודיו דרך הקישור שהודפס בעת ההפעלה (כולל ‎?t=…‎).')));
    else { toast(e.message, true); main.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'banner bad' }, e.message))); }
  }
  main.focus({ preventScroll: true });
}
addEventListener('hashchange', route);
if (!location.hash) location.hash = '#/library'; else route();
