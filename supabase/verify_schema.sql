-- Run this in Supabase SQL editor to verify all required tables and functions exist.
-- Every query should return at least one row.

-- Tables
select 'reels'              as item, count(*) > 0 as exists from information_schema.tables where table_schema='public' and table_name='reels'
union all
select 'athlete_profiles',   count(*) > 0 from information_schema.tables where table_schema='public' and table_name='athlete_profiles'
union all
select 'payments',           count(*) > 0 from information_schema.tables where table_schema='public' and table_name='payments'
union all
select 'pricing',            count(*) > 0 from information_schema.tables where table_schema='public' and table_name='pricing'
union all
select 'analytics_events',   count(*) > 0 from information_schema.tables where table_schema='public' and table_name='analytics_events'
union all
select 'suggestions',        count(*) > 0 from information_schema.tables where table_schema='public' and table_name='suggestions'
union all
select 'support_tickets',    count(*) > 0 from information_schema.tables where table_schema='public' and table_name='support_tickets'
union all
select 'drafts',             count(*) > 0 from information_schema.tables where table_schema='public' and table_name='drafts'
union all
select 'reprocess_requests', count(*) > 0 from information_schema.tables where table_schema='public' and table_name='reprocess_requests'
union all
select 'pipeline_status',    count(*) > 0 from information_schema.tables where table_schema='public' and table_name='pipeline_status'

union all

-- Functions
select 'fn:match_athlete_face', count(*) > 0 from information_schema.routines where routine_schema='public' and routine_name='match_athlete_face'
union all
select 'fn:handle_new_user',    count(*) > 0 from information_schema.routines where routine_schema='public' and routine_name='handle_new_user'
union all
select 'fn:cosine_similarity',  count(*) > 0 from information_schema.routines where routine_schema='public' and routine_name='cosine_similarity'

union all

-- Trigger
select 'trigger:on_auth_user_created', count(*) > 0 from information_schema.triggers where trigger_name='on_auth_user_created'

union all

-- Pricing seed data
select 'pricing_seeded', count(*) > 0 from public.pricing

order by item;
