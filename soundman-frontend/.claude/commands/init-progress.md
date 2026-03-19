---
name: init-progress
description: Generate a meaningful PROGRESS.md from the current repo state
user_invocable: true
---

Generate a PROGRESS.md that accurately reflects the current state of this project.

## Steps

1. **Gather context**:
   - Read the existing README.md if present
   - Run `git log --oneline -20` to understand recent history
   - Run `git status` to see any uncommitted work
   - Scan top-level files and directories to understand project structure
   - Read `.bedrock/stack.yml` if present

2. **Write PROGRESS.md** with these sections:

   - **Current state**: What is built and working right now. Be specific — mention the stack, key components, and what's functional. 2–6 bullet points.
   - **Next**: The most obvious next steps based on git history and project state. 2–4 items.
   - **Open decisions**: Any unresolved questions visible from the code or history. Omit this section if there are none.

3. **Keep it lean**: Under 30 lines total. This is a context-recovery document, not a changelog. No timestamps, no history, no duplication of the git log.

Write the file directly. Do not ask for confirmation.
