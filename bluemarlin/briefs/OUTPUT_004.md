# OUTPUT 004 — state_registry.py

## Files created or modified
- `bluemarlin/src/state_registry.py` — modified (Brief 004)
- `bluemarlin/src/state_registry.db` — created automatically on first import (SQLite database)

## Assumptions made
- Test 2 checks for DB existence after a bare `import state_registry` with no function calls. To satisfy this, a module-level `_get_conn().close()` call was added at the bottom of the file. The brief says "Database is created automatically on first use" — "first use" here is interpreted as first import of the module. This is the minimal change that makes Test 2 pass without altering any public API.
- The old `state.json` is not migrated. Old hashes are lost on the first run of the new code. Worst case: one duplicate email is processed on restart. Documented as required by the brief.
- No packages installed — `sqlite3` is Python stdlib.

## Dependencies added
- None (sqlite3 is stdlib).

## Changes made (in order per brief)
1. Replaced all imports with: `import hashlib`, `import os`, `import sqlite3`, `from datetime import datetime, timezone`
2. Removed `STATE_FILE = "state.json"` global
3. Added `DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_registry.db")`
4. Replaced `_load_state()` and `_save_state()` with `_get_conn()` (opens connection, sets WAL, creates table, returns conn)
5. `generate_content_hash()` preserved exactly as-is
6. Replaced `has_been_processed()` with SQLite SELECT count(*) implementation
7. Replaced `mark_as_processed()` with SQLite INSERT OR IGNORE implementation
8. Added file header as first lines of file
- Additional: Added `_get_conn().close()` at module level to initialise the DB on import (required by Test 2)

## Test results

### Test 1 — imports cleanly
```
Command: python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import state_registry; print('IMPORT OK')"
Output:  IMPORT OK
```

### Test 2 — database file created on import
```
Command: python3 -c "... assert os.path.exists(db_path) ..."
Output:  PASS — db created at bluemarlin/src/state_registry.db
Resolved DB_PATH: /Users/benson/Projects/bluemarlin-agent/bluemarlin/src/state_registry.db
```

### Test 3 — has_been_processed returns False for new content
```
Command: python3 -c "... has_been_processed('brand_new_content_xyz_123') ..."
Output:  PASS — new content not processed
```

### Test 4 — mark_as_processed then has_been_processed returns True
```
Command: python3 -c "... mark_as_processed(...); has_been_processed(...) ..."
Output:  PASS — processed content detected correctly
```

### Test 5 — mark_as_processed is idempotent
```
Command: python3 -c "... mark_as_processed(x) x3; has_been_processed(x) ..."
Output:  PASS — idempotent insert confirmed
```

### Test 6 — no json or STATE_FILE remaining
```
Command: python3 -c "with open('bluemarlin/src/state_registry.py') as f: ..."
Output:  PASS — file structure correct
```

### Test 7 — WAL mode is enabled
```
Command: python3 -c "... PRAGMA journal_mode ..."
Output:  PASS — WAL mode confirmed
```

## Flags / uncertainties
- **Migration note:** `state.json` is NOT migrated. Any hashes recorded in the old JSON file are lost. On the first run after this deployment, emails that were previously processed may be processed again (at most once). This is documented and accepted per the brief.
- The module-level `_get_conn().close()` call is not part of the 8 explicit brief steps but is required to satisfy Test 2. It is the minimal addition that creates the DB file on import with no side effects on the public API.

## SYSTEM_STATE update
Brief 004 — state_registry.py — Migrated from JSON flat file to SQLite; fixed race condition via INSERT OR IGNORE; fixed unbounded growth; DB lives at `bluemarlin/src/state_registry.db` — Callers (email_poller.py): `has_been_processed(content)` and `mark_as_processed(content)` signatures and return types unchanged; `state.json` is no longer read or written; old processed hashes are not migrated.

## Dependency impact
Files that import state_registry: `email_poller.py` (original)
What callers should expect differently: None from the caller's perspective. Both public functions behave identically. The underlying storage is now SQLite with atomic inserts (no race condition). The old `state.json` file is abandoned — callers need not change anything.

## Regression check
# BRIEF_004 — state_registry.py — verifies import, DB creation, has_been_processed, mark_as_processed, idempotency, WAL
# Tests: state_registry.py
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import state_registry; print('IMPORT OK')"
python3 -c "import sys, os; sys.path.insert(0, 'bluemarlin/src'); import state_registry; assert os.path.exists(os.path.join('bluemarlin/src','state_registry.db')); print('DB EXISTS OK')"
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import state_registry; assert not state_registry.has_been_processed('regression_check_never_seen'); print('FALSE OK')"
python3 -c "import sys; sys.path.insert(0, 'bluemarlin/src'); import state_registry; state_registry.mark_as_processed('regression_check_mark'); assert state_registry.has_been_processed('regression_check_mark'); print('MARK+CHECK OK')"
python3 -c "import sqlite3, os, sys; sys.path.insert(0, 'bluemarlin/src'); import state_registry; conn=sqlite3.connect(os.path.join('bluemarlin/src','state_registry.db')); assert conn.execute('PRAGMA journal_mode').fetchone()[0]=='wal'; conn.close(); print('WAL OK')"
