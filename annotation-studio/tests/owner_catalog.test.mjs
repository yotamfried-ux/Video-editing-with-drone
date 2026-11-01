// Tests for Precision Studio V2: catalog ownership by athlete and Surfer Workspace.
import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { newCtx, makeVideo, tmp, seg, kf } from './helpers.mjs';
import { reconcile } from '../server/ingest.mjs';
import * as A from '../server/annotations.mjs';
import * as Catalog from '../server/catalog_owner.mjs';
import { ApiError } from '../server/errors.mjs';

async function withSource() {
  const ctx = newCtx();
  const raw = path.join(tmp('ops-'), 'raw');
  makeVideo(path.join(raw, 'a.mp4'), { tag: 'clip-a' });
  makeVideo(path.join(raw, 'b.mp4'), { tag: 'clip-b' });
  await reconcile(ctx, { roots: [{ dir: raw, prefix: 'raw/' }] });
  const sources = ctx.db.prepare('select * from sources order by id').all();
  return { ctx, db: ctx.db, src1: sources[0], src2: sources[1] };
}

test('video assigned to athlete without segments; Surfer Workspace displays video with 0 events', async () => {
  const { db, src1 } = await withSource();
  const surferA = A.createAthlete(db, 'Surfer Alpha');

  // Initial state: unassigned
  const initOwner = Catalog.getCatalogOwner(db, src1.id);
  assert.equal(initOwner.owner_athlete_id, null);
  assert.equal(initOwner.owner_status, 'unassigned');

  // Assign to Surfer Alpha
  const updated = Catalog.setCatalogOwner(db, src1.id, {
    owner_athlete_id: surferA.id,
    status: 'assigned',
    reason: 'Initial assignment by coach',
    changed_by: 'coach_yotam',
  });

  assert.equal(updated.owner_athlete_id, surferA.id);
  assert.equal(updated.owner_status, 'assigned');
  assert.equal(updated.owner_assigned_by, 'coach_yotam');
  assert.equal(updated.athlete.label, 'Surfer Alpha');
  assert.equal(updated.history.length, 1);
  assert.equal(updated.history[0].new_owner_id, surferA.id);
  assert.equal(updated.history[0].reason, 'Initial assignment by coach');

  // Verify Surfer Workspace returns this video even though it has 0 segments!
  const workspace = Catalog.listAthleteSources(db, surferA.id, { filter: 'owner' });
  assert.equal(workspace.totals.owned_sources, 1);
  assert.equal(workspace.items.length, 1);
  assert.equal(workspace.items[0].id, src1.id);
  assert.equal(workspace.items[0].is_owner, true);
  assert.equal(workspace.items[0].events_count, 0); // 0 events!
});

test('reassignment records audit history in source_owner_history; history is immutable', async () => {
  const { db, src1 } = await withSource();
  const surferA = A.createAthlete(db, 'Surfer Alpha');
  const surferB = A.createAthlete(db, 'Surfer Beta');

  // 1. Assign to Surfer Alpha
  Catalog.setCatalogOwner(db, src1.id, { owner_athlete_id: surferA.id });

  // 2. Reassign to Surfer Beta with explicit reason
  Catalog.setCatalogOwner(db, src1.id, {
    owner_athlete_id: surferB.id,
    reason: 'Camera was tracking Beta during second heat',
    changed_by: 'annotator_1',
  });

  const ownerInfo = Catalog.getCatalogOwner(db, src1.id);
  assert.equal(ownerInfo.owner_athlete_id, surferB.id);
  assert.equal(ownerInfo.history.length, 2);
  assert.equal(ownerInfo.history[0].old_owner_id, surferA.id);
  assert.equal(ownerInfo.history[0].new_owner_id, surferB.id);
  assert.equal(ownerInfo.history[0].reason, 'Camera was tracking Beta during second heat');

  // Verify immutability of source_owner_history
  const histId = ownerInfo.history[0].id;
  assert.throws(
    () => db.prepare("update source_owner_history set reason='tampered' where id=?").run(histId),
    /IMMUTABLE/
  );
  assert.throws(
    () => db.prepare('delete from source_owner_history where id=?').run(histId),
    /IMMUTABLE/
  );
});

