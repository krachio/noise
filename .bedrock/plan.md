# Codebase Cleanup Plan

## Goal

Bring the codebase back to the quality bar defined in CLAUDE.md before adding new features. Every file should pass all five reviewers at 8+.

## Identified Issues

### 1. Module boundaries — _web_audio.py in krach package
- `_web_audio.py` imports `pyodide.code.run_js` (browser-only)
- Only consumer is `web/index.html` (Pyodide context)
- Core krach package should be platform-agnostic
- **Fix:** Move to `web/` as standalone bridge module

### 2. Web folder is a mess
- 817 deleted JupyterLite build artifacts in git status
- No `.gitignore` for `_output/`, `.venv/`, `.cache/`
- Mix of abandoned approaches (JupyterLite, standalone-repl, try.html)
- New `index.html` untracked
- **Fix:** Clean git state, add `.gitignore`, commit only sources

### 3. Hardcoded paths
- `/tmp/krach-web/dsp` in `_web_audio.py:245` — no override
- Socket paths partially configurable (env var) but defaults scattered
- DSP dir, log path use `Path.home()` (OK) but not configurable
- **Fix:** Central config with env var overrides, no literal `/tmp/` in source

### 4. _mixer.py is a god module (~1800 lines)
- Node, DspDef, VoiceMixer, NodeHandle, build_graph_ir, pattern builders,
  pitch utils, control binding, graph building — all in one file
- Violates the 500-line guideline in CLAUDE.md
- **Fix:** Extract into focused modules with clear responsibilities

### 5. Stale merge artifacts
- `_flush()` iterates `self._nodes.values()` twice (lines 1707 + 1711)
- Some docstrings still say "voice" / "bus" instead of "node"
- BusHandle / VoiceHandle are type aliases but still have separate classes
- **Fix:** Mechanical cleanup pass

### 6. Inconsistent error handling
- Some ops raise, some warn, some silently no-op
- No consistent policy documented
- **Fix:** Define policy in CLAUDE.md, apply uniformly

## Phases

### Phase 1: Clean the web folder
1. Add `web/.gitignore` (ignore `_output/`, `.venv/`, `.cache/`, `*.doit.db`)
2. `git rm` all deleted JupyterLite artifacts
3. `git rm` abandoned files (standalone-repl.html, try.html, jupyter-lite.json, etc.)
4. Track `web/index.html`
5. **Review:** Tomás, Renzo

### Phase 2: Move _web_audio.py out of krach
1. Move `_web_audio.py` → `web/krach_web.py`
2. Update `web/index.html` import
3. Remove web-specific code from krach package
4. **Review:** Tomás, Kira

### Phase 3: Extract _mixer.py into focused modules
Target structure:
```
krach/src/krach/
├── __init__.py          startup, connect()
├── _config.py           paths, env vars, defaults
├── _node.py             Node dataclass, DspDef, @dsp
├── _graph.py            build_graph_ir, graph building
├── _pattern.py          pattern builders (note, hit, seq, cat, stack, ...)
├── _pitch.py            pitch utils (existing)
├── _bind.py             _bind_voice, _bind_ctrl, _bind_voice_poly
├── _mixer.py            VoiceMixer (session orchestration only)
├── _handle.py           NodeHandle, VoiceHandle, BusHandle
├── _mininotation.py     existing
├── _copilot.py          existing
└── patterns/            existing (session, ir, pattern, graph)
```
1. Extract `_config.py` — central path configuration
2. Extract `_node.py` — Node/DspDef/Voice/Bus types
3. Extract `_graph.py` — build_graph_ir and helpers
4. Extract `_pattern.py` — free-function pattern builders
5. Extract `_bind.py` — IR binding functions
6. Extract `_handle.py` — NodeHandle and aliases
7. What remains in `_mixer.py`: VoiceMixer class (~500 lines)
8. **Review:** All five reviewers

### Phase 4: Mechanical cleanup
1. Fix `_flush()` double iteration
2. Update all docstrings: "voice/bus" → "node"
3. Collapse VoiceHandle/BusHandle into NodeHandle
4. Remove dead code
5. **Review:** Maren, Suki

### Phase 5: Error handling policy
1. Document policy in CLAUDE.md:
   - Missing node → `warnings.warn` (non-destructive ops)
   - Invalid args → `ValueError` (constructive error message)
   - Engine errors → `KernelError` (surfaced from Rust)
   - Config errors → `RuntimeError` (startup only)
2. Audit all `raise` / `return` / `warnings.warn` paths against policy
3. **Review:** Kira, Renzo

## Ralph Loop Protocol

For each phase:
1. Read this plan + `.bedrock/reviewers.md`
2. Implement the phase
3. Run `/qa` (pyright + tests)
4. Spawn all 5 reviewers on changed files
5. Fix issues until all scores ≥ 8
6. Commit
7. Move to next phase
