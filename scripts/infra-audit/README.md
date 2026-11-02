# Infrastructure audit tools (read-only, operator-run)

Purpose: measure what the storage/backup/database plan depends on, **without changing anything**. Run them yourself; output goes to your terminal
(and optionally a file). Nothing is sent anywhere; none of them prints secrets, object names, or file contents.

| Tool | Where to run | Reads | Mutates |
|---|---|---|---|
| `hetzner-audit.sh` | on the Hetzner server (`ssh host 'bash -s' < hetzner-audit.sh`) | disk, RAM, CPU, load, services, containers, ports, firewall, SSH hardening, update/backup indicators | nothing |
| `r2_audit.py` | your computer, with your existing `R2_*` variables | bucket list, object count and bytes per top-level prefix, projected free-tier use | nothing (List operations only; a few Class A requests) |
| `supabase_exposure_check.sh` | your computer, with `SUPABASE_URL` + a public/anon key | which schemas the REST API exposes | nothing (GET only) |

Reminders: R2 lock rules are listed with `npx wrangler r2 bucket lock list <bucket>` (needs your Cloudflare login); the Supabase SQL checks live in
`annotation-studio/db/verify-isolation.sql`.
