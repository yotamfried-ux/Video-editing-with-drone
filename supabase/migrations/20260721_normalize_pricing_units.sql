-- Normalize historical pricing rows and make the stored unit explicit.
--
-- Older operator flows stored values such as 7900 for ₪79. Newer code stores
-- human-readable major ILS such as 79 and converts once at the payment boundary.
-- SportReel prices have historically been below ₪1,000, so unversioned values
-- at or above 1000 are the known legacy-agorot representation and are divided
-- exactly once before the unit marker becomes mandatory.

begin;

alter table public.pricing
  add column if not exists price_unit text;

update public.pricing
set
  price_ils = price_ils / 100,
  price_unit = 'major_ils_v1',
  updated_at = now()
where price_unit is null
  and price_ils >= 1000;

update public.pricing
set
  price_unit = 'major_ils_v1',
  updated_at = coalesce(updated_at, now())
where price_unit is null;

alter table public.pricing
  alter column price_unit set default 'major_ils_v1';

alter table public.pricing
  alter column price_unit set not null;

alter table public.pricing
  drop constraint if exists pricing_unit_supported;

alter table public.pricing
  add constraint pricing_unit_supported
  check (price_unit = 'major_ils_v1');

commit;

-- Verification query for deployment evidence:
-- select sport, price_ils, price_unit from public.pricing order by sport;
