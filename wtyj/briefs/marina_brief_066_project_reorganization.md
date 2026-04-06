# BRIEF 066 — Project Reorganization: agents/marina + shared
**Status:** Draft | **Files:** all source, all tests, CLAUDE.md, INFRA.md, .gitignore, snapshot.sh, systemd unit | **Depends on:** commit staged cleanup changes from previous session | **Blocks:** all future briefs (paths change)

## Context

All 8 source files live flat in `bluemarlin/src/`. Every file uses `sys.path.insert(0, __file_dir__)` to import siblings. There is no separation between platform code (config_loader, bm_logger, state_registry) and Marina-specific code (email_poller, marina_agent, etc.). This blocks adding a second agent (social) because both agents need shared platform code but shouldn't be in the same directory.

Additionally, `state_registry.db` (runtime SQLite) sits in `src/` alongside source files. The VPS git repo root is `/root/` (`.git` at `/root/.git`), so the `bluemarlin/` subdirectory provides necessary isolation from home directory files and must be kept.

## Why This Approach

Three options were considered:
1. **Flatten bluemarlin/ to repo root** — rejected because VPS repo root is `/root/`, flattening would mix project files with home dir files.
2. **Separate repo for social** — rejected because master_plan defines one platform, shared state between agents.
3. **Keep bluemarlin/, reorganize within it** — chosen. Keeps VPS isolation, enables multi-agent structure, all changes are mechanical (file moves + import updates).

The `agents/` naming (not `src/`) matches the master_plan vocabulary. `shared/` over `lib/` or `core/` because it's three utility files, not a library.

## Source Material

### Current directory structure (within bluemarlin/)
```
src/                    ← all 8 source files, flat
  config_loader.py      ← shared (used by all agents)
  bm_logger.py          ← shared
  state_registry.py     ← shared
  state_registry.db     ← runtime SQLite (gitignored)
  email_poller.py       ← marina-specific
  marina_agent.py       ← marina-specific
  gws_calendar.py       ← marina-specific
  sheets_writer.py      ← marina-specific
  payment_stub.py       ← marina-specific
  format_sheets.py      ← marina-specific
tests/                  ← 33 files, flat
config/
logs/
briefs/
```

### Current import patterns in source files
All source files use: `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` then bare imports like `import config_loader`.

### Current import patterns in test files
All test files (except live_test_harness.py and clear_holds.py) use: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))` then bare imports.

### Current relative path references
- `config_loader.py` line 10: `_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "client.json")`
- `bm_logger.py` line 11-12: `_BASE_DIR = os.path.dirname(os.path.abspath(__file__))` then `LOG_PATH = os.path.join(_BASE_DIR, "..", "logs", "bluemarlin.log")`
- `state_registry.py` line 12-14: `DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_registry.db")`
- `email_poller.py` line 40-41: `_SRC_DIR = os.path.dirname(os.path.abspath(__file__))` then `_CONFIG_DIR = os.path.normpath(os.path.join(_SRC_DIR, "..", "config"))`
- `gws_calendar.py` line 18-19: `_SRC_DIR = os.path.dirname(os.path.abspath(__file__))` then `_KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))`
- `sheets_writer.py` line 16-17: `_SRC_DIR = os.path.dirname(os.path.abspath(__file__))` then `KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))`
- `payment_stub.py` line 11: `PAYMENT_STATE_FILE = "payment_state.json"` (CWD-relative — stays as-is)
- `clear_holds.py` line 2: `db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "state_registry.db")`
- `snapshot.sh` line 43: `scp "${VPS}:${VPS_DIR}/src/state_registry.db" ...`
- `snapshot.sh` line 87: `python3 << ... c = sqlite3.connect('src/state_registry.db') ...`

### VPS systemd unit (current)
```ini
WorkingDirectory=/root/bluemarlin
ExecStart=/usr/bin/python3 /root/bluemarlin/src/email_poller.py
```

### Duplicate .claude/agents/
`bluemarlin/.claude/agents/` is a stale copy of `.claude/agents/` (root). The root one is authoritative. The nested one should be deleted.

## Instructions

### Phase 0 — Prerequisite: commit staged cleanup changes
The previous session staged file renames (briefs), deletions (dead source files), and moves. These must be committed first to avoid git confusion.

