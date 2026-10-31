# Ground Truth — backup and recovery

## Local-first procedure (selected direction; implemented and tested)
Principle: **footage and its backup on the same disk is not a backup.** The tool enforces it.

| Step | Command | What it guarantees |
|---|---|---|
| Back up | `node scripts/gt-offsite-backup.mjs run --to <dir on ANOTHER physical device>` | **Refuses** a destination on the same device (`st_dev`) as the live data. Writes a verified database export + the labelled originals (`--scope all` for everything). Each copy is re-hashed before it is accepted; a corrupt or missing copy is repaired on the next run; a corrupt *source* is never propagated; nothing in the destination is ever deleted |
| Verify (monthly) | `node scripts/gt-offsite-backup.mjs verify --to <dir>` | Re-reads and re-hashes every object and the database export against the digest-covered manifest |
| Recovery drill (quarterly) | `STUDIO_HOME=<empty dir> node scripts/gt-offsite-backup.mjs restore --to <dir>` | Rebuilds an empty machine: database, originals (byte-exact), thumbnails/proxies (regenerated), playback. Sources that were not in the backup are marked `unavailable` and heal by `reconcile` under the same identity |
| Status | `node scripts/gt-offsite-backup.mjs status` / Library banner | The UI warns when there is **no** external backup or the last good one is older than 7 days. A failed run is never recorded as a good backup |

Destination = any directory on a different device: an external drive, a network share, or a mounted remote. A second, **offsite** copy (Hetzner append-only via restic, or an R2 prefix with a lock rule) is added only after the read-only audits and an explicit approval (see `APPROVAL-REQUESTS.md`); until then, **keep at least two destinations on two different devices** and rotate them.
Unlabelled footage is not copied by default (cost and size); it remains protected only by the operational storage it came from. Use `--scope all` if you want every original.

The rest of this document (database exports, provider backups, archive mirroring) describes the remote options kept as prepared-but-undeployed.

Status: procedures and tooling are **implemented and tested locally**; scheduled jobs on live infrastructure are **NOT set up** (no live resources exist yet).

## What must survive
1. **Original footage** (archive objects, content-addressed by SHA-256).
2. **Annotation database** (sources, athletes, drafts, immutable revisions, datasets, predictions, evaluations, EDL records, audit log).
3. **Exports from the pipeline** (EDL/predictions JSON) — reproducible from pipeline artifacts, but stored immutably once imported.

## Archive
* **Second copy:** `mirrorArchive(primary, secondary)` (`server/r2archive.mjs`) copies every missing/corrupt object **after verifying the source hash**, never propagating a corrupt source (tested). Secondary = a second bucket/provider or a local disk.
* **Integrity audit:** `POST /api/archive/verify` (or Library → "אמת ארכיון") re-reads and re-hashes every object; failures set `archive_error` visibly. Schedule weekly.
* **Deletion protection (to be verified on the live account, not assumed):** R2 bucket-level retention/lock on the archive bucket; the Studio adapter itself has no delete method; write token held only by the ingest process, read-only token for playback. `scripts/probe-archive-protection.mjs` checks this against a live bucket and **has not been run**.
* **Interrupted ingestion:** `reconcile` is idempotent; incomplete multipart uploads are aborted automatically on failure and by `abortIncompleteUploads()`.

## Database
* **Logical backup (portable, provider-independent):** `node scripts/gt-backup.mjs export FILE` → JSON with per-table counts + SHA-256 digest. `verify FILE` checks the file; `restore FILE` loads it **only into an empty database** and re-verifies every table afterwards. Tested on SQLite and PostgreSQL (round trip identical; tampered/truncated files refused).
* **Integrity audit:** `node scripts/gt-backup.mjs audit` recomputes digests of revisions, frozen manifests, evaluations, predictions and EDLs and checks dataset→revision links.
* **Provider backups (live, not configured here):** enable Supabase PITR/daily backups on the Ground Truth project; additionally run the logical export daily to storage outside that project.
* **Restore drill (do quarterly):** create an empty database → `npm run migrate -- --roles` → `gt-backup.mjs restore` → `audit` → re-run one frozen evaluation and compare the report `digest` with the stored one.

## Recovery scenarios
| Scenario | Procedure |
|---|---|
| Operational storage reset / files moved | nothing to do; identity is the hash; `reconcile` only deactivates locations |
| Archive object lost/corrupt | `verify` flags it → copy back from the secondary (`mirrorArchive(secondary, primary)`) → `verify` |
| Database lost | restore provider backup, or empty DB + migrate + `gt-backup restore` from the latest export |
| Suspected tampering | `gt-backup audit`; compare with latest export digest; revisions are append-only and hash-pinned by datasets |
| Pipeline credential leak | GT unaffected (separate credentials and roles); rotate the pipeline credential only |
