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
    approve_handler = read("web-api/src/lib/operator-draft-approve.ts")
    review_screen = read("mobile/src/app/(operator)/review.tsx")
    contracts = read("mobile/src/features/operator/types/contracts.ts")

    for token in ["QA-FLAGGED", "qa_review_required", "final_verdict", "blocking", "approval_blocked_reasons"]:
        require(token in policy, f"review policy missing {token}")

    require("evaluateDraftReviewPolicy" in drafts_route, "R2/Drive drafts must expose policy metadata")
    require("withReviewPolicy" in drafts_route, "draft list must include storage policy wrapper")
    require("reedit_task" in drafts_route, "draft list must expose active re-edit tasks")
    require("...policy" in drafts_route, "draft list must include policy fields")

    require("approveDraftPost" in approve_route, "approve route must delegate to the storage-derived policy handler")
    require("file_name" not in approve_route, "approve route must not trust client-provided file_name")
    require("file_name" not in approve_handler.split("type ApproveBody", 1)[1].split("};", 1)[0], "ApproveBody must not accept client-provided file_name")
    require("fileName = r2Basename(fileId)" in approve_handler, "R2 policy name must come from storage key")
    require("fileName = (await getFile(fileId)).name" in approve_handler, "Drive policy name must come from Drive lookup")
    require("evaluateDraftReviewPolicy" in approve_handler, "approve handler must enforce review policy")
    require("status: 409" in approve_handler, "blocked approval must return 409")
    policy_call = approve_handler.index("const policy = evaluateDraftReviewPolicy")
    require("await moveR2Object" in approve_handler and policy_call < approve_handler.index("await moveR2Object"), "policy must run before R2 move")
    require("await moveFile" in approve_handler and policy_call < approve_handler.index("await moveFile"), "policy must run before Drive move")

    for token in ["draftIsApprovalBlocked", "approvalReasons", "Approval blocked", "disabled={approving !== null || blocked}", "Send to re-edit"]:
        require(token in review_screen, f"review screen missing {token}")
    require("QA-FLAGGED" in review_screen, "UI must fail safe for QA-FLAGGED even without API metadata")
    require("approval_blocked" in contracts and "approval_blocked_reasons" in contracts and "review_required" in contracts, "mobile contract missing review fields")

    print("operator review gate contract ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
