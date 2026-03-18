---
name: progress
description: Check if PROGRESS.md needs updating after a commit
user_invocable: true
---

Review the latest commit(s) and the current PROGRESS.md. Determine if any of the following changed:

- **Current state**: Does the description of what's built still match reality?
- **Next steps**: Have planned next steps been completed or changed?
- **Open decisions**: Have decisions been made or new questions arisen?

If PROGRESS.md is accurate, report "PROGRESS.md is up to date" and do nothing.

If anything is stale or missing, update PROGRESS.md to reflect the current reality. Keep it lean — this is a context-recovery document, not a changelog. Aim for under 30 lines.

Do NOT:
- Duplicate the git log (commits speak for themselves)
- Add timestamps or session markers
- Accumulate history — replace stale content, don't append
