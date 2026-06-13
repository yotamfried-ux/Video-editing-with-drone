"""D3: extracted QA gate decision."""

from pipeline.stages.qa_gate import qa_blocking


def test_pass_is_non_blocking():
    assert qa_blocking({"verdict": "PASS"}) is False


def test_unknown_is_non_blocking():
    # QA-errored reels must not block delivery.
    assert qa_blocking({"verdict": "UNKNOWN", "qa_error": True}) is False


def test_fail_without_critical_is_non_blocking():
    assert qa_blocking({"verdict": "FAIL",
                        "defects": [{"severity": "minor"}]}) is False


def test_fail_with_critical_blocks():
    assert qa_blocking({"verdict": "FAIL",
                        "defects": [{"severity": "minor"},
                                    {"severity": "critical"}]}) is True
