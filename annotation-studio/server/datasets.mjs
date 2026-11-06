// Dataset freezing. A dataset version pins exact (sha256, approved revision) pairs and is immutable.
import { createHash, randomUUID } from 'node:crypto';
import { verifiedBoxes } from './trackqa.mjs';
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { digestOf, latestRevision } from './annotations.mjs';
import { lineageSnapshot } from './lineage.mjs';
import { unadjudicatedDisagreements } from './sets.mjs';

export const DEFAULT_POLICY = { seed: 'sportreel-v1', ratios: { train: 0.7, validation: 0.15, test: 0.15 } };

/** Deterministic split by *group* (recording session) so near-duplicates never straddle splits. */
const cmpHash = (a, b) => { const x = createHash('sha256').update(a).digest('hex'), y = createHash('sha256').update(b).digest('hex'); return x < y ? -1 : x > y ? 1 : 0; };
export function splitFor(groupKey, policy) {
  const h = createHash('sha256').update(`${policy.seed}|${groupKey}`).digest();
  const u = h.readUInt32BE(0) / 0x100000000;
  const { train, validation } = policy.ratios;
  return u < train ? 'train' : u < train + validation ? 'validation' : 'test';
}

export function freezeDataset(db, { name, sourceIds, policy = DEFAULT_POLICY }) {
  if (!name || !sourceIds?.length) throw new ApiError('INVALID_INPUT');
  return tx(db, () => {
    // The held-out test set is permanent: anything that was ever in a test split stays there.
    const heldOut = new Set(db.prepare("select source_id from dataset_members where split='test'").all().map(r => r.source_id));
    const members = [];
    for (const id of [...new Set(sourceIds)].sort()) {
      const s = db.prepare('select * from sources where id=?').get(id);
      const rev = s && latestRevision(db, id);
      if (!s) throw new ApiError('NOT_FOUND', `מקור לא נמצא: ${id}`);
      if (!rev) throw new ApiError('INVALID_INPUT', `אין גרסה מאושרת עבור ${s.display_name}`);
      if (s.ingest_state !== 'ready') throw new ApiError('ARCHIVE_UNVERIFIED');
      if (s.provider === 'cloud-r2' && s.verify_state !== 'verified') throw new ApiError('SOURCE_UNVERIFIED');
      const group = s.session_key ?? s.id;
      // Taxonomy versions in force when the revision was approved are pinned in the manifest (only when a sport was involved).
      const tax = rev.taxonomy_versions ? JSON.parse(rev.taxonomy_versions) : {};
      // who is in this video (its owner and every event's performer): the athletes it would teach the pipeline about
      const athletes = [...new Set([s.owner_athlete_id, ...(JSON.parse(rev.content).segments ?? []).map(g => g.athlete_id)].filter(Boolean))].sort();
      members.push({ source_id: id, sha256: s.sha256, revision_id: rev.id, revision_digest: rev.digest, group, session: s.session_key ?? null, athletes,
        ...(Object.keys(tax).length ? { taxonomy_versions: tax } : {}),
        // whose video this is: SOURCE OF TRUTH for the pipeline (assigned by the operator), pinned as it was at freeze
        ...(s.owner_athlete_id ? { athlete_of_record: { athlete_id: s.owner_athlete_id, status: s.owner_status ?? null, assigned_by: s.owner_assigned_by ?? null, owner_version: s.owner_version ?? null } } : {}),
        split: heldOut.has(id) ? 'test' : splitFor(group, policy) });
    }
    // Leak-free split by ATHLETE (policy.group_by = 'athlete'): every video of an athlete - and of anyone sharing a video
    // with them - is one group, so no athlete is seen in training and then "tested" again (the pipeline must be judged on
    // people and conditions it never saw, not on what it memorised). policy.test_sessions: recording days held out whole
    // as the test set (another day = other light, sea and people). The rest is assigned in deterministic hash order by
    // cumulative share of videos. The permanent held-out test set still wins.
    if (policy.group_by === 'athlete') {
      const parent = new Map(), find = a => { while (parent.get(a) !== a) { parent.set(a, parent.get(parent.get(a))); a = parent.get(a); } return a; };
      const add = a => { if (!parent.has(a)) parent.set(a, a); };
      for (const m of members) { const ks = m.athletes.length ? m.athletes.map(a => `a:${a}`) : [`v:${m.source_id}`]; ks.forEach(add); for (const k of ks.slice(1)) parent.set(find(k), find(ks[0])); }
      const comp = new Map();
      for (const m of members) { const root = find(m.athletes.length ? `a:${m.athletes[0]}` : `v:${m.source_id}`); (comp.get(root) ?? comp.set(root, []).get(root)).push(m); }
      const testSessions = new Set(policy.test_sessions ?? []);
      const groups = [...comp.values()].map(ms => ({ ms, key: ms.flatMap(m => m.athletes.length ? m.athletes : [m.source_id]).sort()[0] }));
      for (const g of groups) for (const m of g.ms) m.group = `athlete:${g.key}`;
      const forced = groups.filter(g => g.ms.some(m => testSessions.has(m.session) || heldOut.has(m.source_id)));
      const rest = groups.filter(g => !forced.includes(g)).sort((a, b) => cmpHash(`${policy.seed}|${a.key}`, `${policy.seed}|${b.key}`));
      for (const g of forced) for (const m of g.ms) m.split = 'test';
      const r = policy.ratios, pool = testSessions.size ? { train: r.train / (r.train + r.validation), validation: 1 } : { train: r.train, validation: r.train + r.validation };
      const N = rest.reduce((n, g) => n + g.ms.length, 0); let cum = 0;
      for (const g of rest) { const u = (cum + g.ms.length / 2) / Math.max(1, N); cum += g.ms.length;
        const sp = u < pool.train ? 'train' : u < pool.validation ? 'validation' : 'test'; for (const m of g.ms) m.split = sp; }
    }
    // Optional stratification by sport (spec §18): within each sport, groups are ordered by their deterministic hash and
    // assigned by cumulative ratio, so every sport gets its share of train/validation/test. The permanent held-out test
    // set still wins. Default policy is unchanged (no stratification), so existing manifests reproduce exactly.
    if (policy.stratify_by_sport) {
      const sportOf = id => db.prepare('select primary_sport_id from sources where id=?').get(id)?.primary_sport_id ?? 'unknown';
      const bySport = new Map();
      for (const m of members) { m.sport = sportOf(m.source_id); (bySport.get(m.sport) ?? bySport.set(m.sport, new Set()).get(m.sport)).add(m.group); }
      for (const [sport, groups] of bySport) {
        const ordered = [...groups].sort((a, b) => cmpHash(`${policy.seed}|${sport}|${a}`, `${policy.seed}|${sport}|${b}`));
        const { train, validation } = policy.ratios, n = ordered.length;
        ordered.forEach((g, i) => { const u = (i + 0.5) / n; const sp = u < train ? 'train' : u < train + validation ? 'validation' : 'test';
          for (const m of members) if (m.sport === sport && m.group === g && !heldOut.has(m.source_id)) m.split = sp; });
      }
    }
    // Group consistency: every member of a group takes the same split (test wins).
    const byGroup = new Map();
    for (const m of members) byGroup.set(m.group, (byGroup.get(m.group) ?? new Set()).add(m.split));
    for (const m of members) { const sp = byGroup.get(m.group); if (sp.has('test')) m.split = 'test'; }
    // Addendum §11: no freeze while an independent comparison has blocking disagreements without an accepted adjudication.
    const open = unadjudicatedDisagreements(db, members.map(m => m.source_id));
    if (open.length) throw Object.assign(new ApiError('BLOCKING_DISAGREEMENT', `${open.length} מקורות עם אי-הסכמות חוסמות שלא הוכרעו`), { unresolved: open });
    const manifest = { name, policy, members: members.map(({ group, sport, session, athletes, ...m }) => policy.group_by === 'athlete' ? { ...m, group } : m) };
    if (policy.stratify_by_sport) manifest.sport_strata = Object.fromEntries([...new Set(members.map(m => m.sport))].sort().map(sp => [sp, ['train', 'validation', 'test'].reduce((o, k) => ({ ...o, [k]: members.filter(m => m.sport === sp && m.split === k).length }), {})]));
    // Pin the exact identity-lineage relations and physical-action lineage used by this version (only when any exist,
    // so manifests of datasets without lineage are byte-identical to before).
    const lin = lineageSnapshot(db, members.map(m => m.source_id));
    if (lin.person_lineage_relation_ids.length || lin.physical_actions.length) manifest.lineage = lin;
    const indep = db.prepare("select id, purpose from annotation_sets where id != 'primary' order by created_at").all();
    if (indep.length) manifest.annotation_sets = { ground_truth_set: 'primary', independent_sets: indep.map(x => x.id) };
    const digest = digestOf(manifest);
    const id = randomUUID();
    db.prepare('insert into dataset_versions(id,name,created_at,policy,manifest,digest) values(?,?,?,?,?,?)')
      .run(id, name, now(), JSON.stringify(policy), JSON.stringify(manifest), digest);
    for (const m of manifest.members) {
      db.prepare('insert into dataset_members(dataset_id,source_id,sha256,revision_id,split) values(?,?,?,?,?)')
        .run(id, m.source_id, m.sha256, m.revision_id, m.split);
    }
    audit(db, 'operator', 'dataset_frozen', id, { digest, members: members.length });
    return { id, digest, manifest };
  });
}

