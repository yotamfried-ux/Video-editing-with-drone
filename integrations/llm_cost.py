"""Per-call LLM token and cost logging (estimates from list prices).

Every Gemini call made through integrations.gemini is recorded here: tokens by kind (including
thinking tokens, which are billed as output), an estimated cost, and a label for the calling
pipeline step. Each call is logged as it happens and a per-step / per-model summary is printed at
process exit and written to $TMP_DIR/pipeline-debug/llm_cost.json (picked up by the workflow's
diagnostics artifact).

The prices below are public list prices in USD per 1M tokens and are only an ESTIMATE; set
GEMINI_PRICES_JSON to override or extend them (same shape) and always reconcile against the
billing console. This module has no third-party imports so it can be tested without the SDK.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import threading
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# USD per 1M tokens. "in_long"/"out_long" apply when the prompt exceeds "long_ctx" tokens.
DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gemini-2.5-pro": {"in": 1.25, "out": 10.0, "audio_in": 1.25,
                       "long_ctx": 200_000, "in_long": 2.50, "out_long": 15.0},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40, "audio_in": 0.30},
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50, "audio_in": 1.00},
    "gemini-1.5-flash": {"in": 0.075, "out": 0.30, "audio_in": 0.075},
}

_WRAPPER_FRAMES = {"<lambda>", "_with_retry", "_retry_gemini", "generate_content", "wrapper", "inner"}

_lock = threading.Lock()
_calls: list[dict[str, Any]] = []
_unpriced_warned: set[str] = set()
_atexit_registered = False


def _prices() -> dict[str, dict[str, float]]:
    merged = {key: dict(value) for key, value in DEFAULT_PRICES.items()}
    raw = os.getenv("GEMINI_PRICES_JSON", "").strip()
    if raw:
        try:
            for key, value in json.loads(raw).items():
                merged.setdefault(str(key), {}).update({k: float(v) for k, v in dict(value).items()})
        except Exception as exc:  # a bad override must never break a run
            logger.warning("Ignoring invalid GEMINI_PRICES_JSON: %s", exc)
    return merged


def price_for(model: str | None) -> dict[str, float] | None:
    """Longest-prefix match so 'gemini-2.5-flash-lite-preview' finds the flash-lite entry."""
    name = (model or "").lower().removeprefix("models/")
    best = None
    for key, value in _prices().items():
        if name.startswith(key) and (best is None or len(key) > len(best[0])):
            best = (key, value)
    return best[1] if best else None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _modality_counts(usage: Any) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for item in getattr(usage, "prompt_tokens_details", None) or []:
        modality = getattr(item, "modality", None)
        name = str(getattr(modality, "name", modality) or "UNKNOWN").upper()
        out[name] += _int(getattr(item, "token_count", 0))
    return dict(out)


def estimate_cost(model: str | None, *, prompt: int, output: int, thoughts: int,
                  audio_prompt: int = 0) -> float | None:
    """Estimated USD for one call, or None when the model has no known price."""
    price = price_for(model)
    if price is None:
        return None
    long_ctx = price.get("long_ctx")
    is_long = bool(long_ctx) and prompt > long_ctx
    in_rate = price.get("in_long", price["in"]) if is_long else price["in"]
    out_rate = price.get("out_long", price["out"]) if is_long else price["out"]
    audio_rate = price.get("audio_in", in_rate)
    audio = min(audio_prompt, prompt)
    return ((prompt - audio) * in_rate + audio * audio_rate + (output + thoughts) * out_rate) / 1_000_000


def caller_label(skip_module_suffix: str = "llm_cost.py") -> str:
    """Name the pipeline step that made the call, e.g. 'analyzer._gemini_call_session'."""
    import sys

    try:
        frame = sys._getframe(1)
    except ValueError:
        return "unknown"
    while frame is not None:
        filename = frame.f_code.co_filename.replace("\\", "/")
        name = frame.f_code.co_name
        if not filename.endswith(("integrations/gemini.py", skip_module_suffix)) and name not in _WRAPPER_FRAMES:
            module = os.path.splitext(os.path.basename(filename))[0]
            return f"{module}.{name}"
        frame = frame.f_back
    return "unknown"


def record_call(response: Any, *, model: str | None, label: str | None = None) -> dict[str, Any] | None:
    """Record and log one call. Never raises: cost logging must not affect the pipeline."""
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            logger.info("LLM cost | %s | %s | no usage metadata returned", label or "unknown", model)
            return None
        prompt = _int(getattr(usage, "prompt_token_count", 0))
        output = _int(getattr(usage, "candidates_token_count", 0))
        thoughts = _int(getattr(usage, "thoughts_token_count", 0))
        modalities = _modality_counts(usage)
        cost = estimate_cost(model, prompt=prompt, output=output, thoughts=thoughts,
                             audio_prompt=modalities.get("AUDIO", 0))
        entry = {
            "label": label or "unknown", "model": model or "unknown",
            "prompt_tokens": prompt, "output_tokens": output, "thinking_tokens": thoughts,
            "prompt_by_modality": modalities, "cost_usd": cost,
        }
        _append_jsonl(entry)
        with _lock:
            _calls.append(entry)
            total = sum(c["cost_usd"] or 0.0 for c in _calls)
            count = len(_calls)
        _register_summary()
        if cost is None and (model or "") not in _unpriced_warned:
            _unpriced_warned.add(model or "")
            logger.warning("LLM cost | no price known for model %r; tokens are counted but cost is not "
                           "(set GEMINI_PRICES_JSON)", model)
        by_mod = " ".join(f"{k.lower()}={v:,}" for k, v in sorted(modalities.items()))
        cost_text = f"${cost:.4f}" if cost is not None else "unpriced"
        line = (f"💰 LLM cost | {entry['label']} | {entry['model']} | in={prompt:,}"
                f"{f' ({by_mod})' if by_mod else ''} out={output:,} thinking={thoughts:,} | "
                f"≈{cost_text} | run total ≈${total:.4f} ({count} calls)")
        print(line, flush=True)
        logger.info(line)
        return entry
    except Exception as exc:
        logger.debug("LLM cost logging failed: %s", exc)
        return None


def _debug_dir() -> str:
    return os.path.join(os.getenv("TMP_DIR", "/tmp/dtor"), "pipeline-debug")


def _append_jsonl(entry: dict[str, Any]) -> None:
    """Persist each call as it happens so a killed/cancelled run keeps every record."""
    try:
        import time
        os.makedirs(_debug_dir(), exist_ok=True)
        line = json.dumps({"ts": round(time.time(), 3), **entry}, ensure_ascii=False)
        with _lock, open(os.path.join(_debug_dir(), "llm_cost_calls.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
    except Exception as exc:
        logger.debug("LLM cost jsonl append failed: %s", exc)


def snapshot() -> list[dict[str, Any]]:
    with _lock:
        return [dict(call) for call in _calls]


def reset() -> None:
    with _lock:
        _calls.clear()
    _unpriced_warned.clear()


def summarize(calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    calls = snapshot() if calls is None else calls
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for call in calls:
        group = groups.setdefault((call["label"], call["model"]), {
            "label": call["label"], "model": call["model"], "calls": 0, "prompt_tokens": 0,
            "output_tokens": 0, "thinking_tokens": 0, "cost_usd": 0.0, "unpriced_calls": 0})
        group["calls"] += 1
        group["prompt_tokens"] += call["prompt_tokens"]
        group["output_tokens"] += call["output_tokens"]
        group["thinking_tokens"] += call["thinking_tokens"]
        if call["cost_usd"] is None:
            group["unpriced_calls"] += 1
        else:
            group["cost_usd"] += call["cost_usd"]
    rows = sorted(groups.values(), key=lambda g: g["cost_usd"], reverse=True)
    return {
        "estimate": True,
        "note": "List-price estimate; reconcile with the Google billing console.",
        "total_calls": len(calls),
        "total_cost_usd": round(sum(g["cost_usd"] for g in rows), 6),
        "total_prompt_tokens": sum(g["prompt_tokens"] for g in rows),
        "total_output_tokens": sum(g["output_tokens"] for g in rows),
        "total_thinking_tokens": sum(g["thinking_tokens"] for g in rows),
        "unpriced_calls": sum(g["unpriced_calls"] for g in rows),
        "by_step": rows,
    }


def _write_summary() -> None:
    try:
        summary = summarize()
        if not summary["total_calls"]:
            return
        lines = [f"💰 LLM cost summary (estimate, list prices): ≈${summary['total_cost_usd']:.4f} over "
                 f"{summary['total_calls']} calls | in={summary['total_prompt_tokens']:,} "
                 f"out={summary['total_output_tokens']:,} thinking={summary['total_thinking_tokens']:,}"]
        for row in summary["by_step"]:
            lines.append(f"   {row['label']} [{row['model']}]: {row['calls']} calls, "
                         f"in={row['prompt_tokens']:,} out={row['output_tokens']:,} "
                         f"thinking={row['thinking_tokens']:,} ≈${row['cost_usd']:.4f}")
        if summary["unpriced_calls"]:
            lines.append(f"   ({summary['unpriced_calls']} call(s) had no known price and are not in the total)")
        text = "\n".join(lines)
        print(text, flush=True)
        logger.info(text)
        out_dir = _debug_dir()
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "llm_cost.json"), "w", encoding="utf-8") as handle:
            json.dump({**summary, "calls": snapshot()}, handle, indent=2)
    except Exception as exc:
        logger.debug("LLM cost summary failed: %s", exc)


def _register_summary() -> None:
    global _atexit_registered
    with _lock:
        if _atexit_registered:
            return
        _atexit_registered = True
    atexit.register(_write_summary)
