// Blind-run error review: WHY a pipeline run scored as it did, decision by decision.
//
// Reads only what an evaluation already compared — the frozen evaluation-split GT of one dataset, one imported
// predictions/v1 record and the EDLs of the same run — and explains every disagreement in operator terms:
//   selection  : what the pipeline used and should not have / what it should have used and did not (rejected vs never found)
//   identity   : wrong surfer, no surfer, one surfer split into several pipeline identities, several surfers merged into one
//   assembly   : which outputs (reels) mixed surfers, which surfer got no reel, which wave appears in several reels
//   trim       : cut takeoff / cut landing / late start / early end / dead time before or after the wave
//   framing    : surfer missing or clipped in the output, off-centre, crop jumps, crop following another person
// Pure core (`buildReview`) + a thin loader. Nothing here is written back, and nothing reaches the pipeline.
import { ApiError } from './errors.mjs';
import { matchEvents, iou1d } from './evaluate.mjs';
import { evaluateEditing, shotAt, shotSource } from './edl.mjs';

export const REVIEW_VERSION = 'review-1.0.0';
export const REVIEW_PARAMS = {
  cut_tolerance_sec: 0.5,     // starting later / ending earlier than the wave by more than this loses content
  slack_tolerance_sec: 1.5,   // starting earlier / ending later than the wave by more than this is dead time
  default_center: { x: 0.5, y: 0.5 },  // diagnostic centring target where the operator chose none
  framing_gap_frames: 3,      // consecutive flagged output frames closer than this form one episode
};
export const CATEGORIES = ['selection_wrong_use', 'selection_missed', 'identity', 'assembly', 'trim', 'framing'];

const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const r3 = n => Math.round(n * 1000) / 1000;
const overlaps = (a, b) => Math.min(a.end_frame, b.end_frame) > Math.max(a.start_frame, b.start_frame);
const ltr = t => `\u2066${t}\u2069`;   // keep times left-to-right inside Hebrew sentences
const fmt0 = sec => { if (sec == null) return '?'; const m = Math.floor(sec / 60), s = sec - m * 60; return `${m}:${s.toFixed(1).padStart(4, '0')}`; };
const fmt = sec => ltr(fmt0(sec));
const rng = (a, b) => ltr(`${fmt0(a)}–${fmt0(b)}`);

/**
 * @param report      evaluation report (params, run_id, per_source)
 * @param predSources imported prediction sources [{source_sha256, events (selected), rejected}]
 * @param members     frozen eval-split members [{sha256, split, content, owner_athlete_id}]
 * @param videos      sha -> {source_id, name, fps}
 * @param athletes    athlete_id -> label
 * @param edls        EDL payloads of the same run
 */