export function listDatasets(db) {
  return db.prepare('select id,name,created_at,digest,manifest from dataset_versions order by created_at desc').all().map(d => {
    const m = JSON.parse(d.manifest);
    const counts = { train: 0, validation: 0, test: 0 };
    for (const x of m.members) counts[x.split]++;
    return { id: d.id, name: d.name, created_at: d.created_at, digest: d.digest, counts, members: m.members.length };
  });
}

/**
 * How much each label may be trusted (operator, 2026-11-06): the video's owner (athlete_of_record) is the source of
 * truth; boxes GUIDE the pipeline (where to look, how big the athlete is) and are not unquestionable truth - drawn by
 * the operator or suggested by the tracker and accepted on review.
 */
export const LABEL_ROLES = { athlete_of_record: 'source_of_truth', box_guidance: 'guidance', verified_boxes: 'guidance (same boxes, legacy name)' };
/** The approved boxes as guidance: who drew them, and whether their event is in the dataset. */
export function boxGuidance(content) {
  const segs = new Map((content.segments ?? []).map(s => [s.id, s]));
  const kf = new Map((content.keyframes ?? []).map(k => [`${k.segment_id}:${k.frame}`, k]));
  return verifiedBoxes(content).map(b => { const s = segs.get(b.segment_id), k = kf.get(`${b.segment_id}:${b.frame}`);
    return { ...b, role: 'guidance', origin: k?.origin === 'manual' ? 'drawn' : 'tracked', event_decision: s?.decision ?? null, event_usability: s?.usability ?? null }; });
}