```
git add -A
git commit -m "Cleanup: rename briefs to marina_* prefix, delete dead source files, move clear_holds to tests/"
```

### Phase 1 — Create new directory structure
All paths relative to `bluemarlin/`.

```bash
mkdir -p agents/marina
mkdir -p shared
mkdir -p data
mkdir -p tests/marina
touch agents/__init__.py
touch agents/marina/__init__.py
touch shared/__init__.py
touch data/.gitkeep
```

### Phase 2 — Move files with git mv

**Shared platform files (3 files):**
```bash
git mv src/config_loader.py shared/config_loader.py
git mv src/bm_logger.py shared/bm_logger.py
git mv src/state_registry.py shared/state_registry.py
```

**Marina agent files (6 files):**
```bash
git mv src/email_poller.py agents/marina/email_poller.py
git mv src/marina_agent.py agents/marina/marina_agent.py
git mv src/gws_calendar.py agents/marina/gws_calendar.py
git mv src/sheets_writer.py agents/marina/sheets_writer.py
git mv src/payment_stub.py agents/marina/payment_stub.py
git mv src/format_sheets.py agents/marina/format_sheets.py
```

**Test files (33 files):**
```bash
git mv tests/*.py tests/marina/
```

**Delete stale duplicate (from within bluemarlin/):**
```bash
rm -rf .claude/agents/
```

**Delete empty src/ (after confirming it's empty except state_registry.db and .DS_Store):**
```bash
# state_registry.db is gitignored, just leave it — VPS will handle separately
rm -rf src/.DS_Store
rmdir src/ 2>/dev/null || true
```

### Phase 3 — Update source file imports and paths

**shared/config_loader.py** — path still works (`../config/`). Only update file header:
```python
# bluemarlin/shared/config_loader.py
# Last modified: Brief 066
# Purpose: Read-only client.json interface. Caches on first read. Never raises.
```

**shared/bm_logger.py** — path still works (`../logs/`). Only update file header:
```python
# bluemarlin/shared/bm_logger.py
# Last modified: Brief 066
# Purpose: Structured JSONL event logger
```

**shared/state_registry.py** — change DB_PATH and update header:
```python
# bluemarlin/shared/state_registry.py
# Last modified: Brief 066
# Purpose: SQLite WAL deduplication, capacity, manifests, bookings
```
Change line 12-14 from:
```python
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "state_registry.db"
)
```
To:
```python
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "state_registry.db"
)
```

**agents/marina/email_poller.py** — update header, imports, and path:

Header (replace existing header lines 1-14):
```python
#!/usr/bin/env python3
# bluemarlin/agents/marina/email_poller.py
# Last modified: Brief 066
# Purpose: Core orchestrator. IMAP → marina_agent → calendar → sheets → SMTP
```

Replace lines 16-33 (the entire import block from `import state_registry` through `import gws_calendar`) with:
```python
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib, uuid
from datetime import datetime, timezone, timedelta
from email.utils import parseaddr
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText
from email.utils import make_msgid
from email.mime.multipart import MIMEMultipart
import smtplib, base64
import sys as _sys
import os as _os

# Package path setup — add bluemarlin/ root to sys.path
_sys.path.insert(0, _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..')))

from shared import state_registry
from shared import bm_logger
from shared import config_loader
from agents.marina import marina_agent
from agents.marina import sheets_writer
from agents.marina import gws_calendar
from agents.marina import payment_stub
```

Update `_SRC_DIR` / `_CONFIG_DIR` (currently line 40-41, now two levels up):
```python
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.normpath(os.path.join(_SRC_DIR, "..", "..", "config"))
```

**agents/marina/marina_agent.py** — update header and imports:

Header:
```python
# bluemarlin/agents/marina/marina_agent.py
# Last modified: Brief 066
```

Replace lines 10-17 (sys import through bm_logger import):
```python
import sys
from datetime import datetime, timezone, timedelta

import anthropic

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader
import bm_logger
```
With:
```python
import sys
from datetime import datetime, timezone, timedelta

import anthropic

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))
from shared import config_loader
from shared import bm_logger
```

**agents/marina/gws_calendar.py** — update header, imports, and key path:

Header:
```python
# bluemarlin/agents/marina/gws_calendar.py
# Last modified: Brief 066
```

Replace lines 14-16:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader
import state_registry
```
With:
```python
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))
from shared import config_loader
from shared import state_registry
```

Update line 19 `_KEY_PATH` (two levels up now):
```python
_KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))
```

**agents/marina/sheets_writer.py** — update header, imports, and key path:

Header:
```python
# bluemarlin/agents/marina/sheets_writer.py
# Last modified: Brief 066
```

Replace lines 13-14:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader
```
With:
```python
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))
from shared import config_loader
```

