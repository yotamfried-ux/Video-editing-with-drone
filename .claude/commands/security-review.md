---
description: Review pending changes for concrete security risks
---

Run a security review for the current branch.

Scope:

1. Identify changed files against `main`.
2. Review only concrete security impact, including:
   - broken access control
   - authentication or authorization gaps
   - secrets or credentials in code
   - injection risks
   - unsafe file handling
   - payment/webhook validation issues
   - insecure dependency or CI changes
3. Report findings by severity: CRITICAL, HIGH, MEDIUM, LOW, INFO.
4. For each finding, include file path, line/range, risk, and recommended fix.
5. End with a merge recommendation.

Avoid style-only comments unless they create real operational or security risk.
