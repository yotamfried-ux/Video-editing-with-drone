---
description: Re-sync this project with Engineering OS guidance
---

Re-apply Engineering OS guidance for this project.

Steps:

1. Locate the Engineering OS reference:

```bash
ENGINEERING_OS_HOME="${ENGINEERING_OS_HOME:-$HOME/.engineering-os}"
```

2. If the reference exists locally, read:

```bash
$ENGINEERING_OS_HOME/CLAUDE.md
$ENGINEERING_OS_HOME/core/
```

3. Apply the relevant workflow, quality gates, reusable patterns, and lessons to this project.

4. Keep Engineering OS read-only from this repository. Do not edit or vendor the reference directory here.

5. For PR work in this repository:
- use small branches
- run relevant checks before pushing
- address CodeRabbit comments before merge
- require owner approval before merging to `main`