test('bulk assignment with preview and conflict warnings', async () => {
  const { db, src1, src2 } = await withSource();
  const surferA = A.createAthlete(db, 'Surfer Alpha');
  const surferB = A.createAthlete(db, 'Surfer Beta');

  // Pre-assign src1 to Alpha
  Catalog.setCatalogOwner(db, src1.id, { owner_athlete_id: surferA.id });

  // Dry preview assigning both src1 and src2 to Beta
  const preview = Catalog.bulkSetCatalogOwner(db, {
    source_ids: [src1.id, src2.id],
    owner_athlete_id: surferB.id,
    preview: true,
  });

  assert.equal(preview.preview, true);
  assert.equal(preview.total_count, 2);
  assert.equal(preview.conflicts_count, 1);
  assert.equal(preview.conflicts[0].source_id, src1.id);
  assert.equal(preview.conflicts[0].current_owner_id, surferA.id);

  // Apply bulk assignment
  const applied = Catalog.bulkSetCatalogOwner(db, {
    source_ids: [src1.id, src2.id],
    owner_athlete_id: surferB.id,
    reason: 'Bulk heat assignment',
    preview: false,
  });

  assert.equal(applied.success, true);
  assert.equal(applied.updated_count, 2);

  // Verify both now belong to Beta
  assert.equal(Catalog.getCatalogOwner(db, src1.id).owner_athlete_id, surferB.id);
  assert.equal(Catalog.getCatalogOwner(db, src2.id).owner_athlete_id, surferB.id);
});

test('three-way athlete independence: catalog owner != visible appearance != event performer', async () => {
  const { db, src1 } = await withSource();
  const surferOwner = A.createAthlete(db, 'Owner Surfer (A)');
  const surferVisible = A.createAthlete(db, 'Background Surfer (B)');
  const surferPerformer = A.createAthlete(db, 'Action Performer (C)');

  // 1. Assign video ownership to Surfer A
  Catalog.setCatalogOwner(db, src1.id, { owner_athlete_id: surferOwner.id });

  // 2. Mark Surfer B as visible in the video
  db.prepare('insert into athlete_appearances(id, athlete_id, source_id, created_at) values (?, ?, ?, ?)')
    .run('app-1', surferVisible.id, src1.id, new Date().toISOString());

  // 3. Mark event performed by Surfer C
  const c = A.emptyContent();
  c.segments.push(seg('seg-c', 10, 80, {
    athlete_id: surferPerformer.id,
    event_type: 'wave_ride',
    decision: 'include',
    usability: 'usable',
  }));
  c.reviewed_ranges.push({ start_frame: 0, end_frame: 100 });
  A.saveDraft(db, src1.id, 0, c);

  // 4. Approve Ground Truth revision
  const approved = A.approve(db, src1.id, { expectedVersion: 1, reason: 'Ground truth qualified' });
  assert.equal(approved.revision.seq, 1);

  // 5. Verify all three relationships remain strictly isolated
  const catalogState = Catalog.getCatalogOwner(db, src1.id);
  assert.equal(catalogState.owner_athlete_id, surferOwner.id);

  const ownerWorkspace = Catalog.listAthleteSources(db, surferOwner.id, { filter: 'owner' });
  assert.equal(ownerWorkspace.items.length, 1);
  assert.equal(ownerWorkspace.items[0].id, src1.id);

  const visibleWorkspace = Catalog.listAthleteSources(db, surferVisible.id, { filter: 'appearance' });
  assert.equal(visibleWorkspace.items.length, 1);
  assert.equal(visibleWorkspace.items[0].id, src1.id);

  const performerWorkspace = Catalog.listAthleteSources(db, surferPerformer.id, { filter: 'all' });
  assert.equal(performerWorkspace.items[0].events_count, 1);

  // Ensure owner was NOT overwritten to performer
  assert.notEqual(catalogState.owner_athlete_id, surferPerformer.id);
  // Ensure visible athlete was NOT marked as owner
  assert.notEqual(catalogState.owner_athlete_id, surferVisible.id);
});

