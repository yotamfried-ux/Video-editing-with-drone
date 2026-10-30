// Dataset freezing. A dataset version pins exact (sha256, approved revision) pairs and is immutable.
import { createHash, randomUUID } from 'node:crypto';
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';
import { digestOf, latestRevision } from './annotations.mjs';

export const DEFAULT_POLICY = { seed: 'sportreel-v1', ratios: { train: 0.7, validation: 0.15, test: 0.15 } };

/** Deterministic split by *group* (recording session) so near-duplicates never straddle splits. */
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
      const group = s.session_key ?? s.id;
      members.push({ source_id: id, sha256: s.sha256, revision_id: rev.id, revision_digest: rev.digest, group,
        split: heldOut.has(id) ? 'test' : splitFor(group, policy) });
    }
    // Group consistency: every member of a group takes the same split (test wins).
    const byGroup = new Map();
    for (const m of members) byGroup.set(m.group, (byGroup.get(m.group) ?? new Set()).add(m.split));
    for (const m of members) { const sp = byGroup.get(m.group); if (sp.has('test')) m.split = 'test'; }
    const manifest = { name, policy, members: members.map(({ group, ...m }) => m) };
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

/** Training export: JSONL from approved, frozen revisions ONLY (never from drafts or live data). */
export function exportJsonl(db, datasetId, splits = ['train', 'validation']) {
  const d = db.prepare('select * from dataset_versions where id=?').get(datasetId);
  if (!d) throw new ApiError('NOT_FOUND');
  const lines = [];
  for (const m of db.prepare('select * from dataset_members where dataset_id=? order by source_id').all(datasetId)) {
    if (!splits.includes(m.split)) continue;
    const rev = db.prepare('select content,digest,seq from annotation_revisions where id=?').get(m.revision_id);
    lines.push(JSON.stringify({ schema: 1, dataset_id: datasetId, dataset_digest: d.digest, source_sha256: m.sha256,
      split: m.split, revision_digest: rev.digest, annotations: JSON.parse(rev.content) }));
  }
  return lines.join('\n') + (lines.length ? '\n' : '');
}

/** What the pipeline may see for blind evaluation: footage identity only — no labels, no splits. */
export function blindInferenceManifest(db, datasetId) {
  return db.prepare(`select s.sha256, s.byte_size, s.display_name from dataset_members m join sources s on s.id=m.source_id
    where m.dataset_id=? order by s.sha256`).all(datasetId);
}
