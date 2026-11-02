-- 0005: Precision Studio V2 - optimistic concurrency control for video catalog ownership
set local search_path = __SCHEMA__;

alter table sources add column if not exists owner_version integer not null default 0;
alter table cloud_objects add column if not exists owner_version integer not null default 0;
alter table source_owner_history add column if not exists version integer not null default 1;

insert into schema_migrations(version) values ('0005_v2_owner_version') on conflict (version) do nothing;
