// Sport registry + sport-scoped event taxonomy (spec §18). Sports and event types are DATA, not code:
// adding one is a registry write (audited, bumps the sport's taxonomy_version), never an application change.
// Retiring an event type only hides it from pickers — existing annotations stay valid and readable.
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';

/** Initial reference data. Surfing keeps today's event keys so legacy data stays valid. Mirrored in db/migrations/0002_sports.sql. */
export const SEED_SPORTS = [
  { id: 'surfing', name_he: 'גלישה', name_en: 'Surfing', events: [['wave_ride', 'רכיבה על גל', 'Wave ride'], ['failed_takeoff', 'עמידה כושלת', 'Failed takeoff'], ['wipeout', 'נפילה', 'Wipeout'], ['paddle_out', 'חתירה החוצה', 'Paddle out'], ['other', 'אחר', 'Other']] },
  { id: 'football', name_he: 'כדורגל', name_en: 'Football', events: [['shot', 'בעיטה', 'Shot'], ['pass', 'מסירה', 'Pass'], ['goal', 'שער', 'Goal'], ['other', 'אחר', 'Other']] },
  { id: 'basketball', name_he: 'כדורסל', name_en: 'Basketball', events: [['shot', 'זריקה', 'Shot'], ['assist', 'בישול', 'Assist'], ['rebound', 'ריבאונד', 'Rebound'], ['other', 'אחר', 'Other']] },
  { id: 'tennis', name_he: 'טניס', name_en: 'Tennis', events: [['serve', 'הגשה', 'Serve'], ['rally', 'חילופי מכות', 'Rally'], ['point', 'נקודה', 'Point'], ['other', 'אחר', 'Other']] },
];
/** Event keys that existed before the registry; accepted on sources whose sport is still unclassified (never assumed to be surfing). */
export const LEGACY_EVENT_KEYS = ['wave_ride', 'failed_takeoff', 'wipeout', 'paddle_out', 'other'];

const KEY = /^[a-z][a-z0-9_]{1,31}$/;
const ATTR = /^[a-z][a-z0-9_]{0,31}$/;

export function seedSports(db) {
  const t = now();
  for (const s of SEED_SPORTS) {
    db.prepare('insert or ignore into sports(id,name_he,name_en,enabled,taxonomy_version,created_at) values(?,?,?,1,1,?)').run(s.id, s.name_he, s.name_en, t);
    for (const [key, he, en] of s.events) {
      db.prepare("insert or ignore into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values(?,?,?,?,null,'[]',1,1,?)").run(s.id, key, he, en, t);
    }
  }
}

export function listSports(db) {
  const types = db.prepare('select * from sport_event_types order by sport_id, since_version, key').all();
  return db.prepare('select * from sports order by created_at, id').all().map(s => ({
    ...s, enabled: !!s.enabled,
    event_types: types.filter(e => e.sport_id === s.id).map(e => ({ key: e.key, label_he: e.label_he, label_en: e.label_en, parent_key: e.parent_key,
      required_attrs: JSON.parse(e.required_attrs), enabled: !!e.enabled, since_version: e.since_version })),
  }));
}

const getSport = (db, id) => { const s = db.prepare('select * from sports where id=?').get(id); if (!s) throw new ApiError('NOT_FOUND', `ענף לא קיים: ${id}`); return s; };
const bump = (db, id) => db.prepare('update sports set taxonomy_version=taxonomy_version+1 where id=?').run(id);

export function addSport(db, { id, name_he, name_en, enabled = true }) {
  if (!KEY.test(id ?? '') || id === 'unknown') throw new ApiError('INVALID_INPUT', 'מזהה ענף: אותיות לטיניות קטנות, ספרות וקו תחתון');
  if (!String(name_he ?? '').trim() || !String(name_en ?? '').trim()) throw new ApiError('INVALID_INPUT', 'שם בעברית ובאנגלית נדרשים');
  if (db.prepare('select 1 from sports where id=?').get(id)) throw new ApiError('INVALID_INPUT', 'ענף כבר קיים');
  tx(db, () => {
    db.prepare('insert into sports(id,name_he,name_en,enabled,taxonomy_version,created_at) values(?,?,?,?,1,?)').run(id, name_he.trim(), name_en.trim(), enabled ? 1 : 0, now());
    audit(db, 'operator', 'sport_added', id, { name_he, name_en });
  });
  return listSports(db).find(s => s.id === id);
}

