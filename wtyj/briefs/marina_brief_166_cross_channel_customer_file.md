# BRIEF 166 — Cross-channel customer file
**Status:** Draft | **Files:** state_registry.py, marina_agent.py, email_poller.py, social_agent.py, test_166 (new) | **Depends on:** — | **Blocks:** 167

## Context

Image #76 from Benson (2026-04-08) shows the bug in action. A customer contacts Marina on WhatsApp:

> Customer: "hi, i just sent you an email, did you receive it?"
> Marina: "Hi! I don't have access to the inbox from here, so I can't confirm received emails. If you'd like, share what you need and I can help you directly."
> Customer: "i wait until you have checked the email?"
> Marina: "I won't be able to check it from here — this is a separate chat system. Whatever you sent, just drop it here and I'll sort it out for you."

This is wrong. Marina SHOULD be able to pick up where the customer left off in their email thread. Today:
- Email threads live in `email_thread_state.json` keyed by `subject|from_email`
- WhatsApp threads live in `whatsapp_booking_state` + `whatsapp_threads` keyed by phone
- IG/FB/X DM threads live in the same WhatsApp tables keyed by Zernio conversation_id
- **Nothing joins them**. A customer who touches two channels is two separate blobs of state with no shared identity.

Benson's spec (with SR's contribution):
1. Each real customer has ONE file, shared across every channel they touch
2. When a customer contacts us, look them up by the identifier they arrived with (phone for WhatsApp, email for email, conversation_id for DM) → if known, load the file and inject it into Marina's context
3. If unknown AND the customer references another channel ("did you get my email?", "I have a booking from last week"), Marina asks ONE question: "what's your email or booking number?"
4. On the next turn, Marina extracts the new identifier from the customer's reply. Look up by that identifier. If another customer row matches → **merge** the two into one. Now Marina has the cross-channel history.
5. Marina never makes an external API call or guesses matches. The only bridges between channels are identifiers the customer voluntarily shares.

