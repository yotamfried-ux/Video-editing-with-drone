/**
 * CLI over the shared cleanup service (same code as POST /api/operator/storage/clean).
 *   MODE=inventory (default)  read-only inventory + active DB state
 *   MODE=delete               requires CONFIRM_DELETE_OLD_VIDEOS=DELETE_OLD_VIDEOS
 * Writes evidence (object counts/keys only, never secrets) to EVIDENCE_PATH.
 * Exit 0 only when inventory succeeded or a delete run finished with passing verification.
 */
import { writeFileSync } from 'node:fs';
import {
  advanceCleanup, CLEANUP_CONFIRMATION, previewCleanup, realStorage,
} from '../src/lib/video-storage-cleanup-runtime';
import { takeInventory } from '../src/lib/video-storage-cleanup';

async function main(): Promise<number> {
  const mode = (process.env.MODE ?? 'inventory').trim();
  const evidencePath = process.env.EVIDENCE_PATH;
  const evidence: Record<string, unknown> = { mode, started_at: new Date().toISOString() };
  const save = () => evidencePath && writeFileSync(evidencePath, JSON.stringify(evidence, null, 2));

  const preview = await previewCleanup();
  const keys = await takeInventory(realStorage);
  evidence.before = { ...preview, r2_video_keys: keys.r2_video_keys, reels_video_paths: keys.reels_video_paths,
    r2_unscoped_video_keys: keys.r2_unscoped_video_keys, r2_multipart_keys: keys.r2_multipart.map((u) => u.key) };
  console.log(JSON.stringify(preview, null, 2));
  save();
  if (mode !== 'delete') return 0;
  if (process.env.CONFIRM_DELETE_OLD_VIDEOS !== CLEANUP_CONFIRMATION) {
    throw new Error(`CONFIRM_DELETE_OLD_VIDEOS must equal ${CLEANUP_CONFIRMATION}`);
  }

  let run = await advanceCleanup({});
  while (run.status === 'running') {
    console.log(`progress ${run.progress.deleted}/${run.progress.initial_total}`);
    run = await advanceCleanup({ runId: run.run_id });
  }
  evidence.run = run;
  save();
  console.log(JSON.stringify(run, null, 2));
  console.log('VERIFY:', run.status === 'succeeded' ? 'PASS' : 'FAIL');
  return run.status === 'succeeded' ? 0 : 1;
}

main().then((code) => process.exit(code), (error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
