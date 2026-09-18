#!/usr/bin/env python3
"""Regression coverage for safe Supabase psql connection handling."""
from __future__ import annotations

import os
import subprocess
from unittest import mock

import apply_upload_release_migrations as migration


def main() -> int:
    db_url = (
        "postgresql://postgres.test%2Eref:p%40ss%3Aword"
        "@db.example.supabase.co:6543/postgres"
        "?sslmode=require&application_name=sportreel-release&connect_timeout=9"
    )

    original = os.environ.get("SUPABASE_DB_URL")
    os.environ["SUPABASE_DB_URL"] = db_url
    try:
        env = migration.libpq_environment(db_url)
    finally:
        if original is None:
            os.environ.pop("SUPABASE_DB_URL", None)
        else:
            os.environ["SUPABASE_DB_URL"] = original

    assert "SUPABASE_DB_URL" not in env
    assert env["PGHOST"] == "db.example.supabase.co"
    assert env["PGPORT"] == "6543"
    assert env["PGUSER"] == "postgres.test.ref"
    assert env["PGPASSWORD"] == "p@ss:word"
    assert env["PGDATABASE"] == "postgres"
    assert env["PGSSLMODE"] == "require"
    assert env["PGAPPNAME"] == "sportreel-release"
    assert env["PGCONNECT_TIMEOUT"] == "9"

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = dict(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, stdout="1\n", stderr="")

    with mock.patch.object(migration.subprocess, "run", side_effect=fake_run):
        result = migration.psql(db_url, "-At", "-c", "select 1", capture=True)

    command = captured["command"]
    child_env = captured["env"]
    assert isinstance(command, list)
    assert isinstance(child_env, dict)
    assert db_url not in " ".join(str(part) for part in command)
    assert "SUPABASE_DB_URL" not in child_env
    assert child_env["PGHOST"] == "db.example.supabase.co"
    assert child_env["PGPASSWORD"] == "p@ss:word"
    assert result == "1"

    try:
        migration.libpq_environment("not-a-postgres-url")
    except RuntimeError as error:
        assert "SUPABASE_DB_URL" in str(error)
        assert "not-a-postgres-url" not in str(error)
    else:
        raise AssertionError("invalid database URL unexpectedly succeeded")

    print("PASS: psql connection uses libpq environment without exposing the database URI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
