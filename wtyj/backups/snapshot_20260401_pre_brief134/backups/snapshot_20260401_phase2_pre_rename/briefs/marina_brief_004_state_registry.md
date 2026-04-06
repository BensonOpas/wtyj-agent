# BRIEF 004 — state_registry.py
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Fix state_registry.py by migrating from a JSON flat file to
SQLite and fixing the race condition in mark_as_processed().
The public API — has_been_processed() and mark_as_processed() —
must stay identical so email_poller.py requires zero changes.
## Context
state_registry.py is the deduplication gate for processed emails.
email_poller.py calls has_been_processed() and mark_as_processed()
with a content fingerprint string before and after processing each
email. If two emails arrive simultaneously, the current JSON
implementation has a race condition: both processes can call
_load_state() before either calls _save_state(), causing one
deduplication record to be lost and the same email to be processed
twice. Additionally the processed_hashes list grows forever with
no size limit, which is a memory and performance problem over time.
SQLite with a UNIQUE constraint and WAL mode solves both problems
atomically.
## File to modify
bluemarlin/src/state_registry.py
## Files to read before making changes
bluemarlin/src/email_poller.py — to understand how the public
API is called before touching anything
## Current behavior
_load_state() reads state.json from the working directory.
_save_state() writes state.json to the working directory.
has_been_processed(content) hashes content, checks if hash is
in the processed_hashes list, returns bool.
mark_as_processed(content) hashes content, appends hash to
processed_hashes list if not present, saves state.json.
Race condition: load → check → append → save is not atomic.
Unbounded growth: processed_hashes list grows forever.
## Required behavior after this change
has_been_processed(content) hashes content, queries SQLite for
the hash, returns bool. Behavior identical to caller.
mark_as_processed(content) hashes content, inserts hash into
SQLite using INSERT OR IGNORE. Atomic — no race condition.
Database file lives at a path constructed from the location of
state_registry.py itself — not from the working directory.
Database is created automatically on first use if it does not exist.
WAL mode enabled on every connection for concurrent read safety.
## Database details
Filename: state_registry.db
Location: same directory as state_registry.py
  (use os.path.dirname(os.path.abspath(__file__)) to get the path)
Table name: processed_hashes
Schema:
  CREATE TABLE IF NOT EXISTS processed_hashes (
      hash TEXT PRIMARY KEY,
      created_at TEXT NOT NULL
  )
WAL mode: PRAGMA journal_mode=WAL — set on every new connection
## Changes required — follow this order exactly
STEP 1
Replace all imports at the top of the file with:
  import hashlib
  import os
  import sqlite3
  from datetime import datetime, timezone
STEP 2
Remove this global entirely:
  STATE_FILE = "state.json"
STEP 3
Add this constant after the imports:
  DB_PATH = os.path.join(
      os.path.dirname(os.path.abspath(__file__)),
      "state_registry.db"
  )
STEP 4
Replace _load_state() and _save_state() with a single
private function _get_conn() that:
  - Opens a SQLite connection to DB_PATH
  - Sets WAL mode: conn.execute("PRAGMA journal_mode=WAL")
  - Creates the table if it does not exist using the schema above
  - Returns the connection
STEP 5
Keep generate_content_hash() exactly as it is.
Do not change it.
STEP 6
Replace has_been_processed() with a SQLite implementation:
  - Call _get_conn()
  - SELECT count(*) FROM processed_hashes WHERE hash = ?
  - Return True if count > 0, False otherwise
  - Close connection when done
STEP 7
Replace mark_as_processed() with a SQLite implementation:
  - Call _get_conn()
  - INSERT OR IGNORE INTO processed_hashes (hash, created_at)
    VALUES (?, ?)
  - Use datetime.now(timezone.utc).isoformat() for created_at
  - Commit the transaction
  - Close connection when done
