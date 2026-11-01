// Catalog ownership by athlete (independent from segment performer or visible appearances).
import { now, tx, audit } from './db.mjs';
import { ApiError } from './errors.mjs';

export const OWNER_STATUSES = ['unassigned', 'assigned', 'needs_review'];

function getSource(db, id) {
  const s = db.prepare('select * from sources where id=?').get(id);
  if (!s) throw new ApiError('NOT_FOUND', 'סרטון מקור לא נמצא');
  return s;
}

export function getCatalogOwner(db, sourceId) {
  const s = getSource(db, sourceId);
  const athlete = s.owner_athlete_id
    ? db.prepare('select id, label, notes, created_at from athletes where id=?').get(s.owner_athlete_id) ?? null
    : null;
  const history = db.prepare(
    `select h.*, a1.label as old_owner_label, a2.label as new_owner_label
     from source_owner_history h
     left join athletes a1 on a1.id = h.old_owner_id
     left join athletes a2 on a2.id = h.new_owner_id
     where h.source_id = ?
     order by h.id desc`
  ).all(sourceId);
  return {
    source_id: s.id,
    display_name: s.display_name,
    owner_athlete_id: s.owner_athlete_id ?? null,
    owner_status: s.owner_status ?? 'unassigned',
    owner_version: Number(s.owner_version ?? 0),
    owner_assigned_at: s.owner_assigned_at ?? null,
    owner_assigned_by: s.owner_assigned_by ?? null,
    athlete,
    history,
  };
}