Update line 17 `KEY_PATH`:
```python
KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))
```

**agents/marina/format_sheets.py** — update header, imports, and key path:

Header:
```python
# bluemarlin/agents/marina/format_sheets.py
# Last modified: Brief 066
# RUN ONCE: python3 -m agents.marina.format_sheets (from bluemarlin/)
```

Replace lines 10-11:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader
```
With:
```python
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))
from shared import config_loader
```

Also update the KEY_PATH line (currently using `_SRC_DIR` with single `..`):
```python
# Find and replace the line:
KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', 'config', 'bluemarlin-calendar-key.json'))
# With:
KEY_PATH = os.path.normpath(os.path.join(_SRC_DIR, '..', '..', 'config', 'bluemarlin-calendar-key.json'))
```
Where `_SRC_DIR = os.path.dirname(os.path.abspath(__file__))`. Same pattern as gws_calendar.py and sheets_writer.py.

**agents/marina/payment_stub.py** — update header only (no import changes, CWD-relative path stays):
```python
# bluemarlin/agents/marina/payment_stub.py
# Last modified: Brief 066
# Purpose: Payment stub — demo.pay links only
```

### Phase 4 — Create tests/conftest.py

Create `bluemarlin/tests/conftest.py`:
```python
"""Shared test configuration — adds bluemarlin/ root to sys.path."""
import sys
import os

# Add bluemarlin/ (parent of tests/) to sys.path so package imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### Phase 5 — Update test file imports

For every test file in `tests/marina/`, apply these changes:

1. **Remove** the `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))` line (and `'..', '..'` variant since files moved one level deeper). Note: since files moved from `tests/` to `tests/marina/`, the old path `../src` would now be `../../src` — but we're removing it entirely because conftest.py handles it.

2. **Replace bare imports** with package imports:
   - `import marina_agent` → `from agents.marina import marina_agent`
   - `import email_poller` → `from agents.marina import email_poller`
   - `import config_loader` → `from shared import config_loader`
   - `import state_registry` → `from shared import state_registry`
   - `import sheets_writer` → `from agents.marina import sheets_writer`
   - `import gws_calendar` → `from agents.marina import gws_calendar`
   - `import payment_stub` → `from agents.marina import payment_stub`
   - `import format_sheets` → `from agents.marina import format_sheets`
   - `import bm_logger` → `from shared import bm_logger`

3. **Replace from-imports:**
   - `from email_poller import X` → `from agents.marina.email_poller import X`
   - `from marina_agent import X` → `from agents.marina.marina_agent import X`

4. **Do NOT remove** `import sys` or `import os` if they're used elsewhere in the test (e.g., tempfile paths, environment vars).

