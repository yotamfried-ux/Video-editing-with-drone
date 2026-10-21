#!/usr/bin/env python3
"""Contract for per-call LLM cost logging (integrations/llm_cost.py). No SDK or network needed."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations import llm_cost  # noqa: E402


def _usage(prompt, out, thoughts=0, **modalities):
    details = [SimpleNamespace(modality=SimpleNamespace(name=name.upper()), token_count=count)
               for name, count in modalities.items()]
    return SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts,
        prompt_tokens_details=details))


def close(a, b):
    return abs(a - b) < 1e-9


def test_pro_counts_thinking_as_output():
    cost = llm_cost.estimate_cost("gemini-2.5-pro", prompt=100_000, output=5_000, thoughts=15_000)
    assert close(cost, (100_000 * 1.25 + 20_000 * 10.0) / 1e6), cost


def test_pro_long_context_uses_long_rates():
    cost = llm_cost.estimate_cost("gemini-2.5-pro", prompt=300_000, output=1_000, thoughts=0)
    assert close(cost, (300_000 * 2.5 + 1_000 * 15.0) / 1e6), cost


def test_flash_audio_is_billed_at_audio_rate():
    cost = llm_cost.estimate_cost("gemini-2.5-flash", prompt=10_000, output=500, thoughts=0, audio_prompt=4_000)
    assert close(cost, (6_000 * 0.30 + 4_000 * 1.00 + 500 * 2.50) / 1e6), cost


def test_longest_prefix_prefers_flash_lite():
    assert llm_cost.price_for("gemini-2.5-flash-lite-preview")["out"] == 0.40
    assert llm_cost.price_for("models/gemini-2.5-flash")["out"] == 2.50
    assert llm_cost.price_for("something-else") is None


def test_unknown_model_is_counted_but_unpriced():
    llm_cost.reset()
    entry = llm_cost.record_call(_usage(10, 5), model="mystery-model", label="x.y")
    assert entry["cost_usd"] is None and entry["prompt_tokens"] == 10
    summary = llm_cost.summarize()
    assert summary["unpriced_calls"] == 1 and summary["total_cost_usd"] == 0


def test_price_override_from_environment():
    os.environ["GEMINI_PRICES_JSON"] = json.dumps({"gemini-2.5-flash": {"in": 1.0, "out": 2.0}})
    try:
        assert close(llm_cost.estimate_cost("gemini-2.5-flash", prompt=1_000_000, output=0, thoughts=0), 1.0)
        os.environ["GEMINI_PRICES_JSON"] = "not json"
        assert llm_cost.price_for("gemini-2.5-flash")["in"] == 0.30  # bad override is ignored
    finally:
        os.environ.pop("GEMINI_PRICES_JSON", None)


def test_record_logs_a_line_with_label_tokens_and_running_total():
    llm_cost.reset()
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        llm_cost.record_call(_usage(143_000, 5_000, 3_900, video=141_000, text=2_000),
                             model="gemini-2.5-pro", label="analyzer._gemini_call_session")
        llm_cost.record_call(_usage(40_000, 800, 0, video=39_000, audio=1_000),
                             model="gemini-2.5-flash", label="source_evidence_runner.run_qa")
    text = buffer.getvalue()
    assert "analyzer._gemini_call_session" in text and "gemini-2.5-pro" in text, text
    assert "thinking=3,900" in text and "video=141,000" in text, text
    assert "run total" in text and "(2 calls)" in text, text


def test_missing_usage_metadata_never_raises():
    llm_cost.reset()
    assert llm_cost.record_call(SimpleNamespace(), model="gemini-2.5-pro", label="a.b") is None
    assert llm_cost.record_call(None, model="gemini-2.5-pro", label="a.b") is None


def test_summary_groups_by_step_and_model_sorted_by_cost():
    llm_cost.reset()
    with redirect_stdout(io.StringIO()):
        for _ in range(3):
            llm_cost.record_call(_usage(100_000, 4_000, 6_000), model="gemini-2.5-pro", label="analyze")
        llm_cost.record_call(_usage(50_000, 500), model="gemini-2.5-flash", label="qa")
    summary = llm_cost.summarize()
    assert [row["label"] for row in summary["by_step"]] == ["analyze", "qa"], summary
    assert summary["by_step"][0]["calls"] == 3 and summary["total_calls"] == 4
    assert close(summary["total_cost_usd"], round(
        sum(row["cost_usd"] for row in summary["by_step"]), 6)), summary


def test_caller_label_names_the_pipeline_step_not_the_wrapper():
    def _with_retry(fn):
        return fn()

    def analyze_clip():
        return _with_retry(lambda: llm_cost.caller_label())

    assert llm_cost.caller_label().endswith("test_caller_label_names_the_pipeline_step_not_the_wrapper")
    assert analyze_clip().endswith("analyze_clip"), analyze_clip()


def test_summary_is_written_to_the_diagnostics_directory():
    llm_cost.reset()
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["TMP_DIR"] = tmp
        try:
            with redirect_stdout(io.StringIO()):
                llm_cost.record_call(_usage(1_000, 100), model="gemini-2.5-flash", label="a.b")
                llm_cost._write_summary()
            data = json.loads((Path(tmp) / "pipeline-debug" / "llm_cost.json").read_text())
        finally:
            os.environ.pop("TMP_DIR", None)
    assert data["estimate"] is True and data["total_calls"] == 1 and len(data["calls"]) == 1, data


def test_gemini_wrapper_records_every_call():
    source = (ROOT / "integrations" / "gemini.py").read_text()
    assert "llm_cost.record_call(response" in source and "llm_cost.caller_label()" in source
    for module in ("pipeline/stages/analyzer.py", "pipeline/stages/identity.py",
                   "pipeline/identity_failsafe.py", "pipeline/source_evidence_runner.py"):
        text = (ROOT / module).read_text()
        assert "genai.Client(" not in text and "_genai_lib.Client(" not in text, module


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS llm cost logging contract ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
