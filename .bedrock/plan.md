# Codebase Cleanup Plan

## Goal

Bring every file to 9/10 across all 8 reviewers before adding features.

## Known Issues

### 1. Web folder mess
- 817 deleted JupyterLite build artifacts polluting git status
- No `.gitignore` for `_output/`, `.venv/`, `.cache/`
- Abandoned approaches: standalone-repl.html, try.html, jupyter-lite.json
- `web/index.html` untracked

### 2. Module boundary: _web_audio.py in krach core
- Imports `pyodide.code.run_js` (browser-only)
- Only consumer is `web/index.html`
- Platform-specific code leaking into core package

### 3. Hardcoded paths
- `/tmp/krach-web/dsp` in `_web_audio.py:245` — no override
- Paths scattered across `__init__.py`, `session.py`, `_web_audio.py`
- No central config

### 4. _mixer.py god module (~1800 lines)
- Node, DspDef, VoiceMixer, NodeHandle, build_graph_ir, pattern builders, binding, graph building — all one file
- Violates 500-line guideline

### 5. Stale merge artifacts
- `_flush()` double iteration of `self._nodes.values()`
- Docstrings still say "voice" / "bus"
- BusHandle/VoiceHandle still separate classes

### 6. Inconsistent error handling
- No documented policy — some ops raise, some warn, some silently no-op

## Loop Protocol

Each iteration of the ralph loop follows this exact sequence:

```
1. /remind
   Re-read bedrock rules. Ground yourself.

2. Read .bedrock/plan.md § "Findings from last iteration"
   If empty (first run), use § "Known Issues" above.
   Pick the highest-priority unresolved finding.

3. Work on it following /remind protocol:
   - Pin behavior with tests first
   - Implement until /qa passes
   - Commit

4. Spawn all 8 reviewers (Kira, Tomás, Suki, Renzo, Maren, Diego, Yara, Nils)
   Task: "Review the changes in the last commit against .bedrock/reviewers.md"
   Each reviewer scores 1-10 with top 3 issues.

5. Spawn all 8 reviewers again
   Task: "Scan the full codebase for NEW problems not yet in the plan.
   Report findings with file:line references."

6. Collect scores. Update § "Findings from last iteration" below with:
   - Each reviewer's score and top issues
   - New problems discovered in step 5
   - Which items were resolved

7. If any score < 9: loop back to step 1.
   If all scores ≥ 9: mark phase complete, move to next known issue.
```

## Findings from last iteration

_Empty — first run. Start with "Known Issues" above._