**Files requiring import updates (24 files):**
- test_033_thread_key.py: `import email_poller`
- test_034_verify_items.py: no src imports (json/os only)
- test_035_marina_prompt.py: `import marina_agent`
- test_036_prompt_fixes.py: `import marina_agent`
- test_037_extended_stress.py: no src imports (os only, path reference check)
- test_038_prompt_fixes.py: `import marina_agent`
- test_039_capacity_soft_holds.py: `import state_registry, gws_calendar, config_loader`
- test_040_escalation_system.py: `import marina_agent, sheets_writer`
- test_041_semi_escalation_prompt.py: `import marina_agent`
- test_042_operator_email_hardening.py: no src imports (re/uuid only)
- test_043_relay_detection_fixes.py: has sys.path.insert AND deferred imports inside test functions — `from email_poller import _decode_subj` (lines 12, 27, 37, 51) and `import email_poller` (lines 64, 85). Update all to: `from agents.marina.email_poller import _decode_subj` and `from agents.marina import email_poller`
- test_044_departure_before_summary.py: has sys.path.insert but no source imports visible in header — check full file
- test_045_slot_alternative_change.py: has sys.path.insert
- test_046_hybrid_state_machine.py: `from email_poller import _day_matches, _suggest_dates, _build_booking_summary, _build_action_context, _post_validate` + `import marina_agent`
- test_047_reschedule_booking_flow.py: `from email_poller import _BOOKING_INTENTS, _post_validate`
- test_048_human_speech_optimization.py: `from email_poller import _post_validate, _BOOKING_INTENTS, _build_booking_summary` + `import marina_agent`
- test_049_fix_format_sheets.py: has sys.path.insert
- test_050_manifest_foundation.py: `import state_registry, gws_calendar`
- test_051_manifest_integration.py: `import payment_stub`
- test_052_manifests_sheet_tab.py: `import sheets_writer, format_sheets`
- test_061_escalation_bugs.py: `from email_poller import _resolve_booking_ref, _detect_booking_ref` + `import marina_agent`
- test_064_hardening.py: `from email_poller import _post_validate, _day_matches, _SYSTEM_EMAIL_PREFIXES` + `import config_loader, state_registry` + `from marina_agent import _build_user_prompt`
- test_065_production_hardening.py: has sys.path.insert — check full file for specific imports
- test_booking_ref.py: `import state_registry, marina_agent, email_poller`
- test_booking_ref_reply.py: `import marina_agent`
- test_capacity_stress.py: `import state_registry, config_loader, gws_calendar`
- test_marina_live.py: `import marina_agent`
- test_marina_stress.py: `import marina_agent`
- test_marina_tone.py: `import marina_agent, config_loader` + `from email_poller import _build_booking_summary`
- test_multi_trip.py: `import email_poller, marina_agent, config_loader`
- test_stale_thread.py: `import email_poller`

**Special files:**
- `clear_holds.py`: Update DB path from `"src", "state_registry.db"` to `"data", "state_registry.db"`. No sys.path changes needed (standalone script).
- `live_test_harness.py`: Update config path — `os.path.join(_SCRIPT_DIR, "..", "config")` becomes `os.path.join(_SCRIPT_DIR, "..", "..", "config")` (now two levels up from `tests/marina/` to `bluemarlin/`).

### Phase 5b — Update hardcoded file-read paths in tests

Many test files use `os.path.join(os.path.dirname(__file__), "..", "src", "filename.py")` to read source files directly (not imports — actual file reads for source inspection tests). After tests move from `tests/` to `tests/marina/`, TWO things change: (a) need one extra `..` level, and (b) `src/` changes to the new location.

**Path mapping (all relative to `os.path.dirname(__file__)`):**

| Old path | New path |
|----------|----------|
| `"..", "src", "marina_agent.py"` | `"..", "..", "agents", "marina", "marina_agent.py"` |
| `"..", "src", "email_poller.py"` | `"..", "..", "agents", "marina", "email_poller.py"` |
| `"..", "src", "sheets_writer.py"` | `"..", "..", "agents", "marina", "sheets_writer.py"` |
| `"..", "src", "format_sheets.py"` | `"..", "..", "agents", "marina", "format_sheets.py"` |
| `"..", "src", "state_registry.py"` | `"..", "..", "shared", "state_registry.py"` |
| `"..", "src", "gws_calendar.py"` | `"..", "..", "agents", "marina", "gws_calendar.py"` |
| `"..", "src", "payment_stub.py"` | `"..", "..", "agents", "marina", "payment_stub.py"` |
| `"..", "config", "client.json"` | `"..", "..", "config", "client.json"` |
| `"..", "briefs", "..."` | `"..", "..", "briefs", "..."` |
| `"..", "..", "CLAUDE.md"` | `"..", "..", "..", "CLAUDE.md"` |

**Files with hardcoded file-read paths (10 files):**
- `test_034_verify_items.py`: `../config/client.json`
- `test_035_marina_prompt.py`: `../src/marina_agent.py` + `../../CLAUDE.md`
- `test_036_prompt_fixes.py`: `../src/marina_agent.py`
- `test_037_extended_stress.py`: `../briefs/marina_output_037.md`
- `test_038_prompt_fixes.py`: `../src/marina_agent.py`
- `test_049_fix_format_sheets.py`: `../src/format_sheets.py`
- `test_050_manifest_foundation.py`: `../src/state_registry.py` + `../src/gws_calendar.py`
- `test_051_manifest_integration.py`: `../src/email_poller.py` + `../src/payment_stub.py`
- `test_052_manifests_sheet_tab.py`: `../src/sheets_writer.py` + `../src/format_sheets.py` + `../src/email_poller.py`
- `live_test_harness.py`: `../config` (config directory path)