export function setSportEnabled(db, id, enabled) {
  getSport(db, id);
  db.prepare('update sports set enabled=? where id=?').run(enabled ? 1 : 0, id);
  audit(db, 'operator', 'sport_enabled_changed', id, { enabled: !!enabled });
}

export function addEventType(db, sportId, { key, label_he, label_en, parent_key = null, required_attrs = [] }) {
  getSport(db, sportId);
  if (!KEY.test(key ?? '')) throw new ApiError('INVALID_INPUT', 'מפתח אירוע לא תקין');
  if (!String(label_he ?? '').trim() || !String(label_en ?? '').trim()) throw new ApiError('INVALID_INPUT', 'תווית בעברית ובאנגלית נדרשת');
  if (!Array.isArray(required_attrs) || !required_attrs.every(a => ATTR.test(a))) throw new ApiError('INVALID_INPUT', 'שדות חובה לא תקינים');
  if (parent_key != null && !db.prepare('select 1 from sport_event_types where sport_id=? and key=?').get(sportId, parent_key)) throw new ApiError('INVALID_INPUT', 'קטגוריית אב לא קיימת');
  if (db.prepare('select 1 from sport_event_types where sport_id=? and key=?').get(sportId, key)) throw new ApiError('INVALID_INPUT', 'סוג אירוע כבר קיים בענף');
  return tx(db, () => {
    bump(db, sportId);
    const v = getSport(db, sportId).taxonomy_version;
    db.prepare('insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values(?,?,?,?,?,?,1,?,?)')
      .run(sportId, key, label_he.trim(), label_en.trim(), parent_key, JSON.stringify(required_attrs), v, now());
    audit(db, 'operator', 'event_type_added', `${sportId}/${key}`, { taxonomy_version: v });
    return { sport_id: sportId, key, taxonomy_version: v };
  });
}

export function setEventTypeEnabled(db, sportId, key, enabled) {
  if (!db.prepare('select 1 from sport_event_types where sport_id=? and key=?').get(sportId, key)) throw new ApiError('NOT_FOUND');
  return tx(db, () => {
    db.prepare('update sport_event_types set enabled=? where sport_id=? and key=?').run(enabled ? 1 : 0, sportId, key);
    bump(db, sportId);
    audit(db, 'operator', enabled ? 'event_type_enabled' : 'event_type_retired', `${sportId}/${key}`, {});
    return { taxonomy_version: getSport(db, sportId).taxonomy_version };
  });
}

/** Effective sport of a segment: its own explicit sport, else the source's confirmed sport, else null (= unclassified). */
export const effectiveSport = (source, seg) => seg.sport_id ?? source.primary_sport_id ?? null;

/** Server-side sport/event compatibility (also the UI's source of truth for pickers). Retired types stay valid. */
export function validateSegmentTaxonomy(db, source, seg, cache = new Map()) {
  const sport = effectiveSport(source, seg);
  if (seg.sport_id != null) {
    const k0 = `s:${seg.sport_id}`;
    if (!cache.has(k0)) cache.set(k0, !!db.prepare('select 1 from sports where id=?').get(seg.sport_id));
    if (!cache.get(k0)) throw new ApiError('INVALID_INPUT', `ענף לא קיים: ${seg.sport_id}`);
  }
  if (sport == null) {
    if (!LEGACY_EVENT_KEYS.includes(seg.event_type)) throw new ApiError('SPORT_EVENT_MISMATCH', `המקור ללא ענף מאושר; סוג האירוע "${seg.event_type}" דורש סיווג ענף`);
    return;
  }
  const k = `e:${sport}:${seg.event_type}`;
  if (!cache.has(k)) cache.set(k, db.prepare('select required_attrs from sport_event_types where sport_id=? and key=?').get(sport, seg.event_type) ?? null);
  const et = cache.get(k);
  if (!et) throw new ApiError('SPORT_EVENT_MISMATCH', `סוג האירוע "${seg.event_type}" אינו שייך לענף "${sport}"`);
  if (seg.attrs != null && (typeof seg.attrs !== 'object' || Array.isArray(seg.attrs) || !Object.values(seg.attrs).every(v => ['string', 'number', 'boolean'].includes(typeof v)))) {
    throw new ApiError('INVALID_INPUT', 'מאפייני אירוע לא תקינים');
  }
  if (seg.decision === 'include') {
    for (const a of JSON.parse(et.required_attrs)) {
      const v = seg.attrs?.[a];
      if (v == null || v === '') throw new ApiError('INVALID_INPUT', `שדה חובה חסר לאירוע "${seg.event_type}": ${a}`);
    }
  }
}

