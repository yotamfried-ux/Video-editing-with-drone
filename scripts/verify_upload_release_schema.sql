\pset tuples_only on
\pset format unaligned

with checks(item, ok) as (
  values
    ('table:source_uploads', to_regclass('public.source_uploads') is not null),
    ('table:source_upload_parts', to_regclass('public.source_upload_parts') is not null),
    ('table:source_upload_dedup_audit', to_regclass('public.source_upload_dedup_audit') is not null),
    ('table:upload_batches', to_regclass('public.upload_batches') is not null),
    ('table:sportreel_release_migrations', to_regclass('public.sportreel_release_migrations') is not null),

    ('column:source_uploads.id:uuid', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_uploads' and column_name='id' and data_type='uuid'
    )),
    ('column:source_uploads.source_size_bytes:bigint', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_uploads' and column_name='source_size_bytes' and data_type='bigint'
    )),
    ('column:source_uploads.content_sha256:text', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_uploads' and column_name='content_sha256' and data_type='text'
    )),
    ('column:source_uploads.multipart_upload_id:text', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_uploads' and column_name='multipart_upload_id' and data_type='text'
    )),
    ('column:source_uploads.client_upload_id:text', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_uploads' and column_name='client_upload_id' and data_type='text'
    )),
    ('column:source_uploads.local_cleanup_status:text', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_uploads' and column_name='local_cleanup_status' and data_type='text'
    )),
    ('column:source_uploads.source_size_evidence:text', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_uploads' and column_name='source_size_evidence' and data_type='text'
    )),
    ('column:source_upload_parts.etag:text', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='source_upload_parts' and column_name='etag' and data_type='text'
    )),
    ('column:upload_batches.input_manifest:jsonb', exists (
      select 1 from information_schema.columns
      where table_schema='public' and table_name='upload_batches' and column_name='input_manifest' and data_type='jsonb'
    )),

    ('constraint:source_uploads_pkey', exists (
      select 1 from pg_constraint where conrelid='public.source_uploads'::regclass and contype='p'
    )),
    ('constraint:source_uploads_storage_key_unique', exists (
      select 1 from pg_constraint where conrelid='public.source_uploads'::regclass and contype='u'
    )),
    ('constraint:source_uploads_status_check', exists (
      select 1 from pg_constraint where conrelid='public.source_uploads'::regclass and conname='source_uploads_status_check' and contype='c'
    )),
    ('constraint:source_upload_parts_pkey', exists (
      select 1 from pg_constraint where conrelid='public.source_upload_parts'::regclass and contype='p'
    )),
    ('fk:source_upload_parts.source_upload_id', exists (
      select 1 from pg_constraint where conrelid='public.source_upload_parts'::regclass and contype='f'
        and confrelid='public.source_uploads'::regclass
    )),
    ('fk:source_uploads.canonical_upload_id', exists (
      select 1 from pg_constraint where conrelid='public.source_uploads'::regclass and contype='f'
        and confrelid='public.source_uploads'::regclass
    )),
    ('fk:upload_batches.pipeline_run_id', exists (
      select 1 from pg_constraint where conrelid='public.upload_batches'::regclass and contype='f'
        and confrelid='public.pipeline_runs'::regclass
    )),

    ('index:source_uploads_batch_status_idx', to_regclass('public.source_uploads_batch_status_idx') is not null),
    ('index:source_uploads_sha_verified_idx', to_regclass('public.source_uploads_sha_verified_idx') is not null),
    ('index:source_uploads_multipart_activity_idx', to_regclass('public.source_uploads_multipart_activity_idx') is not null),
    ('index:source_uploads_client_upload_id_unique_idx', to_regclass('public.source_uploads_client_upload_id_unique_idx') is not null),
    ('index:source_upload_parts_uploaded_idx', to_regclass('public.source_upload_parts_uploaded_idx') is not null),
    ('index:upload_batches_state_updated_idx', to_regclass('public.upload_batches_state_updated_idx') is not null),

    ('rls:source_uploads', coalesce((select relrowsecurity from pg_class where oid='public.source_uploads'::regclass), false)),
    ('rls:source_upload_parts', coalesce((select relrowsecurity from pg_class where oid='public.source_upload_parts'::regclass), false)),
    ('rls:source_upload_dedup_audit', coalesce((select relrowsecurity from pg_class where oid='public.source_upload_dedup_audit'::regclass), false)),
    ('rls:upload_batches', coalesce((select relrowsecurity from pg_class where oid='public.upload_batches'::regclass), false)),
    ('rls:sportreel_release_migrations', coalesce((select relrowsecurity from pg_class where oid='public.sportreel_release_migrations'::regclass), false)),

    ('policy:upload_tables:no_client_policies', not exists (
      select 1 from pg_policies where schemaname='public'
        and tablename in ('source_uploads','source_upload_parts','source_upload_dedup_audit','upload_batches','sportreel_release_migrations')
    )),
    ('grant:public:no_upload_table_dml', not exists (
      select 1 from information_schema.role_table_grants
      where grantee='PUBLIC' and table_schema='public'
        and table_name in ('source_uploads','source_upload_parts','source_upload_dedup_audit','upload_batches','sportreel_release_migrations')
        and privilege_type in ('SELECT','INSERT','UPDATE','DELETE')
    )),
    ('grant:anon:no_upload_table_dml', not exists (
      select 1 from information_schema.role_table_grants
      where grantee='anon' and table_schema='public'
        and table_name in ('source_uploads','source_upload_parts','source_upload_dedup_audit','upload_batches','sportreel_release_migrations')
        and privilege_type in ('SELECT','INSERT','UPDATE','DELETE')
    )),
    ('grant:authenticated:no_upload_table_dml', not exists (
      select 1 from information_schema.role_table_grants
      where grantee='authenticated' and table_schema='public'
        and table_name in ('source_uploads','source_upload_parts','source_upload_dedup_audit','upload_batches','sportreel_release_migrations')
        and privilege_type in ('SELECT','INSERT','UPDATE','DELETE')
    )),
    ('grant:service_role:upload_tables', not exists (
      select 1
      from unnest(array[
        'public.source_uploads',
        'public.source_upload_parts',
        'public.source_upload_dedup_audit',
        'public.upload_batches',
        'public.sportreel_release_migrations'
      ]) as table_name
      where not has_table_privilege('service_role', table_name, 'SELECT')
        or not has_table_privilege('service_role', table_name, 'INSERT')
        or not has_table_privilege('service_role', table_name, 'UPDATE')
    )),
    ('grant:client:no_upload_rpc_execute',
      not has_function_privilege('anon','public.verify_source_upload(text,bigint)','EXECUTE')
      and not has_function_privilege('authenticated','public.verify_source_upload(text,bigint)','EXECUTE')
      and not has_function_privilege('anon','public.record_source_upload_part(uuid,integer,text,bigint)','EXECUTE')
      and not has_function_privilege('authenticated','public.record_source_upload_part(uuid,integer,text,bigint)','EXECUTE')
      and not has_function_privilege('anon','public.register_source_upload_batch_membership(uuid,text,text)','EXECUTE')
      and not has_function_privilege('authenticated','public.register_source_upload_batch_membership(uuid,text,text)','EXECUTE')),
    ('grant:service_role:upload_rpc_execute',
      has_function_privilege('service_role','public.verify_source_upload(text,bigint)','EXECUTE')
      and has_function_privilege('service_role','public.record_source_upload_part(uuid,integer,text,bigint)','EXECUTE')
      and has_function_privilege('service_role','public.register_source_upload_batch_membership(uuid,text,text)','EXECUTE')),

    ('rpc:verify_source_upload', to_regprocedure('public.verify_source_upload(text,bigint)') is not null),
    ('rpc:resolve_exact_source_duplicate', to_regprocedure('public.resolve_exact_source_duplicate(uuid,text)') is not null),
    ('rpc:attach_source_multipart_session', to_regprocedure('public.attach_source_multipart_session(uuid,text,bigint,integer,boolean)') is not null),
    ('rpc:record_source_upload_part', to_regprocedure('public.record_source_upload_part(uuid,integer,text,bigint)') is not null),
    ('rpc:begin_source_upload_completion', to_regprocedure('public.begin_source_upload_completion(uuid)') is not null),
    ('rpc:record_source_upload_local_cleanup_evidence', to_regprocedure('public.record_source_upload_local_cleanup_evidence(uuid,text,integer,bigint,boolean,text)') is not null),
    ('rpc:register_upload_batch', to_regprocedure('public.register_upload_batch(text,integer,text,text)') is not null),
    ('rpc:assert_upload_batch_ready', to_regprocedure('public.assert_upload_batch_ready(text)') is not null),
    ('rpc:register_source_upload_batch_membership', to_regprocedure('public.register_source_upload_batch_membership(uuid,text,text)') is not null),

    ('migration-ledger:all-release-files', (
      select count(*) = 7 from public.sportreel_release_migrations
      where filename in (
        '20260721_remove_face_recognition.sql',
        '20260723_source_upload_exact_dedup.sql',
        '20260723_source_upload_multipart_foundation.sql',
        '20260723_single_put_size_evidence.sql',
        '20260723_source_upload_local_cleanup_evidence.sql',
        '20260723_upload_batch_verified_gate.sql',
        '20260723_upload_start_idempotency.sql'
      )
    )),

    ('removed:athlete_profiles.face_embedding', not exists (
      select 1 from information_schema.columns where table_schema='public' and table_name='athlete_profiles' and column_name='face_embedding'
    )),
    ('removed:athlete_profiles.photo_path', not exists (
      select 1 from information_schema.columns where table_schema='public' and table_name='athlete_profiles' and column_name='photo_path'
    )),
    ('removed:reels.matched_athlete', not exists (
      select 1 from information_schema.columns where table_schema='public' and table_name='reels' and column_name='matched_athlete'
    )),
    ('removed:function:match_athlete_face', to_regprocedure('public.match_athlete_face(jsonb,double precision)') is null),
    ('removed:function:cosine_similarity', not exists (
      select 1 from information_schema.routines where routine_schema='public' and routine_name='cosine_similarity'
    )),
    ('removed:storage_bucket:athlete-photos', not exists (
      select 1 from storage.buckets where id='athlete-photos'
    ))
)
select item || '=' || case when ok then 'true' else 'false' end
from checks
order by item;
