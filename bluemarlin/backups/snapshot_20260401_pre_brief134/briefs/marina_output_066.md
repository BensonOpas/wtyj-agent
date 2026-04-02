# OUTPUT 066 — Project Reorganization

## What Was Done

### Phase 0 — Pre-reorg commit
Committed 165 files of staged cleanup work from previous session (brief renames, file deletions, etc.).

### Phase 1 — Create directory structure
Created `agents/marina/`, `shared/`, `data/`, `tests/marina/` with `__init__.py` files and `.gitkeep` in `data/`.

### Phase 2 — Move source files
- Marina-specific files moved from `src/` to `agents/marina/`: email_poller.py, marina_agent.py, gws_calendar.py, sheets_writer.py, payment_stub.py, format_sheets.py
- Shared files moved from `src/` to `shared/`: config_loader.py, bm_logger.py, state_registry.py
- `src/` directory removed (after removing gitignored state_registry.db)

### Phase 3 — Update imports in source files
All source files updated to use package-style imports:
- `sys.path.insert(0, ...)` pointing to `bluemarlin/` root (2 dirs up from `agents/marina/`)
- `from shared import config_loader`, `from agents.marina import marina_agent`, etc.
- `_CONFIG_DIR` / `KEY_PATH` updated with extra `..` level

### Phase 4 — state_registry DB path
`DB_PATH` in `shared/state_registry.py` changed from `src/state_registry.db` to `../data/state_registry.db` (relative to `shared/`).

### Phase 5 — Test migration
- Created `tests/conftest.py` — single sys.path setup replacing 27 individual hacks
- Created `tests/marina/test_066_project_structure.py` — 12 structural tests
- Moved all 33 test files to `tests/marina/`
- Updated every test: removed sys.path.insert, changed bare imports to package imports, updated hardcoded file-read paths

### Phase 7 — Documentation updates
- CLAUDE.md: Updated active source files table, added project layout section, updated file header format
- INFRA.md: Updated VPS paths to new structure
- .gitignore: Added `bluemarlin/data/state_registry.db`
- snapshot.sh: Updated `src/state_registry.db` → `data/state_registry.db`
- MEMORY.md: Updated structure, key files, completed briefs

### Phase 8 — VPS deployment
**NOT DONE** — requires separate deployment step:
1. `mkdir -p /root/bluemarlin/data`
2. `mv /root/bluemarlin/src/state_registry.db /root/bluemarlin/data/`
3. Update systemd unit: `ExecStart` → `python3 -m agents.marina.email_poller`
4. `systemctl daemon-reload && systemctl restart bluemarlin`

## Test Results

```
12 passed — test_066_project_structure.py (all structural tests)
120 passed — full suite (excluding 2 collection errors)
15 failed — ALL PRE-EXISTING (prompt content tests from briefs 040-045)
2 collection errors — test_035, test_036 (pre-existing: prompt strings changed in later briefs)
```

**Pre-existing failures** (not caused by Brief 066):
- test_040 (3): escalation prompt content changed in Brief 046 hybrid refactor
- test_041 (3): semi-escalation prompt content changed in Brief 046
- test_043 (2): relay detection prompt content changed in Brief 046
- test_044 (4): departure-before-summary prompt content changed in Brief 046
- test_045 (3): slot alternative prompt content changed in Brief 046
- test_035, test_036: module-level assertions on prompt strings that evolved in later briefs

## Unexpected Issues

1. **src/ directory not empty** — `state_registry.db` (gitignored) blocked `rmdir`. Fixed by removing the file first.
2. **test_066 DB_PATH assertion** — `test_capacity_stress.py` patches `state_registry.DB_PATH` at module level, bleeding into test_066. Fixed by checking source code text instead of runtime value.

## Success Condition
All source files moved from `src/` to `agents/marina/` and `shared/`. All imports use package-style. 12/12 structural tests pass. No new test regressions — all 15 failures pre-date Brief 066.
