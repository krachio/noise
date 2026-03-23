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

### Resolved
- Web folder mess (commit 7496071)
- _web_audio.py moved out of krach core (commit 709378c)
- Hardcoded /tmp path fixed (commit 0768544)
- _flush() double iteration + stale docstrings (commit 2e429cb)

### Reviewer scores (iteration 1)

| Reviewer | Score | Key issues |
|----------|-------|------------|
| Kira | 6 | `voices`/`buses` properties return same dict; `__repr__` dumps everything |
| Tomás | 5 | _mixer.py 1867 lines (3.7x limit); _mininotation monkey-patches VoiceMixer; WebSession fragile subclass |
| Suki | 7 | _bind_voice_poly has no behavioral test; Session socket paths untested; ftom bug documented but unfixed |
| Renzo | 4 | _repo_root() fragile; __init__.py errors don't suggest fix; no central config |
| Maren | 5 | _mixer.py god module; 3 copy-pasted IR tree walkers (~220 lines duplication); struct() uses hasattr |
| Diego | 8 | String alloc in Command::SetParam on RT thread; linear scan in set_param; Automation has heap Strings |
| Yara | 7 | struct() bypasses type system; Node should be mostly frozen; Scene uses positional tuples |
| Nils | 5 | PROGRESS.md test counts stale; module docstrings still say "voice"; error messages don't suggest fixes |

### Priority action items for next iteration
1. **Split _mixer.py** — extract types, graph builder, IR rewriters, pattern builders, handles (Tomás 5, Maren 5)
2. **Generic IR walker** — replace 3 copy-pasted _bind_* functions with single map_ir (Maren 5, Suki 7)
3. **Fix `voices`/`buses` properties** — filter by num_inputs or collapse into `nodes` (Kira 6)
4. **Central config + actionable errors** — replace _repo_root(), add log path hints to errors (Renzo 4)
5. **Freeze Node fields + typed Scene** — frozen dataclass split, NamedTuple for Scene (Yara 7)
6. **Update PROGRESS.md + module docstrings** — accurate counts, "node" not "voice" (Nils 5)
7. **String interning for RT commands** — inline strings or u32 IDs in Command variants (Diego 8)
