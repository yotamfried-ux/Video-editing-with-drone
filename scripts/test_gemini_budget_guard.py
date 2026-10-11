#!/usr/bin/env python3
"""Fail-closed preflight for a manually authorized Gemini video QA run.

Does not claim to enforce a provider billing cap. Requires an explicit per-run
cost estimate and cumulative externally verified spend in ILS.
"""
import argparse
import json
from decimal import Decimal, InvalidOperation

CAP = Decimal("10.00")

def money(value):
    try:
        n = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid monetary input") from exc
    if not n.is_finite() or n < 0:
        raise ValueError("Amount must be finite and nonnegative")
    return n

def authorize(spent, reserved, estimate):
    spent, reserved, estimate = map(money, (spent, reserved, estimate))
    remaining = CAP - spent - reserved
    if remaining <= 0:
        return False, "LIMIT_REACHED", remaining
    if estimate <= 0:
        return False, "MISSING_POSITIVE_ESTIMATE", remaining
    if estimate > remaining:
        return False, "ESTIMATE_EXCEEDS_REMAINING_BUDGET", remaining
    return True, "ESTIMATE_WITHIN_BUDGET_NOT_A_BILLING_GUARANTEE", remaining

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spent-ils", required=True)
    parser.add_argument("--reserved-ils", required=True)
    parser.add_argument("--estimated-next-ils", required=True)
    args = parser.parse_args()
    allowed, reason, remaining = authorize(args.spent_ils, args.reserved_ils, args.estimated_next_ils)
    print(json.dumps({"allowed": allowed, "reason": reason,
                      "cap_ils": str(CAP), "remaining_before_next_ils": str(remaining)}))
    if not allowed:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
