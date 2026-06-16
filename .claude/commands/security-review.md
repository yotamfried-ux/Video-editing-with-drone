---
description: Run a security review of the pending changes on the current branch
---

Run a security review on all pending changes in the current branch.

Steps:
1. Identify all changed files since the branch diverged from main.
2. For each changed file, check for: injection vulnerabilities, authentication/authorization
   gaps, insecure data handling, secrets or credentials in code, unsafe dependencies,
   broken access control, OWASP Top 10 issues relevant to the change.
3. Report findings grouped by severity (CRITICAL / HIGH / MEDIUM / LOW / INFO).
4. For each finding: file path + line range, description, recommendation.
5. End with a go/no-go recommendation for merging.

Focus on actual security impact, not style. A finding without a concrete attack vector
should be INFO at most.
