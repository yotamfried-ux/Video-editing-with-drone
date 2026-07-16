import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { listFolder } from '@/lib/google-drive';
import { createR2SignedGetUrl, listR2Prefix, shouldUseR2Storage } from '@/lib/r2-storage';
import { evaluateDraftReviewPolicy } from '@/lib/draft-review-policy';
import type { DraftRow, DraftsResponse, ReprocessRow } from '@/types/operator-contracts';

const ACTIVE_REEDIT_STATUSES = ['qa_blocked', 'pending', 'queued'];

type StorageDraft = {
  id: string;
  name: string;
  created_at: string;
  size: number | null;
  watch_url: string | null;
  storage_backend: 'r2' | 'drive';
  storage_key?: string;
};

async function activeReeditTasks(draftNames: string[]) {
  if (!draftNames.length) return new Map<string, ReprocessRow>();
  const { data, error } = await supabaseAdmin
    .from('reprocess_requests')
    .select('id, draft_name, notes, status, origin, qa_defects, approval_blocked_reasons, attempt_count, max_attempts, last_pipeline_run_id, created_at, processed_at')
    .in('draft_name', draftNames)
    .in('status', ACTIVE_REEDIT_STATUSES)
    .order('created_at', { ascending: false });
  if (error) throw error;
  const map = new Map<string, ReprocessRow>();
  for (const task of (data ?? []) as ReprocessRow[]) {
    if (task.draft_name && !map.has(task.draft_name)) {
      map.set(task.draft_name, task);
    }
  }
  return map;
}

function withReviewPolicy(draft: StorageDraft, task: ReprocessRow | undefined): DraftRow {
  const taskReasons = Array.isArray(task?.approval_blocked_reasons) ? task.approval_blocked_reasons : [];
  const policy = evaluateDraftReviewPolicy({
    name: draft.name,
    review_required: Boolean(task),
    approval_blocked_reasons: taskReasons,
  });
  return {
    ...draft,
    ...policy,
    reedit_task: task ?? null,
  };
}

// GET /api/operator/drafts — list draft reels waiting for approval.
// R2 is the primary backend when configured; Drive remains as fallback.
export async function GET(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  try {
    if (shouldUseR2Storage()) {
      const files = await listR2Prefix('review/');
      const drafts: StorageDraft[] = files.map((f) => ({
        id: f.key,
        name: f.name,
        created_at: f.created_at,
        size: f.size,
        watch_url: createR2SignedGetUrl(f.key),
        storage_backend: 'r2',
        storage_key: f.key,
      }));
      const tasks = await activeReeditTasks(drafts.map((draft) => draft.name));
      return NextResponse.json<DraftsResponse>({
        drafts: drafts.map((draft) => withReviewPolicy(draft, tasks.get(draft.name))),
      });
    }

    const reviewFolder = process.env.REVIEW_FOLDER_ID;
    if (!reviewFolder) {
      return NextResponse.json(
        { error: 'REVIEW_FOLDER_ID not configured' },
        { status: 503 }
      );
    }
    const files = await listFolder(reviewFolder);
    const drafts: StorageDraft[] = files.map((f) => ({
      id: f.id,
      name: f.name,
      created_at: f.createdTime,
      size: f.size ? Number(f.size) : null,
      watch_url: f.webViewLink ?? null,
      storage_backend: 'drive',
    }));
    const tasks = await activeReeditTasks(drafts.map((draft) => draft.name));
    return NextResponse.json<DraftsResponse>({
      drafts: drafts.map((draft) => withReviewPolicy(draft, tasks.get(draft.name))),
    });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Storage request failed' },
      { status: 502 }
    );
  }
}
