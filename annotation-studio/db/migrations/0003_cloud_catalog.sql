-- 0003: cloud source catalog. Existing SportReel videos in R2 are used IN PLACE (never copied); the bucket is only read.
-- Additive: local sources keep provider NULL.
set local search_path = __SCHEMA__;

alter table sources add column if not exists provider text;
alter table sources add column if not exists cloud_key text;
alter table sources add column if not exists verify_state text;
alter table sources add column if not exists proxy_state text;

create table if not exists cloud_objects(
  id text primary key, key text not null unique, prefix text not null, size bigint not null,
  etag text, last_modified text, record_sha256 text, record_status text, record_upload_id text, batch_id text,
  uploaded_at text, pipeline_state text not null default 'unknown', available integer not null default 1,
  display_name text, source_id text references sources(id), seen_at text not null
);
drop trigger if exists cloud_objects_protected on cloud_objects;
create trigger cloud_objects_protected before delete on cloud_objects for each row execute function reject_delete_protected();

insert into schema_migrations(version) values ('0003_cloud_catalog') on conflict (version) do nothing;