**Scope constraint (from Benson's feedback):** zero external API calls, no latency on the hot path, no brittle name matching, schema that survives new channels, bounded prompt size.

## Why This Approach

**Schema: two tables, not flat columns.** A `customers` table (one row per real person) plus a `customer_identifiers` table (many rows per customer, typed by `type` string — `"email"`, `"phone"`, `"wa_conversation_id"`, etc.). Flat columns were rejected because adding a new channel would require a schema migration every time. The typed identifier table scales to new channels with zero DDL change — just a new `type` string.

**Lookup on every inbound, hot path.** Every inbound message runs a single indexed SELECT on `(type, value)`. Sub-millisecond at any realistic scale. If no match, create a new customer + identifier row atomically (one transaction). No external calls.

**Bounded prompt context.** Marina's CUSTOMER FILE block is capped at ~400 tokens regardless of customer history: display name, known identifiers grouped by channel, last 5 interaction summaries, any active bookings (refs + status only). No raw chat logs, no full email bodies. A 500-interaction customer costs the same Marina latency as a 5-interaction customer.

**Merge via identifier, audited.** When Marina extracts a new identifier from a message (e.g. customer WhatsApps us with their email), after her call we do `customer_lookup(type, value)` — if it returns a DIFFERENT customer_id than the current one, run `customer_merge()` which moves all identifiers and interactions to the surviving row inside a transaction, writes an audit log row in `customer_merges`, and deletes the absorbed row. Merge is idempotent (re-running is a no-op).

**Not in scope for Brief 166** (deferred to follow-ups):
- LLM-generated rolling customer summaries (follow-up brief)
- Backfill from existing `whatsapp_threads` + `email_thread_state.json` (separate one-time script)
- Dashboard "Customer" tab showing the file (dashboard brief)
- Race condition testing under concurrent inbound load (Brief 161's per-phone locks already cover the social path)
- Automatic email pattern detection ("john.smith@...") → name guessing

## Source Material

### state_registry.py DDL pattern

`_get_conn()` at line 16 is called on every DB access and contains all `CREATE TABLE IF NOT EXISTS` statements. New tables should be added there so any fresh DB auto-creates them and existing DBs get them on next access. Example pattern used for `processed_hashes` (line 53-57) and `whatsapp_threads` (line 109-121). Column migrations use `try/except sqlite3.OperationalError: pass` around `ALTER TABLE ADD COLUMN` (e.g. lines 123-130).

### marina_agent.process_message signature

`marina_agent.py:599-608`:
```python
def process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
    channel: str = "email",
    messages: list = None,
) -> dict:
```

Called from:
- `social_agent.py:213` (escalation pre-check)
- `social_agent.py:286` (main orchestrator call)
- `email_poller.py:666` (WhatsApp relay from email path)
- `email_poller.py:692` (email relay response)
- `email_poller.py:742` (escalation pre-check)
- `email_poller.py:813` (main email loop call)

### Inbound identifier extraction points

**Email (email_poller.py main loop):** `from_email` is already extracted at line 510. That's the customer identifier. Customer display name is `from_name` from the same parseaddr call.

**Social (social_agent.handle_incoming_whatsapp_message):** the `phone` parameter IS the identifier — for legacy Meta WhatsApp it's a phone number, for Zernio WhatsApp/IG/FB/X it's a 24-char hex conversation_id. The `from_name` kwarg is the display name (Zernio provides the profile name).

Distinguishing between real phone and Zernio conversation_id: Brief 159's `_is_zernio_conversation_id` helper in `whatsapp_client.py` — 24 hex chars. Type string: `"phone"` for real phone numbers, `"wa_conversation_id"` for Zernio hex ids. For IG/FB/X, use `"ig_conversation_id"`, `"fb_conversation_id"`, `"x_conversation_id"` (or just all of them store as `"zernio_{channel}_id"`). Simplest: use `"wa_conversation_id"` when channel=whatsapp and `"dm_conversation_id_{channel}"` for the rest.

Actually even simpler: we have `msg["channel"]` in the Zernio webhook payload (`whatsapp`, `instagram_dm`, `facebook_dm`, `twitter_dm`). Use `f"zernio_{channel}"` as the type string. So types become:

- `"email"`
- `"phone"` (real phone number, only for legacy Meta WhatsApp)
- `"zernio_whatsapp"`
- `"zernio_instagram_dm"`
- `"zernio_facebook_dm"`
- `"zernio_twitter_dm"`

This is the set. Adding a new channel later = new type string, no DDL change.

### Baseline

762 tests passing (Brief 165).

## Instructions

### Step 1: Add schema + helper functions in `state_registry.py`

Add three new tables near the existing DDL (after `whatsapp_booking_state` at ~line 144):

```python
    # Brief 166: cross-channel customer file
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "display_name TEXT DEFAULT '', "
        "summary TEXT DEFAULT '', "
        "notes TEXT DEFAULT '', "
        "first_seen TEXT NOT NULL, "
        "last_seen TEXT NOT NULL, "
        "active INTEGER DEFAULT 1"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customer_identifiers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "customer_id INTEGER NOT NULL, "
        "type TEXT NOT NULL, "
        "value TEXT NOT NULL, "
        "first_seen TEXT NOT NULL, "
        "FOREIGN KEY (customer_id) REFERENCES customers(id)"
        ")"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_identifiers_type_value "
        "ON customer_identifiers(type, value)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_identifiers_customer "
        "ON customer_identifiers(customer_id)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customer_interactions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "customer_id INTEGER NOT NULL, "
        "channel TEXT NOT NULL, "
        "summary TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "FOREIGN KEY (customer_id) REFERENCES customers(id)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_customer_interactions_customer "
        "ON customer_interactions(customer_id, created_at)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS customer_merges ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "surviving_id INTEGER NOT NULL, "
        "absorbed_id INTEGER NOT NULL, "
        "merged_at TEXT NOT NULL"
        ")"
    )
```

Then add helper functions at the end of `state_registry.py` (before any `# === end of file ===` marker):

```python
# ==================== Brief 166: Cross-channel customer file ====================

def customer_lookup(type_: str, value: str) -> dict | None:
    """Brief 166: look up a customer by an identifier. Returns None if not found.
    Returns a dict with id, display_name, summary, first_seen, last_seen."""
    if not type_ or not value:
        return None
    conn = _get_conn()
    row = conn.execute(
        "SELECT c.id, c.display_name, c.summary, c.notes, c.first_seen, c.last_seen "
        "FROM customers c "
        "INNER JOIN customer_identifiers ci ON ci.customer_id = c.id "
        "WHERE ci.type = ? AND ci.value = ? AND c.active = 1 "
        "LIMIT 1",
        (type_, value.strip())
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "display_name": row[1], "summary": row[2],
        "notes": row[3], "first_seen": row[4], "last_seen": row[5],
    }


def customer_lookup_or_create(type_: str, value: str, display_name: str = "") -> dict:
    """Brief 166: look up a customer by identifier, or create a new row if not found.
    If a new row is created, the first identifier is recorded with the given display_name.
    Idempotent — safe to call on every inbound message."""
    if not type_ or not value:
        raise ValueError("type and value required")
    existing = customer_lookup(type_, value)
    if existing:
        # Optionally refresh display_name if we got a better one and the existing is blank
        if display_name and not existing["display_name"]:
            conn = _get_conn()
            conn.execute(
                "UPDATE customers SET display_name = ?, last_seen = ? WHERE id = ?",
                (display_name, datetime.now(timezone.utc).isoformat(), existing["id"])
            )
            conn.commit()
            conn.close()
            existing["display_name"] = display_name
        return existing
    # Create new customer + identifier atomically
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO customers (display_name, first_seen, last_seen) VALUES (?, ?, ?)",
            (display_name or "", now, now)
        )
        customer_id = cur.lastrowid
        conn.execute(
            "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) VALUES (?, ?, ?, ?)",
            (customer_id, type_, value.strip(), now)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Race: another inbound created the row between lookup and insert. Retry lookup.
        conn.rollback()
        conn.close()
        existing = customer_lookup(type_, value)
        if existing:
            return existing
        raise
    conn.close()
    return {
        "id": customer_id, "display_name": display_name or "",
        "summary": "", "notes": "",
        "first_seen": now, "last_seen": now,
    }


def customer_add_identifier(customer_id: int, type_: str, value: str) -> dict:
    """Brief 166: add a new identifier to an existing customer. Handles the cross-channel
    merge case: if the (type, value) already belongs to a DIFFERENT customer, merge them.
    Returns a dict: {"action": "added" | "merged" | "already_linked", "customer_id": int}.
    """
    if not type_ or not value:
        return {"action": "noop", "customer_id": customer_id}
    value = value.strip()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    existing_row = conn.execute(
        "SELECT customer_id FROM customer_identifiers WHERE type = ? AND value = ?",
        (type_, value)
    ).fetchone()
    if existing_row:
        existing_customer_id = existing_row[0]
        conn.close()
        if existing_customer_id == customer_id:
            return {"action": "already_linked", "customer_id": customer_id}
        # Cross-channel merge: absorb the smaller-id row into the larger (or keep the older).
        # We keep the OLDER customer (lower first_seen) as the surviving row.
        surviving, absorbed = _customer_choose_merge_survivor(customer_id, existing_customer_id)
        customer_merge(surviving, absorbed)
        return {"action": "merged", "customer_id": surviving}
    # No conflict — add the identifier
    try:
        conn.execute(
            "INSERT INTO customer_identifiers (customer_id, type, value, first_seen) VALUES (?, ?, ?, ?)",
            (customer_id, type_, value, now)
        )
        conn.execute(
            "UPDATE customers SET last_seen = ? WHERE id = ?",
            (now, customer_id)
        )
        conn.commit()
        conn.close()
        return {"action": "added", "customer_id": customer_id}
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        # Race — retry the add path by re-resolving
        return customer_add_identifier(customer_id, type_, value)


def _customer_choose_merge_survivor(a_id: int, b_id: int) -> tuple:
    """Brief 166: pick which of two customer rows survives a merge.
    Policy: the one with the EARLIER first_seen wins (older customer = canonical).
    Returns (surviving_id, absorbed_id)."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, first_seen FROM customers WHERE id IN (?, ?)", (a_id, b_id)
    ).fetchall()
    conn.close()
    if len(rows) != 2:
        return (a_id, b_id)
    rows.sort(key=lambda r: r[1])  # earliest first_seen first
    return (rows[0][0], rows[1][0])


def customer_merge(surviving_id: int, absorbed_id: int) -> dict:
    """Brief 166: merge absorbed_id into surviving_id. Moves identifiers and interactions
    to the surviving row, writes an audit row, deletes the absorbed row. Idempotent."""
    if surviving_id == absorbed_id:
        return {"action": "noop"}
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    # Move identifiers (ignore duplicates — the UNIQUE constraint prevents insertion,
    # so we DELETE duplicates from the absorbed row first, then UPDATE the rest).
    conn.execute(
        "DELETE FROM customer_identifiers WHERE customer_id = ? AND (type, value) IN "
        "(SELECT type, value FROM customer_identifiers WHERE customer_id = ?)",
        (absorbed_id, surviving_id)
    )
    conn.execute(
        "UPDATE customer_identifiers SET customer_id = ? WHERE customer_id = ?",
        (surviving_id, absorbed_id)
    )
    # Move interactions
    conn.execute(
        "UPDATE customer_interactions SET customer_id = ? WHERE customer_id = ?",
        (surviving_id, absorbed_id)
    )
    # Fold display_name if surviving is empty
    conn.execute(
        "UPDATE customers SET display_name = COALESCE(NULLIF(display_name, ''), "
        "  (SELECT display_name FROM customers WHERE id = ?)), "
        "last_seen = ? WHERE id = ?",
        (absorbed_id, now, surviving_id)
    )
    # Audit
    conn.execute(
        "INSERT INTO customer_merges (surviving_id, absorbed_id, merged_at) VALUES (?, ?, ?)",
        (surviving_id, absorbed_id, now)
    )
    # Deactivate the absorbed row (soft delete for audit)
    conn.execute("UPDATE customers SET active = 0 WHERE id = ?", (absorbed_id,))
    conn.commit()
    conn.close()
    return {"action": "merged", "surviving_id": surviving_id, "absorbed_id": absorbed_id}


def customer_record_interaction(customer_id: int, channel: str, summary: str):
    """Brief 166: append a one-line interaction summary for a customer. Updates last_seen."""
    if not customer_id or not channel or not summary:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO customer_interactions (customer_id, channel, summary, created_at) "
        "VALUES (?, ?, ?, ?)",
        (customer_id, channel, summary[:500], now)
    )
    conn.execute("UPDATE customers SET last_seen = ? WHERE id = ?", (now, customer_id))
    conn.commit()
    conn.close()


def customer_get_full(customer_id: int) -> dict:
    """Brief 166: return the full customer file — identities + recent interactions.
    Used by marina_agent to build the CUSTOMER FILE prompt block.
    Caps identifiers to 20 and interactions to the last 5 (prompt-size safety)."""
    if not customer_id:
        return {}
    conn = _get_conn()
    c_row = conn.execute(
        "SELECT id, display_name, summary, notes, first_seen, last_seen "
        "FROM customers WHERE id = ? AND active = 1",
        (customer_id,)
    ).fetchone()
    if not c_row:
        conn.close()
        return {}
    id_rows = conn.execute(
        "SELECT type, value, first_seen FROM customer_identifiers "
        "WHERE customer_id = ? ORDER BY first_seen LIMIT 20",
        (customer_id,)
    ).fetchall()
    int_rows = conn.execute(
        "SELECT channel, summary, created_at FROM customer_interactions "
        "WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5",
        (customer_id,)
    ).fetchall()
    conn.close()
    return {
        "id": c_row[0], "display_name": c_row[1], "summary": c_row[2],
        "notes": c_row[3], "first_seen": c_row[4], "last_seen": c_row[5],
        "identifiers": [{"type": r[0], "value": r[1], "first_seen": r[2]} for r in id_rows],
        "recent_interactions": [
            {"channel": r[0], "summary": r[1], "created_at": r[2]} for r in int_rows
        ],
    }
```

### Step 2: Add `_build_customer_file_block` and plumb into `marina_agent.py`

Near the top of `marina_agent.py`, add the helper:

```python
def _build_customer_file_block(customer_file: dict | None) -> str:
    """Brief 166: render the CUSTOMER FILE prompt block from a customer_get_full() dict.
    Empty/None input returns an empty string (block is omitted entirely).
    Capped at ~400 tokens by limiting identifiers (20) and interactions (5)."""
    if not customer_file or not customer_file.get("id"):
        return ""
    lines = ["CUSTOMER FILE — use this context when answering this customer. "
             "This person may have contacted us before across email, WhatsApp, Instagram, "
             "Facebook, or X. Use the identifiers and interaction history below to answer "
             "with continuity; reference past questions or bookings naturally when relevant."]
    name = customer_file.get("display_name") or "(no name on file)"
    lines.append(f"\nDisplay name: {name}")
    first_seen = customer_file.get("first_seen", "")
    last_seen = customer_file.get("last_seen", "")
    if first_seen:
        lines.append(f"First contact: {first_seen[:10]}  |  Last contact: {last_seen[:10]}")
    ids = customer_file.get("identifiers") or []
    if ids:
        lines.append("\nKnown identifiers (used across channels):")
        for ident in ids:
            lines.append(f"  - {ident['type']}: {ident['value']}")
    recent = customer_file.get("recent_interactions") or []
    if recent:
        lines.append("\nRecent interactions (newest first, across all channels):")
        for r in recent:
            date = (r.get("created_at") or "")[:10]
            lines.append(f"  - [{date}] [{r.get('channel', '?')}] {r.get('summary', '')}")
    summary = customer_file.get("summary") or ""
    if summary:
        lines.append(f"\nRolling summary: {summary}")
    lines.append(
        "\nCROSS-CHANNEL REFERENCE RULE: if the customer references a channel or interaction "
        "you do NOT see in the CUSTOMER FILE above (e.g. 'did you get my email?', 'I booked "
        "last week'), ask ONE short question to link them — 'sure, what's your email or booking "
        "reference?' — and wait for their next reply. Do NOT claim you have no access to other "
        "channels; you do. Once they share an identifier you can look up, you will have their "
        "full history."
    )
    return "\n".join(lines)
```

Modify `_build_system_prompt` to accept an optional `customer_file` parameter and inject the block between `AGENT PERSONA` and `WRITING STYLE`:

```python
def _build_system_prompt(thread_flags: dict, channel: str = "email",
                         customer_file: dict | None = None) -> str:
    ...
    customer_file_block = _build_customer_file_block(customer_file)
    ...
    return f"""You are {business.get('agent_name', 'Marina')}, the booking agent for {business.get('name', 'the business')}.
{relay_mode_section}{fully_escalated_section}
AGENT PERSONA:
{_build_agent_persona_block()}

{customer_file_block}

{writing_style_block}
...
```

(When `customer_file_block` is empty, the extra blank lines render as a single blank line — harmless.)

Modify `process_message` to accept and pass through `customer_file`:

```python
def process_message(
    from_email: str,
    subject: str,
    body: str,
    thread_fields: dict,
    thread_flags: dict,
    action_context: str = "",
    channel: str = "email",
    messages: list = None,
    customer_file: dict | None = None,
) -> dict:
    ...
    system_prompt = _build_system_prompt(thread_flags, channel=channel, customer_file=customer_file)
    ...
```

### Step 3: Integrate customer lookup into `email_poller.py` main loop

In `email_poller.py` around the main Marina call at line 813, BEFORE the call:

```python
                # Brief 166: cross-channel customer lookup
                _cust_file = None
                try:
                    _cust = state_registry.customer_lookup_or_create(
                        "email", from_email, display_name=from_name or ""
                    )
                    _cust_file = state_registry.customer_get_full(_cust["id"])
                except Exception as _e:
                    log(f"customer_lookup_failed email={from_email} err={_e}")
                    _cust_file = None
```

Pass `customer_file=_cust_file` to the `marina_agent.process_message(...)` call at line 813.

AFTER Marina returns, record the interaction and handle cross-channel merge for any new identifiers extracted:

```python
                # Brief 166: record interaction + handle cross-channel identifier merge
                if _cust and _cust.get("id"):
                    try:
                        _summary = f"Email thread: {subj[:80]}"
                        state_registry.customer_record_interaction(_cust["id"], "email", _summary)
                        # Merge in any new identifiers Marina extracted
                        _new_fields = result.get("fields", {}) or {}
                        for _ftype, _fkey in (("email", "email"), ("phone", "phone")):
                            _val = _new_fields.get(_fkey)
                            if _val and _val != from_email:
                                state_registry.customer_add_identifier(_cust["id"], _ftype, _val)
                    except Exception as _e:
                        log(f"customer_postprocess_failed err={_e}")
```

### Step 4: Integrate customer lookup into `social_agent.handle_incoming_whatsapp_message`

At the top of the main Marina call site (line 286 region), before the call:

```python
        # Brief 166: cross-channel customer lookup
        _cust_type = "wa_conversation_id" if _is_zernio_conversation_id(phone) else "phone"
        # For IG/FB/X DMs (where phone is a Zernio conversation_id and channel != whatsapp),
        # use the specific type so those conversations don't accidentally merge with WhatsApp.
        _zernio_channel = _msg_meta.get("zernio_channel") if isinstance(_msg_meta, dict) else None
        if _zernio_channel and _zernio_channel != "whatsapp":
            _cust_type = f"zernio_{_zernio_channel}"
        _cust_file_obj = None
        _cust_row = None
        try:
            _cust_row = state_registry.customer_lookup_or_create(
                _cust_type, phone, display_name=from_name or ""
            )
            _cust_file_obj = state_registry.customer_get_full(_cust_row["id"])
        except Exception as _e:
            bm_logger.log("customer_lookup_failed", phone=phone, error=str(_e))
```

Pass `customer_file=_cust_file_obj` to `marina_agent.process_message(...)` at line 286 (and at line 213 for the escalation pre-check — use the same lookup result).

After Marina returns, record interaction and merge new identifiers:

```python
        # Brief 166: record + merge new identifiers
        if _cust_row and _cust_row.get("id"):
            try:
                _summary = f"WhatsApp/DM: {text[:80]}"
                state_registry.customer_record_interaction(_cust_row["id"], channel or "whatsapp", _summary)
                _new_fields = result.get("fields", {}) or {}
                for _ftype, _fkey in (("email", "email"), ("phone", "phone")):
                    _val = _new_fields.get(_fkey)
                    if _val and _val != phone:
                        state_registry.customer_add_identifier(_cust_row["id"], _ftype, _val)
            except Exception as _e:
                bm_logger.log("customer_postprocess_failed", phone=phone, error=str(_e))
```

The helper `_is_zernio_conversation_id` already exists from Brief 159 — import from `whatsapp_client`.

### Step 5: Tests (`wtyj/tests/marina/test_166_customer_file.py`)

```python
"""Tests for Brief 166 — cross-channel customer file.

Covers:
- Schema: tables exist after _get_conn()
- customer_lookup returns None for unknown, dict for known
- customer_lookup_or_create is idempotent
- customer_add_identifier adds + triggers merge when cross-channel collision
- customer_merge moves identifiers + interactions
- customer_get_full caps to 5 interactions, 20 identifiers
- _build_customer_file_block empty input → empty string, populated → prompt text
- marina_agent._build_system_prompt includes CUSTOMER FILE block when customer_file passed
- marina_agent.process_message accepts customer_file kwarg (signature regression)
"""
import os
from datetime import datetime, timezone

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry
from agents.marina import marina_agent


def _cleanup(ids):
    conn = state_registry._get_conn()
    for cid in ids:
        conn.execute("DELETE FROM customer_interactions WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customer_identifiers WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
        conn.execute("DELETE FROM customer_merges WHERE surviving_id = ? OR absorbed_id = ?", (cid, cid))
    conn.commit()
    conn.close()


def test_schema_customers_table_exists():
    """Brief 166: the customers table must be created by _get_conn()."""
    conn = state_registry._get_conn()
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customers'").fetchone()
    conn.close()
    assert row is not None, "customers table missing"


def test_schema_customer_identifiers_table_exists():
    conn = state_registry._get_conn()
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customer_identifiers'").fetchone()
    conn.close()
    assert row is not None, "customer_identifiers table missing"


def test_schema_customer_identifiers_has_unique_index():
    """Brief 166: UNIQUE (type, value) index is load-bearing for race safety."""
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='customer_identifiers'"
    ).fetchall()
    conn.close()
    names = [r[0] for r in rows]
    assert any("idx_customer_identifiers_type_value" in n for n in names)


def test_customer_lookup_returns_none_for_unknown():
    assert state_registry.customer_lookup("email", "nobody@nowhere.test") is None


def test_customer_lookup_or_create_creates_new():
    result = state_registry.customer_lookup_or_create("email", "alice@test.test", display_name="Alice T")
    assert result["id"] > 0
    assert result["display_name"] == "Alice T"
    _cleanup([result["id"]])


def test_customer_lookup_or_create_is_idempotent():
    a = state_registry.customer_lookup_or_create("email", "bob@test.test", display_name="Bob")
    b = state_registry.customer_lookup_or_create("email", "bob@test.test", display_name="Bob")
    assert a["id"] == b["id"]
    _cleanup([a["id"]])


def test_customer_add_identifier_merges_on_cross_channel_collision():
    """Brief 166: the Calvin scenario.
    Customer contacts us on WhatsApp → record with wa_conversation_id.
    Later, on a different channel, we learn their email and it turns out the email
    is already linked to another customer row → merge."""
    wa = state_registry.customer_lookup_or_create(
        "wa_conversation_id", "69d41ae77d2c605d08114697", display_name="Calvin"
    )
    em = state_registry.customer_lookup_or_create(
        "email", "calvin@gaimin.io", display_name="Calvin Adamus"
    )
    assert wa["id"] != em["id"]  # separate rows initially
    # Now link email to wa customer. This should merge.
    result = state_registry.customer_add_identifier(wa["id"], "email", "calvin@gaimin.io")
    assert result["action"] == "merged"
    surviving_id = result["customer_id"]
    # Surviving customer has BOTH identifiers
    full = state_registry.customer_get_full(surviving_id)
    ident_values = {i["value"] for i in full["identifiers"]}
    assert "69d41ae77d2c605d08114697" in ident_values
    assert "calvin@gaimin.io" in ident_values
    _cleanup([wa["id"], em["id"]])


def test_customer_add_identifier_no_conflict_adds_cleanly():
    """Brief 166: new identifier, no existing customer has it → added to current customer."""
    c = state_registry.customer_lookup_or_create("email", "dave@test.test")
    result = state_registry.customer_add_identifier(c["id"], "phone", "+1-555-0001")
    assert result["action"] == "added"
    assert result["customer_id"] == c["id"]
    full = state_registry.customer_get_full(c["id"])
    assert len(full["identifiers"]) == 2
    _cleanup([c["id"]])


def test_customer_add_identifier_already_linked_noop():
    c = state_registry.customer_lookup_or_create("email", "eve@test.test")
    result = state_registry.customer_add_identifier(c["id"], "email", "eve@test.test")
    assert result["action"] == "already_linked"
    _cleanup([c["id"]])


def test_customer_record_interaction_appends():
    c = state_registry.customer_lookup_or_create("email", "frank@test.test")
    state_registry.customer_record_interaction(c["id"], "email", "First booking inquiry")
    state_registry.customer_record_interaction(c["id"], "whatsapp", "Follow up about date")
    full = state_registry.customer_get_full(c["id"])
    assert len(full["recent_interactions"]) == 2
    # Newest first
    assert full["recent_interactions"][0]["summary"] == "Follow up about date"
    _cleanup([c["id"]])


def test_customer_get_full_caps_interactions_to_five():
    c = state_registry.customer_lookup_or_create("email", "grace@test.test")
    for i in range(10):
        state_registry.customer_record_interaction(c["id"], "email", f"interaction {i}")
    full = state_registry.customer_get_full(c["id"])
    assert len(full["recent_interactions"]) == 5
    _cleanup([c["id"]])


def test_customer_merge_audit_row_written():
    a = state_registry.customer_lookup_or_create("email", "hank1@test.test")
    b = state_registry.customer_lookup_or_create("email", "hank2@test.test")
    state_registry.customer_merge(a["id"], b["id"])
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT surviving_id, absorbed_id FROM customer_merges WHERE surviving_id = ? AND absorbed_id = ?",
        (a["id"], b["id"])
    ).fetchone()
    conn.close()
    assert row is not None
    _cleanup([a["id"], b["id"]])


def test_build_customer_file_block_empty():
    assert marina_agent._build_customer_file_block(None) == ""
    assert marina_agent._build_customer_file_block({}) == ""


def test_build_customer_file_block_populated():
    block = marina_agent._build_customer_file_block({
        "id": 1,
        "display_name": "Calvin",
        "first_seen": "2026-03-01T12:00:00+00:00",
        "last_seen": "2026-04-08T00:00:00+00:00",
        "identifiers": [
            {"type": "email", "value": "calvin@gaimin.io", "first_seen": ""},
            {"type": "wa_conversation_id", "value": "69d41ae77d2c...", "first_seen": ""},
        ],
        "recent_interactions": [
            {"channel": "email", "summary": "Asked about wheelchair", "created_at": "2026-04-08T01:00:00+00:00"},
        ],
    })
    assert "CUSTOMER FILE" in block
    assert "Calvin" in block
    assert "calvin@gaimin.io" in block
    assert "wheelchair" in block
    assert "CROSS-CHANNEL REFERENCE RULE" in block


def test_system_prompt_includes_customer_file_when_passed():
    customer_file = {
        "id": 1, "display_name": "TestCustomer",
        "first_seen": "2026-01-01T00:00:00+00:00",
        "last_seen": "2026-01-01T00:00:00+00:00",
        "identifiers": [{"type": "email", "value": "test@test.test", "first_seen": ""}],
        "recent_interactions": [],
    }
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp", customer_file=customer_file)
    assert "CUSTOMER FILE" in prompt
    assert "TestCustomer" in prompt


def test_system_prompt_without_customer_file_has_no_block():
    prompt = marina_agent._build_system_prompt({}, channel="whatsapp")
    # The CUSTOMER FILE block should not appear
    assert "CUSTOMER FILE — use this context" not in prompt
```

### Step 6: Run tests + regression + typecheck-equivalent (no frontend changes)

```bash
python3 -m pytest wtyj/tests/marina/test_166_customer_file.py -v --tb=short
python3 -m pytest wtyj/tests/ -q --tb=line
```

Expected: 15+ new tests pass, 777+ total (762 baseline + 15 new).

### Step 7: Commit + deploy

```bash
git add wtyj/shared/state_registry.py wtyj/agents/marina/marina_agent.py \
        wtyj/agents/marina/email_poller.py wtyj/agents/social/social_agent.py \
        wtyj/tests/marina/test_166_customer_file.py \
        wtyj/briefs/marina_brief_166_cross_channel_customer_file.md
git commit -m "Brief 166: cross-channel customer file"
git push origin main

ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

## Success Condition

1. `customers`, `customer_identifiers`, `customer_interactions`, `customer_merges` tables exist and auto-create on fresh DB
2. `customer_lookup_or_create` is idempotent
3. `customer_add_identifier` correctly merges on cross-channel collision
4. Marina's prompt contains `CUSTOMER FILE` block when a customer_file is passed, does not when None
5. 15+ new tests pass, 777+ total / 0 failures
6. Both containers healthy post-deploy

## Rollback

Revert the commit. Tables persist but are unused by old code (no behavioral impact from leaving them). For a clean rollback: drop the four tables manually on the VPS SQLite.
