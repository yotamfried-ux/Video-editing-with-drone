#!/usr/bin/env python3
"""Apply tracked SportReel production migrations with an exact checksum ledger.

The repository predates a clean Supabase CLI migration history, and several legacy files
share date-only prefixes. This runner applies an explicit full-filename sequence, records
SHA-256 after each successful file, and fails on drift instead of guessing remote history.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    "20260721_remove_face_recognition.sql",
    "20260723_source_upload_exact_dedup.sql",
    "20260723_source_upload_multipart_foundation.sql",
    "20260723_single_put_size_evidence.sql",
    "20260723_source_upload_local_cleanup_evidence.sql",
    "20260723_upload_batch_verified_gate.sql",
    "20260723_upload_start_idempotency.sql",
]
BIOMETRIC_MIGRATION = "20260721_remove_face_recognition.sql"
CONFIRMATION = "REMOVE_BIOMETRICS"


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def psql(db_url: str, *args: str, capture: bool = False) -> str:
    # Keep the credential-bearing URL out of the process argument list and exception text.
    environment = {
        **os.environ,
        "PGDATABASE": db_url,
        "PGCONNECT_TIMEOUT": os.getenv("PGCONNECT_TIMEOUT", "15"),
    }
    completed = subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=environment,
    )
    return (completed.stdout or "").strip()


def query(db_url: str, sql: str) -> str:
    return psql(db_url, "-At", "-c", sql, capture=True)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ensure_ledger(db_url: str) -> None:
    psql(
        db_url,
        "-c",
        """
        create table if not exists public.sportreel_release_migrations (
          filename text primary key,
          content_sha256 text not null check (content_sha256 ~ '^[0-9a-f]{64}$'),
          applied_at timestamptz not null default now(),
          applied_by_commit text not null
        );
        alter table public.sportreel_release_migrations enable row level security;
        revoke all on table public.sportreel_release_migrations from public, anon, authenticated;
        grant select, insert, update, delete on table public.sportreel_release_migrations to service_role;
        """,
    )


def migration_state(db_url: str, filename: str) -> str | None:
    result = query(
        db_url,
        "select content_sha256 from public.sportreel_release_migrations "
        f"where filename = {sql_literal(filename)};",
    )
    return result or None


def record_migration(db_url: str, filename: str, digest: str, commit: str) -> None:
    psql(
        db_url,
        "-c",
        "insert into public.sportreel_release_migrations(filename, content_sha256, applied_by_commit) "
        f"values ({sql_literal(filename)}, {sql_literal(digest)}, {sql_literal(commit)}) "
        "on conflict (filename) do update set "
        "content_sha256 = excluded.content_sha256, "
        "applied_at = now(), applied_by_commit = excluded.applied_by_commit;",
    )


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--evidence",
        default=os.getenv("MIGRATION_EVIDENCE_PATH", "/tmp/upload-migration-evidence.json"),
    )
    args = parser.parse_args()

    evidence_path = Path(args.evidence)
    commit = os.getenv("GITHUB_SHA", "local").strip() or "local"
    evidence: dict[str, Any] = {
        "protocol": "sportreel_release_migrations_v1",
        "commit": commit,
        "check_only": args.check_only,
        "migrations": [],
        "secret_values_recorded": False,
        "result": "pending",
    }

    try:
        db_url = required("SUPABASE_DB_URL")
        confirmation = os.getenv("CONFIRM_BIOMETRIC_REMOVAL", "").strip()
        ensure_ledger(db_url)

        for filename in MIGRATIONS:
            path = ROOT / "supabase" / "migrations" / filename
            if not path.is_file():
                raise RuntimeError(f"Tracked migration is missing: {filename}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            recorded = migration_state(db_url, filename)
            item: dict[str, Any] = {"filename": filename, "content_sha256": digest}

            if recorded:
                if recorded != digest:
                    raise RuntimeError(f"Migration checksum drift for {filename}")
                item["status"] = "already_applied"
                evidence["migrations"].append(item)
                continue

            if args.check_only:
                raise RuntimeError(f"Migration is not recorded as applied: {filename}")
            if filename == BIOMETRIC_MIGRATION and confirmation != CONFIRMATION:
                raise RuntimeError(
                    "Biometric-removal migration is pending; set "
                    f"CONFIRM_BIOMETRIC_REMOVAL={CONFIRMATION} after explicit approval"
                )

            psql(db_url, "-f", str(path))
            record_migration(db_url, filename, digest, commit)
            if migration_state(db_url, filename) != digest:
                raise RuntimeError(f"Migration ledger verification failed for {filename}")
            item["status"] = "applied"
            evidence["migrations"].append(item)

        evidence["result"] = "success"
        write_evidence(evidence_path, evidence)
        print(f"Migration release gate passed for {len(MIGRATIONS)} tracked files")
        return 0
    except Exception as error:
        evidence.update({
            "result": "failure",
            "error_type": type(error).__name__,
            "error": str(error),
        })
        write_evidence(evidence_path, evidence)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
