-- Remove user face recognition and automatic biometric reel ownership.
-- This migration is intentionally destructive for biometric data.
--
-- NOTE: Storage objects/buckets are removed by scripts/remove_biometric_storage.py
-- through the supported Supabase Storage API before this SQL migration runs.
-- The storage schema is intentionally treated as read-only here.

begin;

-- Remove policies/functions that depend on the biometric ownership column first.
drop policy if exists "athletes_read_own_reels" on public.reels;
drop function if exists public.match_athlete_face(jsonb, float8);
drop function if exists public.cosine_similarity(float8[], float8[]);
drop function if exists public.jsonb_to_float8_array(jsonb);

-- Remove stored biometric inputs and inferred ownership.
alter table public.athlete_profiles
  drop column if exists face_embedding,
  drop column if exists photo_path;

alter table public.reels
  drop column if exists matched_athlete cascade;

commit;
