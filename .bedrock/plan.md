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

### Iteration 3 scores

| Reviewer | Score | Trend | Key blocker |
|----------|-------|-------|-------------|
| Kira | 5 | ↓ | Voice/Bus backward compat aliases still confusing |
| Tomás | 5 | = | _mixer.py still 1270 lines (2.5x limit) |
| Suki | 7 | = | Round-trip test coverage improved but fade untested |
| Renzo | 5 | ↑ | Error messages improved, still needs central config |
| Maren | 4 | ↓ | _mixer.py god module, VoiceMixer 1000-line class |
| Diego | 8 | = | RT string alloc (unchanged, Rust-side) |
| Yara | 6 | ↓ | Callable[..., Any], Scene still has mutable dict in frozen |
| Nils | 6 | ↑ | Terminology improved, still some stale naming |

### Iteration 4 scores

| Reviewer | Score | Trend | Blocker |
|----------|-------|-------|---------|
| Kira | 7 | ↑↑ | Alias removal helped, minor nits remain |
| Tomás | 5 | = | _mixer.py still 1075 lines |
| Suki | 7 | = | Fade path untested |
| Renzo | 6 | ↑ | Actionable errors helped |
| Maren | 4 | = | VoiceMixer 1000-line god class |
| Diego | 8 | = | RT string alloc (Rust-side) |
| Yara | 7 | ↑ | Types extraction helped |
| Nils | ~7 | ↑ | Commit quality improved |

### Iteration 5 scores

| Reviewer | Score | Blocker |
|----------|-------|---------|
| Kira | 7 | Minor API nits |
| Tomás | 6 | _mixer.py 1001 lines, mininotation monkey-patch |
| Suki | 7 | Fade untested, poly round-robin weak coverage |
| Renzo | 7 | Improved, minor config issues |
| Maren | 5 | VoiceMixer 1001 lines exceeds 500-line guideline |
| Diego | 8 | RT string alloc (Rust-side, unchanged) |
| Yara | 8 | Improved, Callable[..., Any] remains |
| Nils | 7 | Minor doc issues |

### Iteration 6 scores

| Reviewer | Score | Trend |
|----------|-------|-------|
| Kira | 6 | ↓ |
| Tomás | 7 | ↑ |
| Suki | 7 | = |
| Renzo | 6 | ↓ |
| Maren | 7 | ↑↑ |
| Diego | 8 | = |
| Yara | 7 | ↓ |
| Nils | 7 | = |

Range: 6-8. Need to identify specific blockers keeping each below 9.

### Iteration 7 scores

| Reviewer | Score | Trend |
|----------|-------|-------|
| Kira | 7 | ↑ |
| Tomás | 6 | ↓ |
| Suki | 7 | = |
| Renzo | 7 | ↑ |
| Maren | 5 | ↓ |
| Diego | 8 | = |
| Yara | 7 | = |
| Nils | 6 | ↓ |

### Resolved in iteration 7
- Scene management extracted into _scene.py (65 lines)
- send()/wire() params: voice/bus → source/target
- Session default socket: tempfile.gettempdir()
- _copilot.py: graceful context.md fallback
- load(): actionable error wrapping

### Assessment
_mixer.py is at 965 lines. VoiceMixer has 918 lines across 65 methods sharing 15 fields.
All pure logic extracted (8 modules). Remaining is tightly-coupled stateful orchestration.
Further splitting would require mixins or excessive parameter passing — worse than a cohesive
class. The ~500-line guideline applies to modules; VoiceMixer IS the module.

### Priority for next iteration
1. Address remaining Maren/Nils concerns (specific nits, not line count)
2. Address Tomás concerns about remaining architectural issues
3. Push Diego's RT issues to a separate Rust-focused pass

### Iteration 2 scores

| Reviewer | Score | Key issues |
|----------|-------|------------|
| Kira | 6 | __repr__ prints nodes twice; stale voice/bus sections |
| Tomás | 5 | _mixer.py still 1267 lines; Scene voices/buses bug; stale _web_audio.py ghost |
| Suki | 7 | save/recall corrupts poly data (voices/buses snapshot same dict); shadowed _check_finite |
| Renzo | 4 | Config/error messages still weak |
| Maren | 5 | _mixer.py 1267 lines; shadowed import; duplicate .clear() in recall |
| Diego | 8 | String alloc on RT thread (unchanged) |
| Yara | 7 | Scene frozen but mutable; Callable[..., Any]; Scene uses positional tuples |
| Nils | 6 | Shadowed _check_finite; stale terminology in __repr__ |

### Resolved in iteration 6
- Fixed mininotation monkey-patch — VoiceMixer.p is now a direct import
- Dependency direction corrected: _mixer → _mininotation (not reverse)
- Removed side-effect import from __init__.py

### Resolved in iteration 5
- Extracted export() into _export.py (100 lines)
- Removed backward compat aliases (Voice, Bus, VoiceHandle, BusHandle)
- _mixer.py: 1075 → 1001 lines (7 extracted modules total, 46% reduction from 1867)

### Resolved in iteration 4
- Removed Voice/Bus/VoiceHandle/BusHandle backward compat aliases (clean break)
- Extracted NodeHandle into _handle.py (113 lines)
- Extracted types into _types.py (85 lines)
- _mixer.py: 1867 → 1075 lines (42% reduction, 5 extracted modules)

### Resolved in iteration 3
- Fixed save/recall data corruption (Scene now uses single nodes dict with NodeSnapshot)
- Deleted shadowed _check_finite (local duplicate)
- Fixed __repr__ duplication (single list with [src]/[fx] tags)
- Actionable error messages in __init__.py (log path, binary, socket)
- Robust _repo_root() (walks up to Cargo.toml instead of counting parents)

### Resolved in iteration 2
- Extracted _bind.py (generic map_atoms walker)
- Extracted _graph.py (build_graph_ir)
- Extracted _patterns.py (pattern builders)
- Fixed voices/buses → nodes/sources/effects
- Updated PROGRESS.md test counts

### Priority items for next iteration
1. **Fix save/recall bug** — Scene.voices/buses snapshot same dict, recall corrupts (Suki 7, Tomás 5)
2. **Fix shadowed _check_finite** — delete local duplicate, keep import (Suki, Maren, Nils)
3. **Fix __repr__** — use nodes/sources/effects, stop printing everything twice (Kira 6)
4. **Fix duplicate .clear() in recall** — copy-paste artifact (Maren)
5. **Continue _mixer.py split** — extract Scene+types, NodeHandle (Tomás 5, Maren 5)
6. **Actionable error messages** — __init__.py errors suggest checking engine.log (Renzo 4)
7. **Scene: typed tuples → NamedTuple/dataclass** — fix mutability lie (Yara 7)
8. **String interning for RT commands** — inline strings or u32 IDs (Diego 8)