export function setCatalogOwner(db, sourceId, {
  owner_athlete_id = null,
  status = undefined,
  reason = null,
  changed_by = 'operator',
  expected_version = undefined,
} = {}) {
  const s = getSource(db, sourceId);
  if (owner_athlete_id != null) {
    const a = db.prepare('select id, label from athletes where id=?').get(owner_athlete_id);
    if (!a) throw new ApiError('NOT_FOUND', 'גולש לא קיים');
  }
  const effectiveStatus = status ?? (owner_athlete_id ? 'assigned' : 'unassigned');
  if (!OWNER_STATUSES.includes(effectiveStatus)) {
    throw new ApiError('INVALID_INPUT', `סטטוס שיוך לא תקין: ${effectiveStatus}`);
  }

  const currentVersion = Number(s.owner_version ?? 0);
  if (expected_version === undefined || expected_version === null || typeof expected_version !== 'number' || !Number.isInteger(expected_version) || expected_version < 0) {
    throw new ApiError('INVALID_INPUT', 'חובה לספק expected_version כמספר שלם אי-שלילי');
  }
  if (expected_version !== currentVersion) {
    throw new ApiError('VERSION_CONFLICT', `שיוך הסרטון עודכן במקביל (גרסה נוכחית: ${currentVersion}, נשלח: ${expected_version}) — יש לרענן ולנסות שוב`);
  }

  const oldOwner = s.owner_athlete_id ?? null;
  const oldStatus = s.owner_status ?? 'unassigned';

  // No change needed
  if (oldOwner === owner_athlete_id && oldStatus === effectiveStatus) {
    return getCatalogOwner(db, sourceId);
  }

  const ts = now();
  const newVersion = currentVersion + 1;

  tx(db, () => {
    const upd = db.prepare(`
      update sources
      set owner_athlete_id = ?, owner_status = ?, owner_assigned_at = ?, owner_assigned_by = ?, owner_version = ?
      where id = ? and (owner_version = ? or (owner_version is null and ? = 0))
    `).run(owner_athlete_id, effectiveStatus, ts, changed_by, newVersion, sourceId, currentVersion, currentVersion);

    if (upd.changes === 0) {
      throw new ApiError('VERSION_CONFLICT', 'שיוך הסרטון עודכן במקביל על ידי משתמש אחר');
    }

    db.prepare(`
      insert into source_owner_history(source_id, old_owner_id, new_owner_id, old_status, new_status, changed_by, reason, changed_at, version)
      values (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(sourceId, oldOwner, owner_athlete_id, oldStatus, effectiveStatus, changed_by, reason ?? null, ts, newVersion);

    // Sync cloud_objects if this source is linked to one
    db.prepare(`
      update cloud_objects
      set owner_athlete_id = ?, owner_status = ?, owner_version = coalesce(owner_version, 0) + 1
      where source_id = ?
    `).run(owner_athlete_id, effectiveStatus, sourceId);

    audit(db, changed_by, 'catalog_owner_set', sourceId, {
      old_owner_id: oldOwner,
      new_owner_id: owner_athlete_id,
      old_status: oldStatus,
      new_status: effectiveStatus,
      version: newVersion,
      reason,
    });
  });

  return getCatalogOwner(db, sourceId);
}

export function bulkSetCatalogOwner(db, {
  source_ids = [],
  owner_athlete_id = null,
  status = undefined,
  reason = null,
  preview = false,
  changed_by = 'operator',
  expected_versions = undefined,
} = {}) {
  if (!Array.isArray(source_ids) || source_ids.length === 0) {
    throw new ApiError('INVALID_INPUT', 'חובה לספק רשימת מזהי סרטונים');
  }
  if (source_ids.length > 200) {
    throw new ApiError('INVALID_INPUT', 'ניתן לשייך עד 200 סרטונים בבת אחת');
  }
  if (owner_athlete_id != null) {
    const a = db.prepare('select id, label from athletes where id=?').get(owner_athlete_id);
    if (!a) throw new ApiError('NOT_FOUND', 'גולש לא קיים');
  }
  const effectiveStatus = status ?? (owner_athlete_id ? 'assigned' : 'unassigned');
  if (!OWNER_STATUSES.includes(effectiveStatus)) {
    throw new ApiError('INVALID_INPUT', `סטטוס שיוך לא תקין: ${effectiveStatus}`);
  }

  const sources = source_ids.map(id => getSource(db, id));
  const conflicts = sources.filter(s => s.owner_athlete_id && s.owner_athlete_id !== owner_athlete_id).map(s => ({
    source_id: s.id,
    display_name: s.display_name,
    current_owner_id: s.owner_athlete_id,
    current_status: s.owner_status,
    owner_version: Number(s.owner_version ?? 0),
  }));

  if (preview) {
    return {
      preview: true,
      total_count: sources.length,
      conflicts_count: conflicts.length,
      conflicts,
      target_owner_id: owner_athlete_id,
      target_status: effectiveStatus,
      items: sources.map(s => ({
        source_id: s.id,
        display_name: s.display_name,
        current_owner_id: s.owner_athlete_id ?? null,
        owner_version: Number(s.owner_version ?? 0),
        will_change: s.owner_athlete_id !== owner_athlete_id || (s.owner_status ?? 'unassigned') !== effectiveStatus,
      })),
    };
  }

  // When not preview, expected_versions is strictly mandatory for every source
  if (!expected_versions || typeof expected_versions !== 'object') {
    throw new ApiError('INVALID_INPUT', 'חובה לספק expected_versions עבור כל הסרטונים בשיוך מרוכז');
  }

  const expMap = Array.isArray(expected_versions)
    ? new Map(expected_versions.map(x => [x.source_id, x.expected_version]))
    : new Map(Object.entries(expected_versions).map(([k, v]) => [k, typeof v === 'object' && v !== null ? v.expected_version : v]));

  for (const s of sources) {
    const exp = expMap.get(s.id);
    if (exp === undefined || exp === null || typeof exp !== 'number' || !Number.isInteger(exp) || exp < 0) {
      throw new ApiError('INVALID_INPUT', `חסרה גרסה צפויה תקינה (expected_version) עבור הסרטון "${s.display_name}"`);
    }
    if (exp !== Number(s.owner_version ?? 0)) {
      throw new ApiError('VERSION_CONFLICT', `הסרטון "${s.display_name}" עודכן במקביל (גרסה נוכחית: ${s.owner_version ?? 0}, נשלח: ${exp}) — פעולת השיוך המרוכז בוטלה`);
    }
  }

  const ts = now();
  tx(db, () => {
    for (const s of sources) {
      const currentVersion = Number(s.owner_version ?? 0);
      const oldOwner = s.owner_athlete_id ?? null;
      const oldStatus = s.owner_status ?? 'unassigned';
      if (oldOwner === owner_athlete_id && oldStatus === effectiveStatus) continue;

      const newVersion = currentVersion + 1;
      const upd = db.prepare(`
        update sources
        set owner_athlete_id = ?, owner_status = ?, owner_assigned_at = ?, owner_assigned_by = ?, owner_version = ?
        where id = ? and (owner_version = ? or (owner_version is null and ? = 0))
      `).run(owner_athlete_id, effectiveStatus, ts, changed_by, newVersion, s.id, currentVersion, currentVersion);

      if (upd.changes === 0) {
        throw new ApiError('VERSION_CONFLICT', `הסרטון "${s.display_name}" עודכן במקביל — פעולת השיוך המרוכז בוטלה`);
      }

      db.prepare(`
        insert into source_owner_history(source_id, old_owner_id, new_owner_id, old_status, new_status, changed_by, reason, changed_at, version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).run(s.id, oldOwner, owner_athlete_id, oldStatus, effectiveStatus, changed_by, reason ?? null, ts, newVersion);

      db.prepare(`
        update cloud_objects
        set owner_athlete_id = ?, owner_status = ?, owner_version = coalesce(owner_version, 0) + 1
        where source_id = ?
      `).run(owner_athlete_id, effectiveStatus, s.id);

      audit(db, changed_by, 'catalog_owner_bulk_set', s.id, {
        old_owner_id: oldOwner,
        new_owner_id: owner_athlete_id,
        status: effectiveStatus,
        version: newVersion,
        reason,
      });
    }
  });

  return {
    success: true,
    updated_count: sources.length,
    conflicts_overridden: conflicts.length,
    target_owner_id: owner_athlete_id,
    target_status: effectiveStatus,
  };
}