test('optimistic concurrency control: valid expected_version increments version; stale expected_version throws VERSION_CONFLICT', async () => {
  const { db, src1 } = await withSource();
  const surferA = A.createAthlete(db, 'Surfer Alpha');
  const surferB = A.createAthlete(db, 'Surfer Beta');

  // Initial version is 0
  const initial = Catalog.getCatalogOwner(db, src1.id);
  assert.equal(initial.owner_version, 0);

  // Update with expected_version = 0 -> succeeds, bumps version to 1
  const v1 = Catalog.setCatalogOwner(db, src1.id, {
    owner_athlete_id: surferA.id,
    expected_version: 0,
    changed_by: 'user_1',
  });
  assert.equal(v1.owner_version, 1);
  assert.equal(v1.owner_athlete_id, surferA.id);

  // Stale update: attempting to update with expected_version = 0 again MUST fail with 409 VERSION_CONFLICT!
  assert.throws(
    () => Catalog.setCatalogOwner(db, src1.id, {
      owner_athlete_id: surferB.id,
      expected_version: 0,
      changed_by: 'user_stale',
    }),
    (err) => {
      assert.equal(err.code, 'VERSION_CONFLICT');
      assert.equal(err.status, 409);
      return true;
    }
  );

  // Video was NOT modified by the rejected stale request
  const afterFailed = Catalog.getCatalogOwner(db, src1.id);
  assert.equal(afterFailed.owner_version, 1);
  assert.equal(afterFailed.owner_athlete_id, surferA.id);

  // Update with correct expected_version = 1 -> succeeds, bumps version to 2
  const v2 = Catalog.setCatalogOwner(db, src1.id, {
    owner_athlete_id: surferB.id,
    expected_version: 1,
    changed_by: 'user_2',
  });
  assert.equal(v2.owner_version, 2);
  assert.equal(v2.owner_athlete_id, surferB.id);
  assert.equal(v2.history[0].version, 2);
});

test('bulk assignment optimistic concurrency: concurrent modification of single video aborts entire transaction with rollback', async () => {
  const { db, src1, src2 } = await withSource();
  const surferA = A.createAthlete(db, 'Surfer Alpha');
  const surferB = A.createAthlete(db, 'Surfer Beta');

  // Get preview
  const preview = Catalog.bulkSetCatalogOwner(db, {
    source_ids: [src1.id, src2.id],
    owner_athlete_id: surferA.id,
    preview: true,
  });
  const expectedVersions = preview.items.map(it => ({ source_id: it.source_id, expected_version: it.owner_version }));

  // Simulate concurrent modification to src2 before bulk apply
  Catalog.setCatalogOwner(db, src2.id, {
    owner_athlete_id: surferB.id,
    expected_version: 0,
    changed_by: 'concurrent_user',
  });

  // Attempt to apply bulk assignment using stale expectedVersions
  assert.throws(
    () => Catalog.bulkSetCatalogOwner(db, {
      source_ids: [src1.id, src2.id],
      owner_athlete_id: surferA.id,
      preview: false,
      expected_versions: expectedVersions,
    }),
    (err) => {
      assert.equal(err.code, 'VERSION_CONFLICT');
      return true;
    }
  );

  // ATOMICITY: src1 must NOT have been changed either! Entire batch rolled back!
  assert.equal(Catalog.getCatalogOwner(db, src1.id).owner_athlete_id, null);
  assert.equal(Catalog.getCatalogOwner(db, src2.id).owner_athlete_id, surferB.id);
});
