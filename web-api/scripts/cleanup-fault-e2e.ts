/**
 * Scenario D on real infrastructure: force one real cleanup stage (Supabase reels removal)
 * to fail through the same service, prove the run is reported failed (never clean), then
 * prove a retry with the real deps completes and verifies. Uses only test-scoped state
 * that the caller seeded; fault injection exists only in this script, never in the API.
 */
import { writeFileSync } from 'node:fs';
import { advanceCleanup, realStorage } from '../src/lib/video-storage-cleanup-runtime';
import type { CleanupStorage } from '../src/lib/video-storage-cleanup';

async function drive(storage?: CleanupStorage) {
  let run = await advanceCleanup({ storage });
  while (run.status === 'running') run = await advanceCleanup({ runId: run.run_id, storage });
  return run;
}

async function main(): Promise<number> {
  const faulty: CleanupStorage = {
    ...realStorage,
    removeSupabaseFiles: async () => { throw new Error('injected failure: supabase reels stage'); },
  };
  const failed = await drive(faulty);
  const problems: string[] = [];
  if (failed.status !== 'failed') problems.push(`faulted run status was ${failed.status}, expected failed`);
  if (/Video storage is clean/.test(failed.message)) problems.push('failure message claims clean');
  if (failed.active_state_after !== null && failed.status === 'failed' && failed.phase === 'succeeded') problems.push('failed run marked succeeded');
  const retried = await drive();
  if (retried.status !== 'succeeded') problems.push(`retry status was ${retried.status}: ${retried.error ?? retried.failures.join('; ')}`);
  const evidence = { faulted: failed, retry: retried, problems };
  if (process.env.EVIDENCE_PATH) writeFileSync(process.env.EVIDENCE_PATH, JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ faulted_status: failed.status, faulted_message: failed.message, retry_status: retried.status, problems }, null, 2));
  return problems.length ? 1 : 0;
}

main().then((code) => process.exit(code), (error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