### Phase 5c — Update header-check assertions in tests

Multiple test files assert that source file headers contain specific brief numbers (e.g., `assert "Brief 035" in header`). Since Phase 3 updates all source file headers to "Brief 066", these assertions must also be updated.

**DO NOT change the header check to "Brief 066".** Instead, change each assertion to check for "Brief 066" OR remove the specific brief number check and replace it with a check that the header contains `# Last modified: Brief` (any number). The latter is more robust — future briefs won't break these tests.

**Files with header assertions to update:**
- `test_035_marina_prompt.py`: assertion checking for "Brief 035" in marina_agent.py header
- `test_036_prompt_fixes.py`: assertion checking for "Brief 036" in marina_agent.py header
- `test_038_prompt_fixes.py`: assertion checking for brief number in marina_agent.py header
- `test_044_departure_before_summary.py`: assertion checking for brief number
- `test_045_slot_alternative_change.py`: assertions checking for "Brief 045"
- `test_049_fix_format_sheets.py`: assertion checking for "Brief 049" in format_sheets.py header
- `test_050_manifest_foundation.py`: assertions checking for "Brief 050" in state_registry.py and gws_calendar.py headers
- `test_051_manifest_integration.py`: assertions checking for brief numbers in email_poller.py and payment_stub.py headers
- `test_052_manifests_sheet_tab.py`: assertions checking for brief numbers in sheets_writer.py, format_sheets.py, email_poller.py headers

**Replacement pattern:** For each assertion like `assert "Brief 035" in header`, change to `assert "Last modified: Brief" in header` (checks format without pinning to a specific number).

Read each file to find the exact assertion lines and update them.

### Phase 7 — Update documentation and config

**CLAUDE.md** — Update the ACTIVE SOURCE FILES table:
```
| File | Brief | Lines | Purpose |
|------|-------|-------|---------|
| `agents/marina/email_poller.py` | 066 | ~1215 | Core orchestrator |
| `agents/marina/marina_agent.py` | 066 | ~237 | Single Claude call per message |
| `agents/marina/gws_calendar.py` | 066 | — | Calendar hold + availability via gws CLI |
| `agents/marina/sheets_writer.py` | 066 | — | Sheets logging via gws CLI |
| `agents/marina/payment_stub.py` | 066 | 57 | Payment stub — demo.pay links only |
| `agents/marina/format_sheets.py` | 066 | — | Run-once sheet formatting |
| `shared/config_loader.py` | 066 | 94 | Read-only client.json interface |
| `shared/state_registry.py` | 066 | 57 | SQLite WAL deduplication |
| `shared/bm_logger.py` | 066 | 28 | Structured JSONL event logger |
```

Update FILE HEADER FORMAT section:
```python
# bluemarlin/agents/marina/filename.py
# or
# bluemarlin/shared/filename.py
# Last modified: Brief 0XX
# Purpose: one line
```

**INFRA.md** — Update VPS project paths:
```
| Source files | `/root/bluemarlin/agents/marina/` and `/root/bluemarlin/shared/` |
```

Update systemd ExecStart reference and deploy flow.

**.gitignore** — Replace `bluemarlin/src/state_registry.db` with:
```
bluemarlin/data/*
!bluemarlin/data/.gitkeep
```

**snapshot.sh** — Update all `src/state_registry.db` references to `data/state_registry.db`.

**MEMORY.md** — Update key file paths to new locations.

### Phase 8 — VPS deployment

After pushing to git:

1. SSH to VPS and run:
```bash
cd /root/bluemarlin
# Create data directory and move runtime DB
mkdir -p data
cp src/state_registry.db data/state_registry.db
cp src/state_registry.db-wal data/state_registry.db-wal 2>/dev/null || true
cp src/state_registry.db-shm data/state_registry.db-shm 2>/dev/null || true

# Pull new code
git pull

# Update systemd unit
cat > /etc/systemd/system/bluemarlin.service << 'EOF'
[Unit]
Description=BlueMarlin Autonomous Booking Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bluemarlin
EnvironmentFile=-/root/bluemarlin/config/bluemarlin.env
ExecStart=/usr/bin/python3 -m agents.marina.email_poller
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=bluemarlin

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl restart bluemarlin
systemctl is-active bluemarlin
```