export function buildReview({ report, predSources, members, videos = {}, athletes = {}, edls = [], params = {} }) {
  const P0 = { ...REVIEW_PARAMS, ...params };
  const evp = { iou_threshold: report.params.iou_threshold };
  const preds = new Map(predSources.map(s => [s.source_sha256, s]));
  const items = [];
  const ath = id => id ? { id, label: athletes[id] ?? id } : null;
  const vid = sha => sha == null ? null : ({ sha256: sha, source_id: videos[sha]?.source_id ?? null, name: videos[sha]?.name ?? sha.slice(0, 12) });
  const sec = (sha, f) => { const fps = videos[sha]?.fps; return fps && f != null ? r3(f / fps) : null; };
  const span = (sha, a, b) => ({ start_frame: a, end_frame: b, start_sec: sec(sha, a), end_sec: sec(sha, b) });
  const push = (category, type, severity, sha, range, extra, explain) =>
    items.push({ category, type, severity, video: vid(sha), ...range, ...extra, explain_he: explain });

  // ---- pass 1: pairing per video, and global pipeline-identity <-> surfer co-occurrence ----
  const perVideo = [];
  const co = new Map();
  for (const m of members) {
    const gt = m.content, ps = preds.get(m.sha256);
    const events = ps?.events ?? [], rejected = ps?.rejected ?? [];
    const { G, P, matches, usedG, usedP } = matchEvents(gt, events, evp);
    const who = g => g.athlete_id ?? m.owner_athlete_id ?? null;
    for (const x of matches) if (who(x.g) && x.p.athlete_key != null) {
      const k = `${x.p.athlete_key}\u0000${who(x.g)}`; co.set(k, (co.get(k) ?? 0) + 1);
    }
    perVideo.push({ m, gt, ps, events, rejected, G, P, matches, usedG, usedP, who });
  }
  // greedy one-to-one map (most co-occurrences first, ties by key) — the same rule as the evaluator, but across the whole run
  const ranked = [...co.entries()].map(([k, n]) => { const [key, a] = k.split('\u0000'); return { key, a, n }; })
    .sort((x, y) => y.n - x.n || cmp(x.key, y.key) || cmp(x.a, y.a));
  const keyToAth = new Map(), athTaken = new Set();
  for (const r of ranked) if (!keyToAth.has(r.key) && !athTaken.has(r.a)) { keyToAth.set(r.key, r.a); athTaken.add(r.a); }
  const keysOfAth = new Map(), athsOfKey = new Map();
  for (const r of ranked) {
    (keysOfAth.get(r.a) ?? keysOfAth.set(r.a, new Map()).get(r.a)).set(r.key, r.n);
    (athsOfKey.get(r.key) ?? athsOfKey.set(r.key, new Map()).get(r.key)).set(r.a, r.n);
  }

  // ---- pass 2: per-decision findings ----
  const outputs = new Map();   // output_id -> {athletes: Map(id->n), events: [...]}
  const athleteOutputs = new Map(), athleteGt = new Map();
  let usedCorrect = 0;
  const cutTol = sha => Math.round(P0.cut_tolerance_sec * (videos[sha]?.fps ?? 30));
  const slackTol = sha => Math.round(P0.slack_tolerance_sec * (videos[sha]?.fps ?? 30));
  for (const v of perVideo) {
    const sha = v.m.sha256, gt = v.gt;
    for (const g of v.G) { const a = v.who(g); if (a) athleteGt.set(a, (athleteGt.get(a) ?? 0) + 1); }
    if (!v.ps) push('selection_missed', 'video_not_processed', 'bad', sha, span(sha, 0, 0), { gt_events: v.G.length },
      `הפייפליין לא החזיר שום תוצאה לסרטון הזה (${v.G.length} גלים מתויגים).`);
    // what it used but should not have
    for (const p of v.P) {
      if (v.usedP.has(p.idx)) continue;
      // a near-miss of an annotated wave is explained once, on the missed wave (missed_poor_overlap), not again as a false positive
      if (v.G.some(g => !v.usedG.has(g.id) && overlaps(g, p))) continue;
      const rendered = (p.outputs ?? []).map(o => o.output_id);
      const into = rendered.length ? ` ונכנס ל-${[...new Set(rendered)].join(', ')}` : '';
      const dup = v.G.find(g => v.usedG.has(g.id) && iou1d(g, p) >= evp.iou_threshold);
      const excl = (gt.segments ?? []).find(s => s.decision === 'exclude' && overlaps(s, p));
      const unc = (gt.segments ?? []).find(s => s.decision === 'uncertain' && overlaps(s, p));
      const mid = Math.floor((p.start_frame + p.end_frame) / 2);
      const reviewed = (gt.reviewed_ranges ?? []).some(r => mid >= r.start_frame && mid < r.end_frame);
      const base = { pred_index: p.idx, candidate_id: p.candidate_id ?? null, pipeline_athlete_key: p.athlete_key ?? null, score: p.score ?? null, outputs: [...new Set(rendered)] };
      if (dup) push('selection_wrong_use', 'duplicate', 'warn', sha, span(sha, p.start_frame, p.end_frame), { ...base, segment_id: dup.id, athlete: ath(v.who(dup)) },
        `אותו גל נבחר פעמיים (כפילות של גל ${fmt(sec(sha, dup.start_frame))})${into}.`);
      else if (excl) push('selection_wrong_use', 'used_excluded', 'bad', sha, span(sha, p.start_frame, p.end_frame), { ...base, segment_id: excl.id, gt_reason_codes: excl.reason_codes ?? [], gt_usability: excl.usability ?? null },
        `השתמש בקטע שסומן "לא לכלול"${excl.reason_codes?.length ? ` (${excl.reason_codes.join(', ')})` : ''}${into}.`);
      else if (unc) push('selection_wrong_use', 'used_uncertain', 'info', sha, span(sha, p.start_frame, p.end_frame), { ...base, segment_id: unc.id },
        `השתמש בקטע שסומן "לא בטוח" — לא נספר כטעות${into}.`);
      else if (!reviewed) push('selection_wrong_use', 'used_unreviewed', 'info', sha, span(sha, p.start_frame, p.end_frame), base,
        `השתמש בקטע שלא נבדק בתיוג — אין אמת להשוואה${into}.`);
      else push('selection_wrong_use', 'false_positive', 'bad', sha, span(sha, p.start_frame, p.end_frame), base,
        `השתמש בקטע שאין בו גל מתויג${into}.`);
    }
    // what it should have used and did not
    for (const g of v.G) {
      if (v.usedG.has(g.id)) continue;
      const rj = v.rejected.filter(r => overlaps(g, r)).sort((a, b) => iou1d(g, b) - iou1d(g, a))[0];
      const near = v.P.filter(p => overlaps(g, p) && !v.usedP.has(p.idx)).sort((a, b) => iou1d(g, b) - iou1d(g, a))[0];
      const base = { segment_id: g.id, athlete: ath(v.who(g)), event_type: g.event_type ?? null, usability: g.usability ?? null };
      const wrongSport = near && near.sport_id != null && near.sport_id !== (g.resolved_sport_id ?? 'unknown');
      if (wrongSport) push('selection_missed', 'missed_wrong_sport', 'bad', sha, span(sha, g.start_frame, g.end_frame), { ...base, pred_window: span(sha, near.start_frame, near.end_frame), pipeline_sport: near.sport_id, gt_sport: g.resolved_sport_id ?? null },
        `נמצא קטע בזמן הזה אבל הפייפליין סיווג אותו כענף אחר (${near.sport_id}${g.resolved_sport_id ? ` במקום ${g.resolved_sport_id}` : ''}).`);
      else if (near) push('selection_missed', 'missed_poor_overlap', 'bad', sha, span(sha, g.start_frame, g.end_frame), { ...base, pred_window: span(sha, near.start_frame, near.end_frame), iou: r3(iou1d(g, near)) },
        `הגל נמצא אבל החיתוך רחוק מדי מהגל האמיתי (חפיפה ${Math.round(iou1d(g, near) * 100)}%, נבחר ${rng(sec(sha, near.start_frame), sec(sha, near.end_frame))}).`);
      else if (rj) push('selection_missed', 'missed_rejected', 'bad', sha, span(sha, g.start_frame, g.end_frame), { ...base, pipeline_reason: rj.reason, candidate_id: rj.candidate_id ?? null },
        `הפייפליין מצא את הגל ופסל אותו (סיבה: ${rj.reason}).`);
      else push('selection_missed', 'missed_never_detected', 'bad', sha, span(sha, g.start_frame, g.end_frame), base,
        'הגל לא זוהה בכלל — אין מועמד שחופף לו.');
    }
    // matched: identity, assembly, trimming
    for (const x of v.matches) {
      const g = x.g, p = x.p, truth = v.who(g);
      const base = { segment_id: g.id, pred_index: p.idx, candidate_id: p.candidate_id ?? null, athlete: ath(truth), pipeline_athlete_key: p.athlete_key ?? null };
      const range = span(sha, g.start_frame, g.end_frame);
      let ok = true;
      if (truth && p.athlete_key == null) { ok = false; push('identity', 'no_identity', 'warn', sha, range, base, `הגל נבחר אבל הפייפליין לא שייך אותו לאף גולש (האמת: ${ath(truth).label}).`); }
      else if (truth && keyToAth.get(String(p.athlete_key)) !== truth) {
        ok = false;
        const as = keyToAth.get(String(p.athlete_key));
        push('identity', 'wrong_athlete', 'bad', sha, range, { ...base, pipeline_athlete_as: ath(as) },
          `שויך לגולש הלא נכון: האמת ${ath(truth).label}, הפייפליין ${as ? `חשב שזה ${ath(as).label}` : `נתן זהות ${p.athlete_key} שלא תואמת לאף גולש`}.`);
      }
      // trimming (the selected window vs the annotated wave and its key moments)
      const km = g.key_moments ?? {}, ct = cutTol(sha), sl = slackTol(sha);
      const tr = (type, sev, txt, extra = {}) => { ok = false; push('trim', type, sev, sha, range, { ...base, pred_window: span(sha, p.start_frame, p.end_frame), ...extra }, txt); };
      const dS = p.start_frame - g.start_frame, dE = p.end_frame - g.end_frame, s = f => sec(sha, Math.abs(f));
      if (km.takeoff_frame != null && p.start_frame > km.takeoff_frame) tr('cut_takeoff', 'bad', `החיתוך מתחיל אחרי הקמה — ההקמה חסרה (${s(p.start_frame - km.takeoff_frame)} שנ').`, { takeoff_frame: km.takeoff_frame });
      else if (dS > ct) tr('late_start', 'warn', `החיתוך מתחיל ${s(dS)} שנ' אחרי תחילת הגל.`);
      else if (dS < -sl) tr('early_start', 'info', `${s(dS)} שנ' של זמן מת לפני הגל.`);
      if (km.landing_frame != null && p.end_frame <= km.landing_frame) tr('cut_landing', 'bad', `החיתוך נגמר לפני הסיום — הסוף של הגל חסר (${s(km.landing_frame - p.end_frame)} שנ').`, { landing_frame: km.landing_frame });
      else if (dE < -ct) tr('early_end', 'warn', `החיתוך נגמר ${s(dE)} שנ' לפני סוף הגל.`);
      else if (dE > sl) tr('late_end', 'info', `${s(dE)} שנ' של זמן מת אחרי הגל.`);
      if (ok) usedCorrect++;
      const outs = [...new Set((p.outputs ?? []).map(o => o.output_id))];
      if (!outs.length) push('assembly', 'selected_not_rendered', 'info', sha, range, base, 'הגל נבחר אבל לא הופיע באף סרטון פלט.');
      if (outs.length > 1) push('assembly', 'event_in_multiple_outputs', 'warn', sha, range, { ...base, outputs: outs }, `אותו גל מופיע ב-${outs.length} סרטוני פלט: ${outs.join(', ')}.`);
      for (const o of outs) {
        const rec = outputs.get(o) ?? outputs.set(o, { output_id: o, athletes: new Map(), events: [] }).get(o);
        if (truth) rec.athletes.set(truth, (rec.athletes.get(truth) ?? 0) + 1);
        rec.events.push({ video: vid(sha), segment_id: g.id, athlete: ath(truth), ...range });
        if (truth) (athleteOutputs.get(truth) ?? athleteOutputs.set(truth, new Set()).get(truth)).add(o);
      }
    }
  }
  // identity across the run: one surfer seen as several people / several surfers seen as one
  for (const [a, keys] of [...keysOfAth.entries()].sort((x, y) => cmp(x[0], y[0]))) if (keys.size > 1) {
    push('identity', 'athlete_split', 'warn', null, {}, { athlete: ath(a), pipeline_keys: Object.fromEntries([...keys].sort()) },
      `הפייפליין חשב שהגולש ${ath(a).label} הוא ${keys.size} אנשים שונים (${[...keys.keys()].sort().join(', ')}).`);
  }
  for (const [k, as] of [...athsOfKey.entries()].sort((x, y) => cmp(x[0], y[0]))) if (as.size > 1) {
    push('identity', 'athletes_merged', 'bad', null, {}, { pipeline_athlete_key: k, athletes: [...as.keys()].sort().map(ath) },
      `הפייפליין איחד ${as.size} גולשים שונים לזהות אחת (${k}): ${[...as.keys()].sort().map(a => ath(a).label).join(', ')}.`);
  }
  // assembly across outputs
  const outList = [...outputs.values()].sort((a, b) => cmp(a.output_id, b.output_id)).map(o => ({ output_id: o.output_id, events: o.events.length,
    athletes: [...o.athletes.entries()].sort((x, y) => y[1] - x[1] || cmp(x[0], y[0])).map(([a, n]) => ({ ...ath(a), events: n })) }));
  for (const o of outList) if (o.athletes.length > 1) push('assembly', 'mixed_athletes_in_output', 'bad', null, {}, { output_id: o.output_id, athletes: o.athletes },
    `סרטון הפלט ${o.output_id} מערבב ${o.athletes.length} גולשים: ${o.athletes.map(a => `${a.label} (${a.events})`).join(', ')}.`);
  for (const [a, outs] of [...athleteOutputs.entries()].sort((x, y) => cmp(x[0], y[0]))) if (outs.size > 1) push('assembly', 'athlete_split_across_outputs', 'warn', null, {}, { athlete: ath(a), outputs: [...outs].sort() },
    `הגלים של ${ath(a).label} התפזרו על ${outs.size} סרטוני פלט: ${[...outs].sort().join(', ')}.`);
  for (const [a, n] of [...athleteGt.entries()].sort((x, y) => cmp(x[0], y[0]))) if (!athleteOutputs.has(a) && outputs.size) push('assembly', 'athlete_without_output', 'bad', null, {}, { athlete: ath(a), gt_events: n },
    `לגולש ${ath(a).label} יש ${n} גלים מתויגים ואף אחד מהם לא הגיע לסרטון פלט.`);

  // ---- framing: the run's own EDLs against the frozen evaluation-split boxes (boxes are guidance) ----
  const bySha = Object.fromEntries(members.map(m => [m.sha256, m.content]));
  const framing = [];
  for (const edl of [...edls].sort((a, b) => cmp(a.output_id, b.output_id))) {
    let rep;
    try { rep = evaluateEditing(edl, { bySha }, { default_target: P0.default_center }); } catch (e) { framing.push({ output_id: edl.output_id, status: 'INVALID_EDL', reason: e.message }); continue; }
    framing.push({ output_id: edl.output_id, status: rep.status, reason: rep.reason ?? null, mode: rep.mode ?? edl.mode, coverage: rep.coverage ?? null, visibility: rep.visibility ?? null,
      centering: rep.centering ?? null, centering_default_target_frames: rep.centering_default_target_frames ?? 0, smoothness: rep.smoothness ?? null });
    if (rep.status !== 'EVALUATED') continue;
    for (const ep of episodes(rep.errors, P0.framing_gap_frames)) {
      const sev = ep.type === 'missing_surfer' || ep.type === 'wrong_surfer' ? 'bad' : ep.type === 'partial_clipping' || ep.type === 'crop_jump' ? 'warn' : 'info';
      const at = shotAt(edl, ep.out_start), sha = at ? shotSource(edl, at.shot).sha : null;
      const txt = { missing_surfer: 'הגולש לא נראה בכלל בפלט', partial_clipping: 'הגולש חתוך בקצה הפריים', edge_violation: 'הגולש צמוד מדי לקצה הפריים',
        centering_error: 'הגולש רחוק מהמרכז', crop_jump: 'קפיצה חדה של החיתוך', wrong_surfer: 'החיתוך עוקב אחרי אדם אחר' }[ep.type] ?? ep.type;
      push('framing', ep.type, sev, sha, sha ? span(sha, ep.src_frame_start, ep.src_frame_end + 1) : {}, { output_id: edl.output_id, out_frame_start: ep.out_start, out_frame_end: ep.out_end, frames: ep.frames, ...(ep.worst != null ? { worst: ep.worst } : {}) },
        `${txt} — ${ep.frames} פריימים בפלט ${edl.output_id} (פריימים ${ltr(`${ep.out_start}–${ep.out_end}`)}).`);
    }
  }

  const sevRank = { bad: 0, warn: 1, info: 2 };
  items.sort((a, b) => CATEGORIES.indexOf(a.category) - CATEGORIES.indexOf(b.category) || sevRank[a.severity] - sevRank[b.severity]
    || cmp(a.video?.name ?? '', b.video?.name ?? '') || (a.start_frame ?? 0) - (b.start_frame ?? 0) || cmp(a.type, b.type));
  const count = (c, t) => items.filter(i => i.category === c && (!t || t.includes(i.type))).length;
  const gtTotal = perVideo.reduce((n, v) => n + v.G.length, 0);
  return {
    review_version: REVIEW_VERSION, run_id: report.run_id, pipeline_version: report.pipeline_version, splits: report.params.splits, params: P0,
    summary: {
      videos: members.length, videos_without_prediction: perVideo.filter(v => !v.ps).length, gt_events: gtTotal,
      matched: perVideo.reduce((n, v) => n + v.matches.length, 0), matched_without_issue: usedCorrect,
      used_wrongly: count('selection_wrong_use', ['false_positive', 'used_excluded', 'duplicate']),
      missed: count('selection_missed', ['missed_rejected', 'missed_never_detected', 'missed_poor_overlap', 'missed_wrong_sport']),
      missed_rejected: count('selection_missed', ['missed_rejected']), missed_never_detected: count('selection_missed', ['missed_never_detected']),
      missed_poor_overlap: count('selection_missed', ['missed_poor_overlap']),
      identity_issues: count('identity'), assembly_issues: count('assembly', ['mixed_athletes_in_output', 'athlete_without_output', 'event_in_multiple_outputs', 'athlete_split_across_outputs']),
      trim_issues: count('trim'), outputs: outList.length, framing_outputs_evaluated: framing.filter(f => f.status === 'EVALUATED').length, framing_issues: count('framing'),
    },
    identity_map: [...athsOfKey.entries()].sort((x, y) => cmp(x[0], y[0])).map(([k, as]) => ({ pipeline_athlete_key: k, mapped_to: ath(keyToAth.get(k)),
      seen_as: [...as.entries()].sort((x, y) => y[1] - x[1] || cmp(x[0], y[0])).map(([a, n]) => ({ ...ath(a), events: n })) })),
    outputs: outList, framing, items,
  };
}

