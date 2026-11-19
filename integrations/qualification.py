"""Isolated qualification runs: the production pipeline on the same sources, without touching production state.

Enabled only by SPORTREEL_QUALIFICATION_RUN_ID (a slug, e.g. "q9-20261117-a"). Then:

* R2: every object key the pipeline reads or writes is mapped into ``qualification/<run_id>/`` at the boto3
  boundary (``NamespacedS3``, returned by ``integrations.r2_storage._client``). The rest of the code keeps seeing
  logical keys (``raw/<batch>/x.MP4``, ``review/x.mp4``); a listing strips the namespace again. Any S3 method that
  is not on the allowlist (bucket operations, bulk deletes, ...) raises. Production ``raw/``, ``processed/``,
  ``review/``, ``approved/``, ``metadata/`` are therefore never written, moved or deleted. Inputs are seeded into
  the namespace beforehand by a verified server-side copy (``scripts/qualification_run.py seed``): same bytes,
  same SHA-256.
* Supabase: the client factories return ``GuardedSupabase``: reads pass through; insert / upsert / update /
  delete / rpc are NOT sent - they are appended to the qualification ledger and answered with the payload, so no
  draft row, publishability record, QA task, pipeline status or Discover publication can be created or changed.
* Notifications and athlete follow-ups are skipped.
* LLM spend: ``check_llm_budget`` (called by ``integrations.gemini`` before every model call) raises
  ``LlmBudgetExceeded`` once the run's recorded spend plus a per-call reserve would pass SPORTREEL_LLM_BUDGET_USD.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

NAMESPACE_ROOT = "qualification/"
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{3,62}$")
_lock = threading.Lock()


class QualificationIsolationError(RuntimeError):
    """An operation would reach production state from a qualification run. Always refused."""


class LlmBudgetExceeded(RuntimeError):
    """The qualification run's model budget is spent; no further model call is made."""


def run_id() -> str | None:
    value = os.getenv("SPORTREEL_QUALIFICATION_RUN_ID", "").strip()
    if not value:
        return None
    if not _RUN_ID_RE.match(value):
        raise QualificationIsolationError(f"invalid SPORTREEL_QUALIFICATION_RUN_ID {value!r} (slug a-z0-9-, 4-63)")
    return value


def active() -> bool:
    return run_id() is not None


def namespace() -> str:
    rid = run_id()
    if rid is None:
        raise QualificationIsolationError("not a qualification run")
    return f"{NAMESPACE_ROOT}{rid}/"


def physical_key(key: str) -> str:
    """Logical key -> key inside this run's namespace. A key in another run's namespace is refused."""
    key = str(key or "")
    ns = namespace()
    if key.startswith(ns):
        return key
    if key.startswith(NAMESPACE_ROOT):
        raise QualificationIsolationError(f"key {key!r} belongs to another qualification namespace")
    return ns + key.lstrip("/")


def logical_key(key: str) -> str:
    ns = namespace()
    return key[len(ns):] if key.startswith(ns) else key


# ------------------------------------------------------------------------------------------------ ledger
def _debug_dir() -> str:
    return os.path.join(os.getenv("TMP_DIR", "/tmp/dtor"), "pipeline-debug")


def ledger_path() -> str:
    return os.path.join(_debug_dir(), "qualification_ledger.jsonl")