STEP 8
Add this file header as the very first lines of the file,
before any imports:
  # FILE: state_registry.py
  # CREATED: Before Brief 001 (original codebase)
  # LAST MODIFIED: Brief 004
  # DEPENDS ON: nothing
  # IMPORTS FROM: nothing
  # CALLERS: email_poller.py (original)
## Constraints
- Do not change generate_content_hash() signature or behavior
- Do not change has_been_processed() signature or return type
- Do not change mark_as_processed() signature
- Do not touch email_poller.py
- Do not touch any other file
- Do not install any new packages — sqlite3 is stdlib
- The old state.json file is not migrated — old hashes are lost
  on first run. This is acceptable — worst case is one duplicate
  email processed on restart. Document this in OUTPUT file.
## Test commands
Run all tests from the project root directory.
Report the exact output of each test.
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import state_registry
print('IMPORT OK')
"
# Test 2 — database file created on import
python3 -c "
import sys, os
sys.path.insert(0, 'bluemarlin/src')
import state_registry
db_path = os.path.join('bluemarlin/src', 'state_registry.db')
assert os.path.exists(db_path), f'FAIL: db not found at {db_path}'
print('PASS — db created at', db_path)
"
# Test 3 — has_been_processed returns False for new content
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import state_registry
result = state_registry.has_been_processed('brand_new_content_xyz_123')
assert result == False, f'FAIL: expected False, got {result}'
print('PASS — new content not processed')
"
# Test 4 — mark_as_processed then has_been_processed returns True
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import state_registry
test_content = 'test_email_content_brief_004'
state_registry.mark_as_processed(test_content)
result = state_registry.has_been_processed(test_content)
assert result == True, f'FAIL: expected True, got {result}'
print('PASS — processed content detected correctly')
"
# Test 5 — mark_as_processed is idempotent (no error on duplicate)
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import state_registry
test_content = 'idempotency_test_brief_004'
state_registry.mark_as_processed(test_content)
state_registry.mark_as_processed(test_content)
state_registry.mark_as_processed(test_content)
result = state_registry.has_been_processed(test_content)
assert result == True, 'FAIL'
print('PASS — idempotent insert confirmed')
"
# Test 6 — no json or STATE_FILE remaining in file
python3 -c "
with open('bluemarlin/src/state_registry.py') as f:
    content = f.read()
assert 'import json' not in content, 'FAIL: json import still present'
assert 'STATE_FILE' not in content, 'FAIL: STATE_FILE still present'
assert 'state.json' not in content, 'FAIL: state.json reference still present'
assert 'sqlite3' in content, 'FAIL: sqlite3 not found'
assert 'INSERT OR IGNORE' in content, 'FAIL: atomic insert not found'
print('PASS — file structure correct')
"
# Test 7 — WAL mode is enabled
python3 -c "
import sqlite3, os, sys
sys.path.insert(0, 'bluemarlin/src')
import state_registry
db_path = os.path.join('bluemarlin/src', 'state_registry.db')
conn = sqlite3.connect(db_path)
mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
conn.close()
assert mode == 'wal', f'FAIL: expected wal, got {mode}'
print('PASS — WAL mode confirmed')
"
## Definition of done
- [ ] state_registry.py modified in bluemarlin/src/
- [ ] File header added at top (Brief 004)
- [ ] import json removed
- [ ] STATE_FILE removed
- [ ] sqlite3 used for all state operations
- [ ] DB_PATH constructed from __file__ not working directory
- [ ] WAL mode enabled
- [ ] INSERT OR IGNORE used in mark_as_processed
- [ ] All 7 tests pass with exact output shown
- [ ] OUTPUT_004.md written to bluemarlin/briefs/
- [ ] OUTPUT_004.md includes SYSTEM_STATE update block
- [ ] OUTPUT_004.md includes dependency impact block
- [ ] OUTPUT_004.md includes regression check block
- [ ] OUTPUT_004.md confirms the actual resolved DB_PATH printed during tests