/** Collapse per-frame flags into episodes (same type, output frames within `gap`). */
function episodes(errors, gap) {
  const byType = new Map();
  for (const e of errors ?? []) (byType.get(e.type) ?? byType.set(e.type, []).get(e.type)).push(e);
  const out = [];
  for (const [type, es] of byType) {
    es.sort((a, b) => a.out_frame - b.out_frame);
    let cur = null;
    for (const e of es) {
      const w = e.error ?? e.velocity ?? (e.visible_fraction != null ? 1 - e.visible_fraction : null) ?? (e.iou != null ? 1 - e.iou : null);
      if (cur && e.out_frame - cur.out_end <= gap) { cur.out_end = e.out_frame; cur.frames++; cur.src_frame_start = Math.min(cur.src_frame_start, e.src_frame); cur.src_frame_end = Math.max(cur.src_frame_end, e.src_frame); if (w != null) cur.worst = Math.max(cur.worst ?? 0, r3(w)); continue; }
      cur = { type, out_start: e.out_frame, out_end: e.out_frame, src_frame_start: e.src_frame, src_frame_end: e.src_frame, frames: 1, worst: w != null ? r3(w) : null };
      out.push(cur);
    }
  }
  return out.sort((a, b) => a.out_start - b.out_start || cmp(a.type, b.type));
}

