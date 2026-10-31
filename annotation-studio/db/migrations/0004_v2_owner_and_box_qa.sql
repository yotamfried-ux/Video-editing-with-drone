-- 0004: Precision Studio V2 - manual video catalog ownership and box verification provenance
-- Additive: owner_athlete_id defaults to NULL (unassigned); never backfilled from segment performer.
set local search_path = __SCHEMA__;

alter table sources add column if not exists owner_athlete_id text references athletes(id);
alter table sources add column if not exists owner_status text default 'unassigned';
alter table sources add column if not exists owner_assigned_at text;
alter table sources add column if not exists owner_assigned_by text;

alter table cloud_objects add column if not exists owner_athlete_id text references athletes(id);
alter table cloud_objects add column if not exists owner_status text default 'unassigned';

create table if not exists source_owner_history(
  id serial primary key,
  source_id text not null references sources(id),
  old_owner_id text references athletes(id),
  new_owner_id text references athletes(id),
  old_status text,
  new_status text,
  changed_by text not null,
  reason text,
  changed_at text not null
);

drop trigger if exists source_owner_history_append_only on source_owner_history;
create trigger source_owner_history_append_only before update or delete on source_owner_history for each row execute function reject_immutable();

insert into schema_migrations(version) values ('0004_v2_owner_and_box_qa') on conflict (version) do nothing;
