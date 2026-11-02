-- 0006: FULL_SPEC normative addendum v1 — independent annotation sets (§2), event-scoped primary (§3),
-- physical-action lineage (§4), revisioned person lineage (§6), unique evaluation identity (§10).
-- Additive only. The existing source-keyed drafts/revisions ARE the 'primary' set (no data is copied or rewritten).
set local search_path = __SCHEMA__;

create table if not exists annotation_sets(
  id text primary key,
  purpose text not null check(purpose in ('primary','delayed_blind_reannotation','independent_qa','adjudication')),
  taxonomy_version text, instruction_version text not null default 'guidelines-v1',
  annotator_id text not null,
  contributing_set_ids text not null default '[]',
  created_at text not null
);
-- Status changes are an append-only log (latest wins), so a submitted set can never silently re-open.
create table if not exists annotation_set_status(
  id serial primary key, set_id text not null references annotation_sets(id),
  status text not null check(status in ('draft','active','submitted','adjudicating','accepted','archived')),
  actor text not null, at text not null
);
create table if not exists set_assignments(
  id text primary key, set_id text not null references annotation_sets(id), source_id text not null references sources(id),
  queue_status text not null default 'unlabeled' check(queue_status in ('unlabeled','in_progress','needs_review','completed','excluded')),
  current_revision_id text, operator_id text, playback_position_ms integer not null default 0,
  draft_version integer not null default 0, draft_content text, started_at text, completed_at text, updated_at text not null,
  unique(set_id, source_id)
);
create table if not exists set_revisions(
  id text primary key, set_id text not null references annotation_sets(id), source_id text not null references sources(id),
  seq integer not null, content text not null, digest text not null, author text not null, created_at text not null,
  unique(set_id, source_id, seq)
);
create table if not exists person_lineage_relations(
  id text primary key, set_id text not null,
  relation_type text not null check(relation_type in ('merge','split','equivalent','retire')),
  from_person_id text not null references athletes(id), to_person_id text references athletes(id),
  contributing_revision_id text, reason_code text not null, created_by text not null, created_at text not null
);
create table if not exists physical_actions(
  id text primary key, sport_id text, action_type text not null, primary_person_id text references athletes(id),
  created_revision_id text, created_at text not null
);
create table if not exists physical_action_states(
  id serial primary key, physical_action_id text not null references physical_actions(id),
  lineage_state text not null check(lineage_state in ('provisional','accepted','split','merged','retired')),
  related_action_ids text not null default '[]', reason text, actor text not null, at text not null
);
create table if not exists action_occurrences(
  id text primary key, physical_action_id text not null references physical_actions(id),
  source_id text not null references sources(id), segment_id text not null, evidence_revision_id text,
  start_frame integer not null, end_frame integer not null,
  occurrence_role text not null check(occurrence_role in ('canonical_view','duplicate_view','supplementary_view','uncertain')),
  created_at text not null
);
create table if not exists action_occurrence_retirements(
  id serial primary key, occurrence_id text not null references action_occurrences(id), reason text not null, actor text not null, at text not null
);
alter table evaluation_runs add column if not exists identity_key text;
alter table evaluation_runs add column if not exists matching_version text;
create unique index if not exists evaluation_runs_identity on evaluation_runs(identity_key) where identity_key is not null;

do $$ declare t text; begin
  foreach t in array array['annotation_set_status','set_revisions','person_lineage_relations','physical_actions','physical_action_states','action_occurrences','action_occurrence_retirements'] loop
    execute format('drop trigger if exists %I_append_only on %I', t, t);
    execute format('create trigger %I_append_only before update or delete on %I for each row execute function reject_immutable()', t, t);
  end loop;
end $$;

insert into annotation_sets(id, purpose, annotator_id, created_at) values ('primary', 'primary', 'operator', '1970-01-01T00:00:00.000Z') on conflict (id) do nothing;
insert into schema_migrations(version) values ('0006_full_spec_lineage') on conflict (version) do nothing;