/** Resolved sport is stamped into stored content so frozen revisions are self-describing for the blind evaluator. */
export function stampResolved(content, source) {
  for (const s of content.segments) {
    const sp = effectiveSport(source, s);
    if (sp != null) s.resolved_sport_id = sp; else delete s.resolved_sport_id;
  }
  return content;
}

/** Taxonomy versions in force for the sports a document uses; pinned on approved revisions. */
export function taxonomyVersionsFor(db, content) {
  const out = {};
  for (const id of new Set(content.segments.map(s => s.resolved_sport_id).filter(Boolean))) out[id] = getSport(db, id).taxonomy_version;
  return out;
}

const draftRow = (db, id) => db.prepare('select * from annotation_drafts where source_id=?').get(id);

/**
 * Operator (re)classification of one source. Never touches approved revisions or frozen datasets.
 * Draft segments whose event type does not exist in the new sport are reported, never deleted:
 * either acknowledge (they stay and block saving until fixed) or pass an explicit `remap` {old_key:new_key}.
 */
export function setSourceSport(db, sourceId, sportId, { reason = '', acknowledgeIncompatible = false, remap = null, actor = 'operator' } = {}) {
  const src = db.prepare('select * from sources where id=?').get(sourceId);
  if (!src) throw new ApiError('NOT_FOUND');
  if (sportId != null) getSport(db, sportId);
  return tx(db, () => {
    const d = draftRow(db, sourceId);
    const content = d ? JSON.parse(d.content) : null;
    const segsToCheck = (content?.segments ?? []).filter(s => s.sport_id == null);
    const known = new Map();
    const ok = key => {
      if (sportId == null) return LEGACY_EVENT_KEYS.includes(key);
      if (!known.has(key)) known.set(key, !!db.prepare('select 1 from sport_event_types where sport_id=? and key=?').get(sportId, key));
      return known.get(key);
    };
    let remapped = 0;
    if (content && remap) {
      for (const [from, to] of Object.entries(remap)) if (!ok(to)) throw new ApiError('SPORT_EVENT_MISMATCH', `יעד המיפוי "${to}" אינו שייך לענף`);
      for (const s of segsToCheck) if (!ok(s.event_type) && remap[s.event_type]) { s.event_type = remap[s.event_type]; remapped++; }
    }
    const incompatible = segsToCheck.filter(s => !ok(s.event_type)).map(s => ({ id: s.id, event_type: s.event_type }));
    if (incompatible.length && !acknowledgeIncompatible) throw Object.assign(new ApiError('SPORT_INCOMPATIBLE'), { incompatible });
    if (content) {
      stampResolved(content, { ...src, primary_sport_id: sportId });
      db.prepare('update annotation_drafts set content=?, version=?, updated_at=? where source_id=?')
        .run(JSON.stringify(content), d.version + 1, now(), sourceId);
    }
    db.prepare('update sources set primary_sport_id=? where id=?').run(sportId, sourceId);
    audit(db, actor, 'source_sport_set', sourceId, { from: src.primary_sport_id ?? null, to: sportId, reason, remapped, incompatible_kept: incompatible.length });
    return { source_id: sourceId, primary_sport_id: sportId, remapped, incompatible };
  });
}

/** Bulk classification: each source succeeds or is reported individually (sources needing remapping are skipped, not forced). */
export function bulkSetSport(db, ids, sportId, reason = '') {
  if (!Array.isArray(ids) || !ids.length) throw new ApiError('INVALID_INPUT');
  const done = [], skipped = [];
  for (const id of ids) {
    try { setSourceSport(db, id, sportId, { reason }); done.push(id); }
    catch (e) { if (!(e instanceof ApiError)) throw e; skipped.push({ id, code: e.code, incompatible: e.incompatible }); }
  }
  return { updated: done.length, skipped };
}
