#!/usr/bin/env python3
"""Budget preflight negative and boundary tests; zero external calls."""
from test_gemini_budget_guard import authorize
for spent, reserved, estimate, allowed, reason in [
    ("0", "0", "0.50", True, None),
    ("9.50", "0", "0.50", True, None),
    ("9.50", "0", "0.51", False, "ESTIMATE_EXCEEDS_REMAINING_BUDGET"),
    ("10", "0", "0.01", False, "LIMIT_REACHED"),
    ("8", "2", "0.01", False, "LIMIT_REACHED"),
    ("0", "0", "0", False, "MISSING_POSITIVE_ESTIMATE"),
]:
    result = authorize(spent, reserved, estimate)
    assert result[0] == allowed and (reason is None or result[1] == reason), result
for bad in ["-1", "NaN", "Infinity", "nonsense"]:
    try:
        authorize(bad, "0", "1")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid budget input accepted: " + bad)
print("Budget guard: 10 isolated cases passed; no provider billing guarantee claimed")
