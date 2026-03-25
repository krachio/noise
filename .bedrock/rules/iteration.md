For every unit of work:
0. Read PROGRESS.md to recover context
1. Resolve uncertainties (web search, then ask user)
2. Plan incremental breakdown into transparent commits. Confirm plan with the user before proceeding
3. For each commit: first pin tests and behavior, validate with /qa
4. Then implement until /qa passes
5. Then commit
6. Run /progress to check if PROGRESS.md needs updating

## Live session issues

During live krach sessions, log discoveries to `issues.log` (gitignored) with a type prefix:
- `[bug]` — broken behavior
- `[feature]` — missing capability (e.g. chord voicing module)
- `[ux]` — friction in the workflow

After the session, promote entries to GitHub issues with matching labels, then clear the file.
