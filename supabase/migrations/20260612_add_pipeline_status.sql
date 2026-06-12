-- Pipeline status table — single row (id=1) updated by the GitHub Actions
-- pipeline to reflect live progress in the operator app.

create table if not exists pipeline_status (
  id          integer primary key default 1,
  stage       text,
  progress    numeric(6,4),
  meta        jsonb,
  updated_at  timestamptz default now()
);

-- Ensure only one row ever exists.
create unique index if not exists pipeline_status_singleton on pipeline_status (id);

-- Auto-update updated_at on every upsert.
create or replace function _set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists pipeline_status_updated_at on pipeline_status;
create trigger pipeline_status_updated_at
  before insert or update on pipeline_status
  for each row execute function _set_updated_at();

-- Seed the initial row so the app never gets a null.
insert into pipeline_status (id, stage, progress, meta)
values (1, 'idle', 0, '{}')
on conflict (id) do nothing;

-- Allow the anon/authenticated roles to read (operator app reads directly).
grant select on pipeline_status to anon, authenticated;
-- Service role handles writes (pipeline uses service key).