/** Loader: one stored evaluation -> its error review. Uses only the evaluated splits of the frozen dataset. */
export function reviewEvaluation(db, evaluationId) {
  const ev = db.prepare('select * from evaluation_runs where id=?').get(evaluationId);
  if (!ev) throw new ApiError('NOT_FOUND');
  const report = JSON.parse(ev.report);
  const pr = db.prepare('select * from pipeline_predictions where id=?').get(ev.prediction_id);
  const ds = db.prepare('select * from frozen_datasets where id=?').get(ev.dataset_id);
  if (!pr || !ds) throw new ApiError('NOT_FOUND');
  const payload = JSON.parse(pr.payload);
  const owners = new Map((JSON.parse(ds.manifest).members ?? []).map(m => [m.sha256, m.athlete_of_record?.athlete_id ?? null]));
  const members = db.prepare('select * from frozen_revisions where dataset_id=? order by sha256').all(ev.dataset_id)
    .filter(m => report.params.splits.includes(m.split))
    .map(m => ({ sha256: m.sha256, split: m.split, content: JSON.parse(m.content), owner_athlete_id: owners.get(m.sha256) ?? null }));
  const videos = {};
  for (const m of members) {
    const s = db.prepare('select id,display_name,fps_num,fps_den from sources where sha256=? order by created_at limit 1').get(m.sha256);
    if (s) videos[m.sha256] = { source_id: s.id, name: s.display_name, fps: s.fps_num && s.fps_den ? s.fps_num / s.fps_den : null };
  }
  const athletes = Object.fromEntries(db.prepare('select id,label from athletes').all().map(a => [a.id, a.label]));
  const evalShas = new Set(members.map(m => m.sha256));
  // only outputs of THIS run whose every shot comes from an evaluated video (no partial / train-split framing claims)
  const edls = db.prepare('select payload from edl_records where run_id=? order by output_id').all(report.run_id).map(r => JSON.parse(r.payload))
    .filter(e => e.shots.every(s => evalShas.has(s.source_sha256 ?? e.source_sha256)));
  return { evaluation_id: ev.id, evaluation_digest: ev.digest, ...buildReview({ report, predSources: payload.sources, members, videos, athletes, edls }) };
}
