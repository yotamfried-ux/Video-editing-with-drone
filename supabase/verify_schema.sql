-- Run in Supabase SQL editor after all migrations.
-- Every `ok` value must be true.

-- Required tables.
select 'table:reels' as item, count(*) > 0 as ok
from information_schema.tables where table_schema='public' and table_name='reels'
union all
select 'table:athlete_profiles', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='athlete_profiles'
union all
select 'table:payments', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='payments'
union all
select 'table:pricing', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='pricing'
union all
select 'table:analytics_events', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='analytics_events'
union all
select 'table:suggestions', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='suggestions'
union all
select 'table:support_tickets', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='support_tickets'
union all
select 'table:drafts', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='drafts'
union all
select 'table:reprocess_requests', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='reprocess_requests'
union all
select 'table:pipeline_status', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='pipeline_status'
union all
select 'table:draft_feedback', count(*) > 0
from information_schema.tables where table_schema='public' and table_name='draft_feedback'
union all

-- Required non-biometric function/trigger and unit contracts.
select 'function:handle_new_user', count(*) > 0
from information_schema.routines where routine_schema='public' and routine_name='handle_new_user'
union all
select 'trigger:on_auth_user_created', count(*) > 0
from information_schema.triggers where trigger_name='on_auth_user_created'
union all
select 'pricing_seeded', count(*) > 0 from public.pricing
union all
select 'pricing:price_unit_column', count(*) > 0
from information_schema.columns
where table_schema='public' and table_name='pricing' and column_name='price_unit' and is_nullable='NO'
union all
select 'pricing:all_major_ils_v1', count(*) > 0 and bool_and(price_unit = 'major_ils_v1')
from public.pricing
union all
select 'pricing:legacy_agorot_removed', count(*) = 0
from public.pricing
where price_unit = 'major_ils_v1' and price_ils >= 1000
union all

-- Removed biometric contract: these checks pass only when the old surface is absent.
select 'removed:athlete_profiles.face_embedding', count(*) = 0
from information_schema.columns
where table_schema='public' and table_name='athlete_profiles' and column_name='face_embedding'
union all
select 'removed:athlete_profiles.photo_path', count(*) = 0
from information_schema.columns
where table_schema='public' and table_name='athlete_profiles' and column_name='photo_path'
union all
select 'removed:reels.matched_athlete', count(*) = 0
from information_schema.columns
where table_schema='public' and table_name='reels' and column_name='matched_athlete'
union all
select 'removed:function:match_athlete_face', count(*) = 0
from information_schema.routines
where routine_schema='public' and routine_name='match_athlete_face'
union all
select 'removed:function:cosine_similarity', count(*) = 0
from information_schema.routines
where routine_schema='public' and routine_name='cosine_similarity'
union all
select 'removed:storage_bucket:athlete-photos', count(*) = 0
from storage.buckets where id='athlete-photos'
order by item;
