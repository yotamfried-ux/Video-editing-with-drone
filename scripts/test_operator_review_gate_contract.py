#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(ok: bool, msg: str) -> None:
    if not ok:
        raise SystemExit(msg)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    policy = read("web-api/src/lib/draft-review-policy.ts")
    drafts_route = read("web-api/src/app/api/operator/drafts/route.ts")
    approve_route = read("web-api/src/app/api/operator/drafts/approve/route.ts")
    review_screen = read("mobile/src/app/(operator)/review.tsx")
    contracts = read("mobile/src/features/operator/types/contracts.ts")

    for token in ["QA-FLAGGED", "qa_review_required", "final_verdict", "blocking", "approval_blocked_reasons"]:
        require(token in policy, f"review policy missing {token}")

    require("evaluateDraftReviewPolicy({ name: f.name })" in drafts_route, "R2 drafts must expose policy metadata")
    require("evaluateDraftReviewPolicy({ name: f.name })" in drafts_route, "Drive drafts must expose policy metadata")
    require("...policy" in drafts_route, "draft list must include policy fields")

    require("evaluateDraftReviewPolicy" in approve_route, "approve endpoint must enforce review policy")
    require("status: 409" in approve_route, "blocked approval must return 409")
    require("moveR2Object" in approve_route and approve_route.index("evaluateDraftReviewPolicy") < approve_route.index("moveR2Object"), "policy must run before R2 move")
    require("moveFile" in approve_route and approve_route.index("evaluateDraftReviewPolicy") < approve_route.index("moveFile"), "policy must run before Drive move")

    for token in ["draftIsApprovalBlocked", "approvalReasons", "Approval blocked", "disabled={approving !== null || blocked}", "Send to re-edit"]:
        require(token in review_screen, f"review screen missing {token}")
    require("QA-FLAGGED" in review_screen, "UI must fail safe for QA-FLAGGED even without API metadata")
    require("approval_blocked" in contracts and "approval_blocked_reasons" in contracts and "review_required" in contracts, "mobile contract missing review fields")

    print("operator review gate contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
