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

  const oldOwner = s.owner_athlete_id ?? null;
  const oldStatus = s.owner_status ?? 'unassigned';

  // No change needed
  if (oldOwner === owner_athlete_id && oldStatus === effectiveStatus) {
    return getCatalogOwner(db, sourceId);
  }

  const ts = now();
  tx(db, () => {
    db.prepare(`
      insert into source_owner_history(source_id, old_owner_id, new_owner_id, old_status, new_status, changed_by, reason, changed_at)
      values (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(sourceId, oldOwner, owner_athlete_id, oldStatus, effectiveStatus, changed_by, reason ?? null, ts);

    db.prepare(`
      update sources
      set owner_athlete_id = ?, owner_status = ?, owner_assigned_at = ?, owner_assigned_by = ?
      where id = ?
    `).run(owner_athlete_id, effectiveStatus, ts, changed_by, sourceId);

    // Sync cloud_objects if this source is linked to one
    db.prepare(`
      update cloud_objects
      set owner_athlete_id = ?, owner_status = ?
      where source_id = ?
    `).run(owner_athlete_id, effectiveStatus, sourceId);

    audit(db, changed_by, 'catalog_owner_set', sourceId, {
      old_owner_id: oldOwner,
      new_owner_id: owner_athlete_id,
      old_status: oldStatus,
      new_status: effectiveStatus,
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
        will_change: s.owner_athlete_id !== owner_athlete_id || (s.owner_status ?? 'unassigned') !== effectiveStatus,
      })),
    };
  }

  const ts = now();
  tx(db, () => {
    for (const s of sources) {
      const oldOwner = s.owner_athlete_id ?? null;
      const oldStatus = s.owner_status ?? 'unassigned';
      if (oldOwner === owner_athlete_id && oldStatus === effectiveStatus) continue;

      db.prepare(`
        insert into source_owner_history(source_id, old_owner_id, new_owner_id, old_status, new_status, changed_by, reason, changed_at)
        values (?, ?, ?, ?, ?, ?, ?, ?)
      `).run(s.id, oldOwner, owner_athlete_id, oldStatus, effectiveStatus, changed_by, reason ?? null, ts);

      db.prepare(`
        update sources
        set owner_athlete_id = ?, owner_status = ?, owner_assigned_at = ?, owner_assigned_by = ?
        where id = ?
      `).run(owner_athlete_id, effectiveStatus, ts, changed_by, s.id);

      db.prepare(`
        update cloud_objects
        set owner_athlete_id = ?, owner_status = ?
        where source_id = ?
      `).run(owner_athlete_id, effectiveStatus, s.id);

      audit(db, changed_by, 'catalog_owner_bulk_set', s.id, {
        old_owner_id: oldOwner,
        new_owner_id: owner_athlete_id,
        status: effectiveStatus,
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

  // Owned sources
  const ownedRows = db.prepare('select * from sources where owner_athlete_id = ? order by created_at desc').all(athleteId);
  const ownedIds = new Set(ownedRows.map(s => s.id));

  // Appearance sources
  const appearanceRows = db.prepare(`
    select distinct s.*
    from sources s
    join athlete_appearances a on a.source_id = s.id
    where a.athlete_id = ?
  `).all(athleteId);

  let combined = [];
  if (filter === 'owner') {
    combined = ownedRows;
  } else if (filter === 'appearance') {
    combined = appearanceRows;
  } else {
    // all: union
    const map = new Map();
    for (const s of ownedRows) map.set(s.id, s);
    for (const s of appearanceRows) if (!map.has(s.id)) map.set(s.id, s);
    combined = Array.from(map.values());
  }

  // Also query draft segment events for each source to count how many events this athlete performed
  const items = combined.map(s => {
    let eventsCount = 0;
    let trackQACount = 0;
    const draft = db.prepare('select content from annotation_drafts where source_id=?').get(s.id);
    if (draft) {
      try {
        const c = JSON.parse(draft.content);
        const athleteSegs = (c.segments || []).filter(seg => seg.athlete_id === athleteId);
        eventsCount = athleteSegs.length;
        const segIds = new Set(athleteSegs.map(seg => seg.id));
        const keyframes = (c.keyframes || []).filter(k => segIds.has(k.segment_id));
        trackQACount = keyframes.filter(k => k.verification_status === 'verified_correct').length;
      } catch {}
    }

    return {
      id: s.id,
      display_name: s.display_name,
      byte_size: s.byte_size,
      duration_ms: s.duration_ms,
      frame_count: s.frame_count,
      primary_sport_id: s.primary_sport_id,
      is_owner: s.owner_athlete_id === athleteId,
      owner_status: s.owner_athlete_id === athleteId ? s.owner_status : 'unassigned',
      has_appearance: db.prepare('select 1 from athlete_appearances where source_id=? and athlete_id=?').get(s.id, athleteId) != null,
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
} = {}) {
  const obj = db.prepare('select * from cloud_objects where id=?').get(cloudObjectId);
  if (!obj) throw new ApiError('NOT_FOUND', 'אובייקט ענן לא נמצא');

  if (owner_athlete_id != null) {
    const a = db.prepare('select id, label from athletes where id=?').get(owner_athlete_id);
    if (!a) throw new ApiError('NOT_FOUND', 'גולש לא קיים');
  }
  const effectiveStatus = status ?? (owner_athlete_id ? 'assigned' : 'unassigned');
  if (!OWNER_STATUSES.includes(effectiveStatus)) {
    throw new ApiError('INVALID_INPUT', `סטטוס שיוך לא תקין: ${effectiveStatus}`);
  }

  tx(db, () => {
    db.prepare('update cloud_objects set owner_athlete_id = ?, owner_status = ? where id = ?')
      .run(owner_athlete_id, effectiveStatus, cloudObjectId);

    if (obj.source_id) {
      setCatalogOwner(db, obj.source_id, {
        owner_athlete_id,
        status: effectiveStatus,
        reason,
        changed_by,
      });
    }
  });

  return {
    id: cloudObjectId,
    owner_athlete_id,
    owner_status: effectiveStatus,
    source_id: obj.source_id ?? null,
  };
}
