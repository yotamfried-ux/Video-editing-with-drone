-- 0002: multi-sport catalog (spec §18). Additive: existing data stays valid and unclassified (NULL), never backfilled to surfing.
set local search_path = __SCHEMA__;

create table if not exists sports(
  id text primary key, name_he text not null, name_en text not null,
  enabled integer not null default 1, taxonomy_version integer not null default 1, created_at text not null
);
create table if not exists sport_event_types(
  sport_id text not null references sports(id), key text not null,
  label_he text not null, label_en text not null, parent_key text,
  required_attrs text not null default '[]', enabled integer not null default 1,
  since_version integer not null default 1, created_at text not null,
  primary key(sport_id, key)
);
alter table sources add column if not exists primary_sport_id text;
alter table annotation_revisions add column if not exists taxonomy_versions text;

-- Sports/event types are configuration that is never deleted (retire = enabled 0).
drop trigger if exists sports_protected on sports;
create trigger sports_protected before delete on sports for each row execute function reject_delete_protected();
drop trigger if exists sport_event_types_protected on sport_event_types;
create trigger sport_event_types_protected before delete on sport_event_types for each row execute function reject_delete_protected();

insert into sports(id,name_he,name_en,enabled,taxonomy_version,created_at) values ('surfing','גלישה','Surfing',1,1,'2026-10-31T00:00:00.000Z') on conflict (id) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('surfing','wave_ride','רכיבה על גל','Wave ride',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('surfing','failed_takeoff','עמידה כושלת','Failed takeoff',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('surfing','wipeout','נפילה','Wipeout',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('surfing','paddle_out','חתירה החוצה','Paddle out',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('surfing','other','אחר','Other',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sports(id,name_he,name_en,enabled,taxonomy_version,created_at) values ('football','כדורגל','Football',1,1,'2026-10-31T00:00:00.000Z') on conflict (id) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('football','shot','בעיטה','Shot',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('football','pass','מסירה','Pass',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('football','goal','שער','Goal',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('football','other','אחר','Other',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sports(id,name_he,name_en,enabled,taxonomy_version,created_at) values ('basketball','כדורסל','Basketball',1,1,'2026-10-31T00:00:00.000Z') on conflict (id) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('basketball','shot','זריקה','Shot',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('basketball','assist','בישול','Assist',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('basketball','rebound','ריבאונד','Rebound',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('basketball','other','אחר','Other',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sports(id,name_he,name_en,enabled,taxonomy_version,created_at) values ('tennis','טניס','Tennis',1,1,'2026-10-31T00:00:00.000Z') on conflict (id) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('tennis','serve','הגשה','Serve',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('tennis','rally','חילופי מכות','Rally',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('tennis','point','נקודה','Point',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;
insert into sport_event_types(sport_id,key,label_he,label_en,parent_key,required_attrs,enabled,since_version,created_at) values ('tennis','other','אחר','Other',null,'[]',1,1,'2026-10-31T00:00:00.000Z') on conflict (sport_id,key) do nothing;

insert into schema_migrations(version) values ('0002_sports') on conflict (version) do nothing;
