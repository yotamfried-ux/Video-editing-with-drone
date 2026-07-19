-- Authoritative server-side publishability state for every object in REVIEW.
--
-- Storage listing and operator approval must not infer QA state from a filename or
-- trust booleans supplied by a client. The pipeline writes this row only after the
-- immutable rendered media snapshot, explicit final QA, manifest reconciliation,
-- and the real REVIEW upload are known.

create table if not exists public.draft_publishability (
  storage_object_id text primary key,
  draft_name text not null,
  pipeline_run_id text,
  athlete_key text,
  part_index integer not null check (part_index > 0),
  publishable boolean not null default false,
  qa_evidence_recorded boolean not null default false,
  qa_verdict text,
  qa_passed boolean not null default false,
  technical_issues jsonb not null default '[]'::jsonb,
  approval_blocked_reasons jsonb not null default '[]'::jsonb,
  media_specs_revision text,
  manifest_revision text not null,
  updated_at timestamptz not null default now()
);

create index if not exists draft_publishability_run_idx
  on public.draft_publishability (pipeline_run_id, updated_at desc);

create index if not exists draft_publishability_name_idx
  on public.draft_publishability (draft_name, updated_at desc);

alter table public.draft_publishability enable row level security;
