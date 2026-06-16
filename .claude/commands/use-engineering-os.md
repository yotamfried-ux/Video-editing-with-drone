---
description: Re-sync this project with Engineering OS (read-only governance layer) and report skill presence
---

Re-apply **Engineering OS** to this project as a READ-ONLY governance + knowledge layer.

Steps:

1. Run the sync script. Choose the method that fits your environment:

   **If `~/.engineering-os` already exists locally** (most common after first run):
   ```bash
   bash "${ENGINEERING_OS_HOME:-$HOME/.engineering-os}/scripts/use-in-project.sh"
   ```

   **If running in Claude Code on the web** (GitHub may be network-blocked):
   - Tell Claude: *"Clone Engineering OS from https://github.com/yotamfried-ux/Engineering-OS
     to ~/.engineering-os using the GitHub MCP, then run scripts/use-in-project.sh from there."*

   **First time on a local machine:**
   ```bash
   bash -c "$(curl -fsSL https://raw.githubusercontent.com/yotamfried-ux/Engineering-OS/main/scripts/use-in-project.sh)"
   ```

2. For all work in THIS project from now on, follow the rules in
   `${ENGINEERING_OS_HOME:-$HOME/.engineering-os}/CLAUDE.md` and its `core/` policies
   (workflow, git cadence, quality gates, skill orchestration, documentation).

3. Use `patterns/` for reusable code and `external-skills/` to know which skills are
   default-on. End every task with the "🧰 במה השתמשתי" usage report.

4. **superpowers** requires a one-time manual install inside Claude Code CLI:
   ```
   /plugin install superpowers@claude-plugins-official
   ```

5. **Cross-project learning loop:** When a lesson from this project reaches Medium
   confidence (root cause proven), open a PR to Engineering OS to share it —
   see `${ENGINEERING_OS_HOME:-$HOME/.engineering-os}/core/learning-loop.md`.

**Never modify anything under the Engineering OS reference directory** — it is shared
and read-only. To update the reference: `git -C "${ENGINEERING_OS_HOME:-$HOME/.engineering-os}" pull --ff-only`.