/** Training export: JSONL from approved, frozen revisions ONLY (never from drafts or live data). */
export function exportJsonl(db, datasetId, splits = ['train', 'validation']) {
  const d = db.prepare('select * from dataset_versions where id=?').get(datasetId);
  if (!d) throw new ApiError('NOT_FOUND');
  const lines = [], pinned = new Map((JSON.parse(d.manifest).members ?? []).map(x => [x.source_id, x.athlete_of_record]));
  for (const m of db.prepare('select * from dataset_members where dataset_id=? order by source_id').all(datasetId)) {
    if (!splits.includes(m.split)) continue;
    const rev = db.prepare('select content,digest,seq from annotation_revisions where id=?').get(m.revision_id);
    lines.push(JSON.stringify({ schema: 1, dataset_id: datasetId, dataset_digest: d.digest, source_sha256: m.sha256,
      split: m.split, revision_digest: rev.digest, label_roles: LABEL_ROLES,
      athlete_of_record: pinned.get(m.source_id) ?? null,   // source of truth: whose video this is
      annotations: JSON.parse(rev.content),
      box_guidance: boxGuidance(JSON.parse(rev.content)),   // guidance, not unquestionable truth (see LABEL_ROLES)
      // legacy name kept for existing readers: the same approved boxes (also guidance)
      verified_boxes: verifiedBoxes(JSON.parse(rev.content)) }));
  }
  return lines.join('\n') + (lines.length ? '\n' : '');
}

/** What the pipeline may see for blind evaluation: footage identity only — no labels, no splits. */
export function blindInferenceManifest(db, datasetId) {
  return db.prepare(`select s.sha256, s.byte_size, s.display_name from dataset_members m join sources s on s.id=m.source_id
    where m.dataset_id=? order by s.sha256`).all(datasetId);
}
