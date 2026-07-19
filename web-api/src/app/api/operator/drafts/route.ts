import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { listFolder } from '@/lib/google-drive';
import { createR2SignedGetUrl, listR2Prefix, shouldUseR2Storage } from '@/lib/r2-storage';
import { evaluateDraftReviewPolicy } from '@/lib/draft-review-policy';
import {
  loadAuthoritativeDraftPublishability,
  type DraftPublishabilityAuthority,
} from '@/lib/draft-publishability';
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

function authorityReasons(authority: DraftPublishabilityAuthority | undefined): string[] {
  if (!authority) {
    return ['Authoritative pipeline publishability evidence is missing.'];
  }
  const reasons = [...authority.approval_blocked_reasons];
  if (!authority.qa_evidence_recorded) reasons.push('Final QA evidence is missing.');
  if (authority.qa_verdict !== 'PASS' || !authority.qa_passed) reasons.push('Final QA did not pass.');
  for (const issue of authority.technical_issues) reasons.push(`Technical issue: ${issue}`);
  if (!authority.publishable && !reasons.length) reasons.push('The final business manifest blocked publication.');
  return [...new Set(reasons)];
}

function withReviewPolicy(
  draft: StorageDraft,
  task: ReprocessRow | undefined,
  authority: DraftPublishabilityAuthority | undefined,
): DraftRow {
  const taskReasons = Array.isArray(task?.approval_blocked_reasons) ? task.approval_blocked_reasons : [];
  const authoritativeReasons = authorityReasons(authority);
  const authoritativeReady = Boolean(
    authority?.publishable
      && authority.qa_evidence_recorded
      && authority.qa_verdict === 'PASS'
      && authority.qa_passed
      && authority.technical_issues.length === 0,
  );
  const policy = evaluateDraftReviewPolicy({
    name: draft.name,
    review_required: Boolean(task) || !authoritativeReady,
    qa_review_required: !authoritativeReady,
    qa_gate: authority ? {
      final_verdict: authority.qa_verdict,
      qa_review_required: !authoritativeReady,
      defects: authority.technical_issues.map((issue) => ({
        severity: 'critical',
        blocking: true,
        note: issue,
      })),
    } : null,
    approval_blocked_reasons: [...taskReasons, ...authoritativeReasons],
  });
  return {
    ...draft,
    ...policy,
    authoritative_publishability: authority ?? null,
    reedit_task: task ?? null,
  };
}

async function enrichDrafts(drafts: StorageDraft[]): Promise<DraftRow[]> {
  const [tasks, authorities] = await Promise.all([
    activeReeditTasks(drafts.map((draft) => draft.name)),
    loadAuthoritativeDraftPublishability(drafts),
  ]);
  return drafts.map((draft) => withReviewPolicy(
    draft,
    tasks.get(draft.name),
    authorities.get(draft.id),
  ));
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
      return NextResponse.json<DraftsResponse>({ drafts: await enrichDrafts(drafts) });
    }

    const reviewFolder = process.env.REVIEW_FOLDER_ID;
    if (!reviewFolder) {
      return NextResponse.json(
        { error: 'REVIEW_FOLDER_ID not configured' },
        { status: 503 },
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
    return NextResponse.json<DraftsResponse>({ drafts: await enrichDrafts(drafts) });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Storage request failed' },
      { status: 502 },
    );
  }
}