export function listAthleteSources(db, athleteId, { filter = 'all' } = {}) {
  const athlete = db.prepare('select * from athletes where id=?').get(athleteId);
  if (!athlete) throw new ApiError('NOT_FOUND', 'גולש לא קיים');

  // 1. Sources where this athlete is the catalog owner
  const ownedRows = db.prepare(`
    select * from sources
    where owner_athlete_id = ?
    order by created_at desc
  `).all(athleteId);

  // 2. Sources where this athlete appears or has events (distinct source_id)
  const appearanceRows = db.prepare(`
    select s.*
    from sources s
    where s.id in (
      select source_id from athlete_appearances where athlete_id = ?
    ) or s.id in (
      select distinct d.source_id
      from annotation_drafts d
      where json_extract(d.content, '$.segments') like ?
    )
    order by s.created_at desc
  `).all(athleteId, `%"athlete_id":"${athleteId}"%`);

  let candidateMap = new Map();

  if (filter === 'owner') {
    for (const r of ownedRows) candidateMap.set(r.id, { ...r, is_owner: true, is_appearance: false });
  } else if (filter === 'appearance') {
    for (const r of appearanceRows) candidateMap.set(r.id, { ...r, is_owner: r.owner_athlete_id === athleteId, is_appearance: true });
  } else {
    // all
    for (const r of ownedRows) candidateMap.set(r.id, { ...r, is_owner: true, is_appearance: false });
    for (const r of appearanceRows) {
      if (candidateMap.has(r.id)) {
        candidateMap.get(r.id).is_appearance = true;
      } else {
        candidateMap.set(r.id, { ...r, is_owner: r.owner_athlete_id === athleteId, is_appearance: true });
      }
    }
  }

  const items = Array.from(candidateMap.values()).map(s => {
    const draft = db.prepare('select content from annotation_drafts where source_id=?').get(s.id);
    let eventsCount = 0;
    let trackQACount = 0;
    if (draft?.content) {
      try {
        const c = JSON.parse(draft.content);
        const segs = (c.segments || []).filter(seg => seg.athlete_id === athleteId);
        eventsCount = segs.length;
        const keyframes = (c.keyframes || []).filter(k => segs.some(seg => seg.id === k.segment_id));
        trackQACount = keyframes.filter(k => k.verification_status === 'verified_correct').length;
      } catch {}
    }
    return {
      id: s.id,
      display_name: s.display_name,
      duration_ms: s.duration_ms,
      byte_size: s.byte_size,
      primary_sport_id: s.primary_sport_id,
      owner_status: s.owner_status,
      owner_version: Number(s.owner_version ?? 0),
      is_owner: s.is_owner,
      is_appearance: s.is_appearance,
      events_count: eventsCount,
      track_qa_count: trackQACount,
      thumb_path: s.thumb_path,
      created_at: s.created_at,
    };
  });

  return {
    athlete,
    filter,
    totals: {
      owned_sources: ownedRows.length,
      appearance_sources: appearanceRows.length,
      total_unique_sources: filter === 'owner' ? ownedRows.length : filter === 'appearance' ? appearanceRows.length : items.length,
    },
    items,
  };
}

