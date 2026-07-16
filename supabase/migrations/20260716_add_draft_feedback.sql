-- draft_feedback: structured operator feedback on a delivered/review draft.
--
-- The label vocabulary here is not invented for this table — it mirrors
-- pipeline/candidate_ledger.py's OPERATOR_FEEDBACK_EVENTS/VALUE_LABELS (that
-- module is the source of truth; web-api mirrors it in
-- src/types/operator-contracts.ts). Inserted by web-api when an operator taps
-- a structured feedback control on the Review screen; consumed by
-- pipeline/stages/feedback.py's existing approval-based learning loop and by
-- the missed-good-moment recall report.
create table if not exists public.draft_feedback (
  id             uuid primary key default gen_random_uuid(),
  draft_name     text not null,
  feedback_event text not null,
  value_labels   jsonb not null default '[]'::jsonb,
  note           text not null default '',
  created_at     timestamptz not null default now()
);

create index if not exists draft_feedback_draft_created_idx
  on public.draft_feedback (draft_name, created_at desc);

-- Service-role only (pipeline + web-api both use the service key).
alter table public.draft_feedback enable row level security;
