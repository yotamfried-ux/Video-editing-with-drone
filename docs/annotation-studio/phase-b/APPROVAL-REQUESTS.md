# Phase B — approval requests (nothing below has been done)

Each request lists the exact action, resource, cost, risks, rollback, and the evidence already obtained. Approve individually.

## A1 — Create the protected R2 archive bucket and two tokens
* **Action:** create bucket `sportreel-gt-archive` (name adjustable) in the existing Cloudflare account; enable bucket-level retention/lock if the account supports it; create (1) an *Object Read & Write* token scoped to this bucket only (held by the Studio ingest process) and (2) an *Object Read only* token scoped to this bucket (playback/evaluator).
* **Resource:** new bucket + 2 API tokens. The existing `sportreel` bucket and its credentials are **not touched**.
* **Cost:** R2 storage per GB-month above the free allowance, no egress fees (per Cloudflare's published R2 pricing — **verify current numbers before approving**). Footage volume determines the amount; nothing is created without a size ceiling you set.
* **Risks:** a mis-scoped token would expose the archive — mitigated by `scripts/probe-archive-protection.mjs` (checks reader cannot write/delete; locked objects cannot be deleted; no public read). Retention lock makes accidental deletion impossible **and** makes deliberate deletion wait for the retention period.
* **Rollback:** delete the bucket (only while empty or after retention expiry) and revoke the tokens; Studio falls back to the local archive.
* **Evidence so far:** R2 adapter tests (10) vs. an in-repo S3 stub incl. the published AWS SigV4 vector; **not** tested against real R2.

## A2 — Ground Truth database isolation: choose one, then apply migrations
* **Option 1 (recommended): new Supabase project** dedicated to Ground Truth. **Cost:** may require a paid plan — the organization already has two active projects; the exact plan/limit must be checked in your billing page (I could not and did not verify it). **Benefit:** separate dashboard, keys, backups, blast radius.
* **Option 2: dedicated schema `ground_truth` in the existing `sportreel` project.** **Cost:** none. **Residual risk:** same project superuser/dashboard/`service_role` owner can still reach it by granting themselves access; protection depends on the REVOKEs verified by `tests/pg/isolation.test.mjs` (which proved `anon`, `authenticated`, `service_role` — even with BYPASSRLS — are denied everything) and on never running a blanket `GRANT … ALL TABLES` as an admin.
* **Action (either option):** `STUDIO_ADMIN_DB_URL=… npm run migrate -- --roles` (creates schema, tables, triggers, roles `gt_owner`, `gt_studio`, `gt_evaluator`; **no production table is read or altered**), then set the two role passwords out-of-band. Use a **direct or session-pooler** connection — Supabase's transaction-mode pooler (port 6543) breaks multi-statement transactions.
* **Rollback:** `drop schema ground_truth cascade; drop role gt_studio, gt_evaluator, gt_owner;` (Option 1: delete the project). Take `gt-backup export` first.
* **Evidence so far:** migrations + roles applied to a **local PostgreSQL 16** (not Supabase): 3 role-denial/authorization tests, migration idempotency, dry-run, full suite on Postgres, end-to-end flow under the real roles.

## A3 — One real pipeline run with evidence export enabled
* **Action:** run the production workflow once on **a batch you designate** with `SPORTREEL_EXPORT_EDL=1` (requires a one-line env addition to `pipeline-run.yml`) so the diagnostics artifact contains `edl/*.edl.json` and `predictions.v1.json`.
* **Cost:** one normal pipeline run (compute + Gemini usage as today). **Risks:** extra SHA-256 pass over each source (cost ∝ footage size; ~seconds per GB); export code is wrapped so failures cannot fail a run (tested). Rendering arguments are proven unchanged by test.
* **Rollback:** unset the flag.
* **Evidence so far:** the same code path (`framing.install` → `editor.cut_clip` → `editor.compile_reel`) rendered synthetic 4K reels; the EDL matched the actual output pixels for contain, fixed crop and follow crop.
* **Also requires your explicit statement that the footage may be processed/annotated** (consent/retention is an open item in the spec).