export function setCloudObjectCatalogOwner(db, cloudObjectId, {
  owner_athlete_id = null,
  status = undefined,
  reason = null,
  changed_by = 'operator',
  expected_version = undefined,
} = {}) {
  const obj = db.prepare('select * from cloud_objects where id=?').get(cloudObjectId);
  if (!obj) throw new ApiError('NOT_FOUND', 'אובייקט ענן לא נמצא');

  if (expected_version === undefined || expected_version === null || typeof expected_version !== 'number' || !Number.isInteger(expected_version) || expected_version < 0) {
    throw new ApiError('INVALID_INPUT', 'חובה לספק expected_version כמספר שלם אי-שלילי');
  }

  const currentVersion = Number(obj.owner_version ?? 0);
  if (expected_version !== currentVersion) {
    throw new ApiError('VERSION_CONFLICT', `אובייקט הענן עודכן במקביל (גרסה נוכחית: ${currentVersion}, נשלח: ${expected_version}) — יש לרענן ולנסות שוב`);
  }

  if (owner_athlete_id != null) {
    const a = db.prepare('select id, label from athletes where id=?').get(owner_athlete_id);
    if (!a) throw new ApiError('NOT_FOUND', 'גולש לא קיים');
  }
  const effectiveStatus = status ?? (owner_athlete_id ? 'assigned' : 'unassigned');
  if (!OWNER_STATUSES.includes(effectiveStatus)) {
    throw new ApiError('INVALID_INPUT', `סטטוס שיוך לא תקין: ${effectiveStatus}`);
  }

  const newCloudVersion = currentVersion + 1;
  const ts = now();

  tx(db, () => {
    const upd = db.prepare('update cloud_objects set owner_athlete_id = ?, owner_status = ?, owner_version = ? where id = ? and (owner_version = ? or (owner_version is null and ? = 0))')
      .run(owner_athlete_id, effectiveStatus, newCloudVersion, cloudObjectId, currentVersion, currentVersion);

    if (upd.changes === 0) {
      throw new ApiError('VERSION_CONFLICT', 'אובייקט הענן עודכן במקביל על ידי משתמש אחר');
    }

    if (obj.source_id) {
      const src = db.prepare('select * from sources where id=?').get(obj.source_id);
      if (src) {
        const srcOldOwner = src.owner_athlete_id ?? null;
        const srcOldStatus = src.owner_status ?? 'unassigned';
        const srcCurrentVer = Number(src.owner_version ?? 0);
        const srcNewVer = srcCurrentVer + 1;

        db.prepare(`
          update sources
          set owner_athlete_id = ?, owner_status = ?, owner_assigned_at = ?, owner_assigned_by = ?, owner_version = ?
          where id = ?
        `).run(owner_athlete_id, effectiveStatus, ts, changed_by, srcNewVer, obj.source_id);

        db.prepare(`
          insert into source_owner_history(source_id, old_owner_id, new_owner_id, old_status, new_status, changed_by, reason, changed_at, version)
          values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).run(obj.source_id, srcOldOwner, owner_athlete_id, srcOldStatus, effectiveStatus, changed_by, reason ?? 'שיוך מתוך קטלוג ענן', ts, srcNewVer);

        audit(db, changed_by, 'catalog_owner_set', obj.source_id, {
          old_owner_id: srcOldOwner,
          new_owner_id: owner_athlete_id,
          old_status: srcOldStatus,
          new_status: effectiveStatus,
          version: srcNewVer,
          reason,
        });
      }
    }
  });

  return {
    id: cloudObjectId,
    owner_athlete_id,
    owner_status: effectiveStatus,
    owner_version: newCloudVersion,
    source_id: obj.source_id ?? null,
  };
}
