import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  OPERATOR_FEEDBACK_EVENTS,
  VALUE_LABELS,
  type DraftFeedbackResponse,
  type OperatorFeedbackEvent,
  type ValueLabel,
} from '@/types/operator-contracts';

type FeedbackBody = {
  draft_name?: string;
  feedback_event?: string;
  value_labels?: unknown;
  note?: string;
};

function isOperatorFeedbackEvent(value: string): value is OperatorFeedbackEvent {
  return (OPERATOR_FEEDBACK_EVENTS as readonly string[]).includes(value);
}

function sanitizeValueLabels(value: unknown): ValueLabel[] {
  if (!Array.isArray(value)) return [];
  const allowed = new Set<string>(VALUE_LABELS);
  const seen: ValueLabel[] = [];
  for (const item of value) {
    if (typeof item === 'string' && allowed.has(item) && !seen.includes(item as ValueLabel)) {
      seen.push(item as ValueLabel);
    }
  }
  return seen;
}

// POST /api/operator/drafts/feedback — operator submits structured feedback
// on a draft (per docs/audit/self-learning-loop-audit-20260706.md Phase 2/8).
//
// Body: { draft_name: string, feedback_event: OperatorFeedbackEvent,
//          value_labels?: ValueLabel[], note?: string }
//
// This only records the feedback row; it does not itself approve, reject, or
// re-edit a draft (use the existing /drafts/approve and /reprocess routes for
// those actions). pipeline/stages/feedback.py reads draft_feedback rows to
// fold structured labels into its existing prompt-injection learning loop.
export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  const limited = await enforceRateLimit(req, 'draft-feedback', 30, 60);
  if (limited) return limited;

  let body: FeedbackBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const draftName = (body.draft_name ?? '').trim();
  if (!draftName) {
    return NextResponse.json({ error: 'draft_name required' }, { status: 400 });
  }

  const feedbackEvent = (body.feedback_event ?? '').trim();
  if (!isOperatorFeedbackEvent(feedbackEvent)) {
    return NextResponse.json(
      { error: `feedback_event must be one of: ${OPERATOR_FEEDBACK_EVENTS.join(', ')}` },
      { status: 400 },
    );
  }

  const valueLabels = sanitizeValueLabels(body.value_labels);
  const note = (body.note ?? '').trim().slice(0, 2000);

  const { data, error } = await supabaseAdmin
    .from('draft_feedback')
    .insert({
      draft_name: draftName,
      feedback_event: feedbackEvent,
      value_labels: valueLabels,
      note,
    })
    .select('id, draft_name, feedback_event, value_labels, note, created_at')
    .single();

  if (error || !data) {
    return NextResponse.json({ error: error?.message ?? 'Could not record feedback' }, { status: 500 });
  }

  return NextResponse.json<DraftFeedbackResponse>({ ok: true, feedback: data });
}
