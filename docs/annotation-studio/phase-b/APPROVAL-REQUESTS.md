# Phase B — approval requests (zero extra cost) — NOTHING BELOW HAS BEEN DONE

Replaces the first version, which assumed a new bucket and a new Supabase project. Decision context and comparison tables: [`INFRASTRUCTURE-DECISION.md`](INFRASTRUCTURE-DECISION.md).
Each request lists the exact action, resource, cost, risks, rollback and the evidence already obtained. Approve individually; each is independent.

## Step 0 — no approval needed: run the read-only audits yourself and share the output
`scripts/infra-audit/{r2_audit.py, hetzner-audit.sh, supabase_exposure_check.sh}` (details in that folder's README). They change nothing and print no secrets.

## R1 — R2 retention lock on a dedicated prefix of the EXISTING bucket (optional; only if you want an offsite copy of the labelled footage)
* **Action:** add one bucket-lock rule (indefinite retention) on prefix `gt-archive/` of the existing bucket (`npx wrangler r2 bucket lock add …` or dashboard).
* **Resource:** one rule on the existing bucket; no new bucket, no new token required (a separate Object R/W token for Studio is recommended, also free).
* **Cost:** $0 for the rule. Stored data beyond the free 10 GB: $0.015/GB-month. Only the *labelled* footage is copied, so expect cents to a few dollars per month — the audit tells us the real baseline.
* **Risks:** an indefinite lock cannot be undone for stored objects until the rule is removed by an account admin (that is the point). Documented behaviour of DELETE on locked objects is unclear in community reports — verified by a **probe** (`annotation-studio/scripts/probe-archive-protection.mjs`) before any footage is stored.
* **Rollback:** remove the rule (admin); delete probe objects.
* **Evidence so far:** adapter + stub tests only; **live behaviour NOT TESTED**.

## H1 — restic append-only backup target on the existing Hetzner server (optional; conditional on the audit)
* **Precondition (all must hold, from `hetzner-audit.sh`):** free disk ≥ planned archive × 1.5 *after* a 25% reserve; load5 per core < 0.5; ≥ 2 GB available RAM; SSH key-only; firewall active; the server itself has backups; the new service can run as a separate unix user with its own directory and no access to the agents' files.
* **Action:** install `restic` + `rest-server --append-only`, bound to localhost/VPN or firewalled to your IP; create a dedicated user and directory.
* **Cost:** $0 (uses existing disk). **Risks:** another service on the agents' host; disk fill — mitigated by a quota/monitor and the reserve rule. **Rollback:** stop the service, remove the user/directory.
* **Evidence so far:** none for Hetzner (no access). **BLOCKED on the audit.**

## S1 — create the `ground_truth` schema in the EXISTING Supabase project (optional; not needed for the local-first default)
* **Action:** `STUDIO_ADMIN_DB_URL=… npm run migrate -- --roles` as `postgres` (creates schema, tables, triggers, roles `gt_studio`/`gt_evaluator`; reads or alters **no** production table), then set the two role passwords out-of-band, then run `db/verify-isolation.sql` and `supabase_exposure_check.sh`.
* **Cost:** $0 (DB is ~18 MB of the 8 GB included; daily backups included on Pro). **A new project is NOT proposed: it costs from $10/month.**
* **Connection:** the shared pooler in **session mode** (port 5432, user `gt_studio.<project-ref>`) — free and IPv4-compatible. Direct connections are IPv6-only unless the paid IPv4 add-on is bought. Transaction mode (6543) is untested with this adapter: do not use it.
* **Risks:** (1) `postgres` (and so the `SUPABASE_DB_URL` secret, held by two manually dispatched workflows, and the dashboard SQL editor) can read Ground Truth through `pg_read_all_data`; it cannot rewrite history (triggers). (2) A future `GRANT ... ALL TABLES` run by an admin would expose it — `verify-isolation.sql` detects this. (3) `DROP SCHEMA` by `postgres` is possible — independent exports are required.
* **Rollback:** `drop schema ground_truth cascade; drop role gt_studio, gt_evaluator;` after `gt-backup export`.
* **Evidence so far:** migration applied as a **non-superuser `postgres`-like role** on local PostgreSQL 16 replaying the live role/ACL configuration; 8 isolation tests; verifier passes on a correct deployment and fails on all 6 violation kinds. **Live Supabase: NOT TESTED.** REST exposure: **NOT VERIFIED** (needs your anon key).

## P1 — one real pipeline run with evidence export enabled (unchanged)
* **Action:** one run of the production workflow on a batch you designate with `SPORTREEL_EXPORT_EDL=1` (one-line env addition to `pipeline-run.yml`). **Cost:** one normal run. **Rollback:** unset the flag. Also requires your statement that the footage may be processed.
* **Evidence so far:** the same code path rendered synthetic 4K reels and the EDL matched the actual pixels; export is wrapped so it cannot fail a run.
