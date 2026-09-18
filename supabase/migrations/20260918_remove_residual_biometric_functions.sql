-- Remove any residual overloads of the legacy biometric face-matching function.
-- This is intentionally destructive and belongs to the explicit biometric-removal release gate.

do $$
declare
  fn regprocedure;
begin
  for fn in
    select p.oid::regprocedure
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'match_athlete_face'
  loop
    execute format('drop function if exists %s cascade', fn);
  end loop;
end
$$;
