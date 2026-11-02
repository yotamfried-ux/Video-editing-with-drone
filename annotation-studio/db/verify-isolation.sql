-- READ-ONLY isolation assertions for the Ground Truth schema. Safe to run in the Supabase SQL editor (catalog SELECTs only,
-- no DDL, no data read). Raises an exception naming every violation; prints a notice when clean.
-- Run: after any migration, and periodically. Edit the schema name below if you deployed under another name.
do $$
declare
  s constant text := 'ground_truth';
  sid oid;
  pipeline_roles constant text[] := array['anon','authenticated','service_role','authenticator','supabase_auth_admin','supabase_storage_admin'];
  problems text[] := '{}';
  r record;
begin
  select oid into sid from pg_namespace where nspname = s;
  if sid is null then raise exception 'schema % does not exist', s; end if;

  -- 1. schema ACL: no PUBLIC (grantee 0) and no pipeline-side role
  for r in select a.grantee, a.privilege_type from pg_namespace n, aclexplode(n.nspacl) a
           where n.oid = sid and (a.grantee = 0 or a.grantee::regrole::text = any(pipeline_roles)) loop
    problems := problems || format('schema %s: %s has %s', s, case when r.grantee = 0 then 'PUBLIC' else r.grantee::regrole::text end, r.privilege_type);
  end loop;

  -- 2. tables, views, sequences (relacl) and columns (attacl)
  for r in select c.relname, a.grantee, a.privilege_type from pg_class c, aclexplode(c.relacl) a
           where c.relnamespace = sid and (a.grantee = 0 or a.grantee::regrole::text = any(pipeline_roles)) loop
    problems := problems || format('relation %s: %s has %s', r.relname, case when r.grantee = 0 then 'PUBLIC' else r.grantee::regrole::text end, r.privilege_type);
  end loop;
  for r in select c.relname, t.attname, a.grantee from pg_class c join pg_attribute t on t.attrelid = c.oid, aclexplode(t.attacl) a
           where c.relnamespace = sid and t.attacl is not null and (a.grantee = 0 or a.grantee::regrole::text = any(pipeline_roles)) loop
    problems := problems || format('column %s.%s granted to %s', r.relname, r.attname, case when r.grantee = 0 then 'PUBLIC' else r.grantee::regrole::text end);
  end loop;

  -- 3. functions: a NULL proacl means the PostgreSQL default, i.e. EXECUTE for PUBLIC
  for r in select p.proname, p.proacl from pg_proc p where p.pronamespace = sid loop
    if r.proacl is null then problems := problems || format('function %s: default ACL (PUBLIC can execute)', r.proname); end if;
  end loop;
  for r in select p.proname, a.grantee from pg_proc p, aclexplode(p.proacl) a
           where p.pronamespace = sid and (a.grantee = 0 or a.grantee::regrole::text = any(pipeline_roles)) loop
    problems := problems || format('function %s: %s can execute', r.proname, case when r.grantee = 0 then 'PUBLIC' else r.grantee::regrole::text end);
  end loop;

  -- 4. default privileges that would auto-grant on future objects in this schema
  for r in select d.defaclrole::regrole::text as owner, a.grantee from pg_default_acl d, aclexplode(d.defaclacl) a
           where d.defaclnamespace = sid and (a.grantee = 0 or a.grantee::regrole::text = any(pipeline_roles)) loop
    problems := problems || format('default privileges of %s grant to %s', r.owner, case when r.grantee = 0 then 'PUBLIC' else r.grantee::regrole::text end);
  end loop;

  -- 5. pipeline-side roles must not be members of the Ground Truth roles
  for r in select m.member::regrole::text as member, m.roleid::regrole::text as gt from pg_auth_members m
           where m.roleid::regrole::text in ('gt_studio','gt_evaluator') and m.member::regrole::text = any(pipeline_roles) loop
    problems := problems || format('%s is a member of %s', r.member, r.gt);
  end loop;

  -- 6. the schema must not be listed in any PostgREST role-level configuration (on Supabase the exposed-schema list lives in
  --    the API settings, not here: verify it separately with scripts/infra-audit/supabase_exposure_check.sh)
  for r in select setrole::regrole::text as who, c from pg_db_role_setting, unnest(setconfig) c
           where c ~ '^pgrst\.db_schemas=' and c ~ ('(^|[=, ])' || s || '([, ]|$)') loop
    problems := problems || format('PostgREST role config for %s exposes %s: %s', r.who, s, r.c);
  end loop;

  if array_length(problems, 1) > 0 then
    raise exception E'ISOLATION VIOLATION(S) in schema %:\n  - %', s, array_to_string(problems, E'\n  - ');
  end if;
  raise notice 'isolation OK for schema % (no PUBLIC/pipeline-side grants on schema, relations, columns, functions, default ACLs, role membership)', s;
end $$;
