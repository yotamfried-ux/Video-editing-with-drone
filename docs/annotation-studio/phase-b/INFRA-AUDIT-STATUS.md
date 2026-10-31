# Infrastructure audit scripts — status (honest)

| Script | Executed? | Result | Why |
|---|---|---|---|
| `scripts/infra-audit/r2_audit.py` | **NO — BLOCKED** | — | Needs Cloudflare R2 credentials/API access that this environment does not have |
| `scripts/infra-audit/hetzner-audit.sh` | **NO — BLOCKED** | — | Must run **on** the Hetzner server (read-only); there is no SSH access from here |
| `scripts/infra-audit/supabase_exposure_check.sh` | **NO — BLOCKED** | — | Needs a Supabase API key/URL that this environment does not hold |

What *was* done: all three were syntax-checked (`bash -n`, `python3 -m py_compile`) and reviewed to be read-only (no create/delete/modify calls). That is **not** an audit of any infrastructure.

**They are not needed for the Local First configuration** (SQLite + local write-once archive + independent device backup), which is the approved direction (2026-10-31) and is fully verified without any cloud resource. They only matter if an off-site target (Hetzner restic append-only, R2 locked prefix) or a Supabase deployment is chosen later.

If/when you want them: run each on a machine that has the access, paste the output, and it will be analysed. No live change is made without your explicit approval (`APPROVAL-REQUESTS.md`).