2. Verify with `journalctl -u bluemarlin -n 20` — should show normal polling without import errors.

## Tests

### Structural tests (new file: tests/marina/test_066_project_structure.py)
```python
"""Brief 066 — verify project reorganization."""
import os
import sys

# conftest.py handles sys.path
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))

def test_agents_marina_directory_exists():
    assert os.path.isdir(os.path.join(_ROOT, 'agents', 'marina'))

def test_shared_directory_exists():
    assert os.path.isdir(os.path.join(_ROOT, 'shared'))

def test_data_directory_exists():
    assert os.path.isdir(os.path.join(_ROOT, 'data'))

def test_src_directory_does_not_exist():
    assert not os.path.isdir(os.path.join(_ROOT, 'src'))

def test_marina_source_files_exist():
    marina_dir = os.path.join(_ROOT, 'agents', 'marina')
    expected = ['email_poller.py', 'marina_agent.py', 'gws_calendar.py',
                'sheets_writer.py', 'payment_stub.py', 'format_sheets.py',
                '__init__.py']
    for f in expected:
        assert os.path.isfile(os.path.join(marina_dir, f)), f"Missing: agents/marina/{f}"

def test_shared_source_files_exist():
    shared_dir = os.path.join(_ROOT, 'shared')
    expected = ['config_loader.py', 'bm_logger.py', 'state_registry.py', '__init__.py']
    for f in expected:
        assert os.path.isfile(os.path.join(shared_dir, f)), f"Missing: shared/{f}"

def test_config_loader_path_resolves():
    from shared import config_loader
    assert os.path.isfile(config_loader._CONFIG_PATH), \
        f"config_loader._CONFIG_PATH does not exist: {config_loader._CONFIG_PATH}"

def test_bm_logger_path_resolves():
    from shared import bm_logger
    log_dir = os.path.dirname(bm_logger.LOG_PATH)
    assert os.path.isdir(log_dir), f"Log directory does not exist: {log_dir}"

def test_state_registry_db_path():
    from shared import state_registry
    db_dir = os.path.dirname(state_registry.DB_PATH)
    assert os.path.isdir(db_dir), f"Data directory does not exist: {db_dir}"
    assert 'data' in state_registry.DB_PATH, \
        f"DB_PATH should reference data/ directory: {state_registry.DB_PATH}"

def test_imports_from_agents_marina():
    from agents.marina import email_poller
    from agents.marina import marina_agent
    from agents.marina import gws_calendar
    from agents.marina import sheets_writer
    from agents.marina import payment_stub
    assert hasattr(email_poller, 'main')
    assert hasattr(marina_agent, 'process_message')

def test_imports_from_shared():
    from shared import config_loader
    from shared import bm_logger
    from shared import state_registry
    assert hasattr(config_loader, 'get_trips')
    assert hasattr(bm_logger, 'log')
    assert hasattr(state_registry, 'DB_PATH')

def test_no_sys_path_insert_in_tests():
    """No test file should have sys.path.insert — conftest.py handles it."""
    test_dir = os.path.dirname(__file__)
    violations = []
    for fname in os.listdir(test_dir):
        if fname.startswith('test_') and fname.endswith('.py'):
            with open(os.path.join(test_dir, fname)) as f:
                content = f.read()
            if 'sys.path.insert' in content:
                violations.append(fname)
    assert not violations, f"Files still have sys.path.insert: {violations}"
```

### Existing test suite
Run the full test suite to confirm all imports resolve:
```bash
cd bluemarlin && python -m pytest tests/marina/ -v --tb=short 2>&1 | tail -60
```

All existing tests must pass with zero import errors.

## Success Condition

`python -m pytest tests/marina/ -v` passes all tests including the new structural test, and `src/` directory no longer exists. On VPS, `systemctl is-active bluemarlin` returns `active` and `journalctl -u bluemarlin -n 10` shows normal polling.

## Rollback

1. `git revert HEAD` on Mac and VPS
2. On VPS: restore systemd unit to original, `systemctl daemon-reload && systemctl restart bluemarlin`
3. On VPS: `cp data/state_registry.db src/state_registry.db` (if DB was moved)
4. VPS snapshot from `backups/snapshot_20260310_212631_pre-reorg/` has all runtime state