def record(kind: str, **fields: Any) -> None:
    entry = {"ts": round(time.time(), 3), "qualification_run_id": run_id(), "kind": kind, **fields}
    os.makedirs(_debug_dir(), exist_ok=True)
    with _lock, open(ledger_path(), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


# ------------------------------------------------------------------------------------------------ R2
class _NamespacedPaginator:
    def __init__(self, inner: Any):
        self._inner = inner

    def paginate(self, **kwargs: Any):
        if "Prefix" in kwargs:
            kwargs["Prefix"] = physical_key(kwargs["Prefix"])
        else:
            kwargs["Prefix"] = namespace()
        for page in self._inner.paginate(**kwargs):
            page = dict(page)
            page["Contents"] = [dict(item, Key=logical_key(item["Key"])) for item in page.get("Contents", [])]
            yield page


class NamespacedS3:
    """boto3 S3 client proxy that confines every object operation to the qualification namespace."""

    _ALLOWED = {"head_object", "get_object", "put_object", "delete_object", "copy_object", "download_file",
                "upload_file", "generate_presigned_url", "get_paginator", "list_objects_v2"}

    def __init__(self, inner: Any):
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name not in self._ALLOWED:
            raise QualificationIsolationError(f"S3 method {name!r} is not allowed in a qualification run")
        method = getattr(self._inner, name)
        if name == "get_paginator":
            return lambda op: _NamespacedPaginator(method(op)) if op == "list_objects_v2" else self._refuse(op)
        if name == "download_file":
            return lambda bucket, key, filename, *a, **k: method(bucket, physical_key(key), filename, *a, **k)
        if name == "upload_file":
            def upload(filename, bucket, key, *a, **k):
                record("r2_write", op="upload_file", key=physical_key(key))
                return method(filename, bucket, physical_key(key), *a, **k)
            return upload
        if name == "generate_presigned_url":
            def presign(client_method, Params=None, **k):
                params = dict(Params or {})
                if "Key" in params:
                    params["Key"] = physical_key(params["Key"])
                return method(client_method, Params=params, **k)
            return presign

        def call(**kwargs: Any) -> Any:
            if "Key" in kwargs:
                kwargs["Key"] = physical_key(kwargs["Key"])
            if "Prefix" in kwargs or name == "list_objects_v2":
                kwargs["Prefix"] = physical_key(kwargs.get("Prefix", ""))
            if "CopySource" in kwargs:
                source = dict(kwargs["CopySource"])
                source["Key"] = physical_key(source["Key"])
                kwargs["CopySource"] = source
            if name in ("put_object", "delete_object", "copy_object"):
                record("r2_write", op=name, key=kwargs.get("Key"))
            result = method(**kwargs)
            if name == "list_objects_v2" and isinstance(result, dict):
                result = dict(result, Contents=[dict(i, Key=logical_key(i["Key"])) for i in result.get("Contents", [])])
            return result
        return call

    @staticmethod
    def _refuse(op: str):
        raise QualificationIsolationError(f"paginator {op!r} is not allowed in a qualification run")


# ------------------------------------------------------------------------------------------------ Supabase
class _FakeResult:
    def __init__(self, data: Any):
        self.data = data if isinstance(data, list) else ([data] if data is not None else [])
        self.count = len(self.data)


class _BlockedWrite:
    """Swallows the rest of a write chain (.eq(...).execute()) and records it instead of sending it."""

    def __init__(self, table: str, op: str, payload: Any):
        self._table, self._op, self._payload, self._filters = table, op, payload, []

    def __getattr__(self, name: str):
        def chain(*args: Any, **kwargs: Any):
            if name == "execute":
                record("supabase_write_blocked", table=self._table, op=self._op, filters=self._filters,
                       payload=self._payload)
                if self._op == "rpc":
                    return _FakeResult(None)       # an RPC answer is never invented: no rows
                return _FakeResult(self._payload if isinstance(self._payload, (dict, list)) else None)
            self._filters.append([name, list(args)])
            return self
        return chain


class _GuardedTable:
    _WRITES = {"insert", "upsert", "update", "delete"}

    def __init__(self, inner: Any, name: str):
        self._inner, self._name = inner, name

    def __getattr__(self, attr: str):
        if attr in self._WRITES:
            return lambda *args, **kwargs: _BlockedWrite(self._name, attr, args[0] if args else kwargs.get("json"))
        return getattr(self._inner, attr)


class GuardedSupabase:
    """Read-through, write-blocking Supabase client for qualification runs."""

    def __init__(self, inner: Any):
        self._inner = inner

    def table(self, name: str) -> _GuardedTable:
        return _GuardedTable(self._inner.table(name), name)

    from_ = table

    def rpc(self, fn: str, params: dict | None = None, *args: Any, **kwargs: Any):
        return _BlockedWrite(f"rpc:{fn}", "rpc", params)

    def __getattr__(self, attr: str):
        if attr in ("storage", "auth", "functions", "realtime", "postgrest"):
            raise QualificationIsolationError(f"Supabase {attr!r} is not available in a qualification run")
        return getattr(self._inner, attr)


def guard_supabase(client: Any) -> Any:
    return GuardedSupabase(client) if active() else client


# ------------------------------------------------------------------------------------------------ LLM budget
LLM_CALL_RESERVE_USD = 0.05   # largest single call seen in run diagnostics is ~$0.03 (2.5-pro, long video)


def llm_budget_usd() -> float | None:
    raw = os.getenv("SPORTREEL_LLM_BUDGET_USD", "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        raise LlmBudgetExceeded(f"invalid SPORTREEL_LLM_BUDGET_USD {raw!r}")


def _recorded_spend() -> float:
    total = 0.0
    path = os.path.join(_debug_dir(), "llm_cost_calls.jsonl")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    total += float(json.loads(line).get("cost_usd") or 0.0)
                except (ValueError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    return total


# MEM-04: analysis may not starve identity verification and final QA. Calls are classed by the calling step.
ANALYSIS_LABEL_PREFIXES = ("analyzer._gemini_call_session", "analyzer.analyze_", "analyzer._analyze_chunk",
                           "missed_moment_rescue.")


def budget_phase(label: str | None) -> str:
    """'analysis' for per-source analysis calls, 'downstream' for identity, source-evidence and QA calls."""
    return "analysis" if str(label or "").startswith(ANALYSIS_LABEL_PREFIXES) else "downstream"


def downstream_reserve_usd() -> float:
    try:
        return max(0.0, float(os.getenv("SPORTREEL_LLM_DOWNSTREAM_RESERVE_USD", "0") or 0))
    except ValueError:
        raise LlmBudgetExceeded("invalid SPORTREEL_LLM_DOWNSTREAM_RESERVE_USD")


def refusals_path() -> str:
    return os.path.join(_debug_dir(), "llm_budget_refusals.jsonl")


def _record_refusal(**row: Any) -> None:
    try:
        os.makedirs(_debug_dir(), exist_ok=True)
        with _lock, open(refusals_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.time(), **row}) + "\n")
    except OSError:
        pass


def check_llm_budget(label: str | None = None) -> None:
    """Called before every model call. A qualification run without a budget is refused outright.

    With SPORTREEL_LLM_DOWNSTREAM_RESERVE_USD set, analysis calls stop at (cap - reserve) so identity verification
    and final QA keep their share; downstream calls may use the full cap. Every refusal is recorded in
    pipeline-debug/llm_budget_refusals.jsonl so the batch verdict reports the run as INCOMPLETE, never SUCCESS.
    """
    cap = llm_budget_usd()
    if cap is None:
        if active():
            raise LlmBudgetExceeded("qualification runs require SPORTREEL_LLM_BUDGET_USD")
        return
    spent = _recorded_spend()
    phase = budget_phase(label)
    limit = cap - downstream_reserve_usd() if phase == "analysis" else cap
    if spent + LLM_CALL_RESERVE_USD > limit:
        _record_refusal(phase=phase, label=label, spent_usd=round(spent, 4), cap_usd=cap, limit_usd=round(limit, 4))
        if active():
            record("llm_budget_exceeded", spent_usd=round(spent, 4), cap_usd=cap, phase=phase, label=label)
        raise LlmBudgetExceeded(f"LLM budget reached ({phase}): spent ${spent:.4f} + reserve ${LLM_CALL_RESERVE_USD} "
                                f"> limit ${limit:.4f} (cap ${cap})")


# ------------------------------------------------------------------------------------------------ fault injection
FAULT_POINTS = ("after_analysis", "before_qa", "after_first_upload")
_fault_hits: dict[str, int] = {}


def draft_name_perturbation() -> tuple[str, str]:
    """Gate A PA-13 (cycle 12): (description suffix, YYYYMMDD) that make a RETRY propose different draft names, as a
    retry on another day / with another model description would. Honoured ONLY in a qualification run; ("", "")
    otherwise, so production names can never be changed by it."""
    if not active():
        return "", ""
    suffix = os.getenv("SPORTREEL_QUALIFICATION_DESCRIPTION_SUFFIX", "").strip()[:40]
    day = os.getenv("SPORTREEL_QUALIFICATION_DRAFT_DATE", "").strip()
    return suffix, (day if re.match(r"^\d{8}$", day) else "")


def fault(point: str) -> None:
    """Gate A (cycle 10): a deliberate HARD crash at a named point, honoured ONLY in a qualification run.

    SPORTREEL_QUALIFICATION_FAULT=<point> -> the ledger records the fault, then the process exits with code 97 via
    os._exit (no finally blocks, no cleanup: the same as a runner kill). Outside a qualification run, or for any
    other point, this is a no-op, so production can never be crashed by it.
    """
    if point not in FAULT_POINTS:
        raise ValueError(f"unknown fault point {point!r}")
    if not active() or os.getenv("SPORTREEL_QUALIFICATION_FAULT", "").strip() != point:
        return
    with _lock:
        _fault_hits[point] = _fault_hits.get(point, 0) + 1
    record("fault_injected", point=point)
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(97)
