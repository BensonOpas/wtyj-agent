"""Tests for Brief 166 — cross-channel customer file.

Covers:
- Schema tables and indexes
- customer_lookup / customer_lookup_or_create (idempotent)
- customer_add_identifier (add / already_linked / merge)
- customer_merge audit + identifier migration
- customer_get_full caps interactions to 5
- _build_customer_file_block empty vs populated
- _build_system_prompt includes CUSTOMER FILE block when customer_file passed
- process_message signature accepts customer_file kwarg
"""
import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from shared import state_registry
from agents.marina import marina_agent


def _cleanup(ids):
    conn = state_registry._get_conn()
    for cid in ids:
        conn.execute("DELETE FROM customer_interactions WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customer_identifiers WHERE customer_id = ?", (cid,))
        conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
        conn.execute(
            "DELETE FROM customer_merges WHERE surviving_id = ? OR absorbed_id = ?",
            (cid, cid),
        )
    conn.commit()
    conn.close()


# --- Schema ---

def test_schema_customers_table_exists():
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='customers'"
    ).fetchone()
    conn.close()
    assert row is not None, "customers table missing"


def test_schema_customer_identifiers_table_exists():
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='customer_identifiers'"
    ).fetchone()
    conn.close()
    assert row is not None, "customer_identifiers table missing"


def test_schema_customer_identifiers_has_unique_index():
    """Brief 166: UNIQUE (type, value) index is load-bearing for race safety."""
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='customer_identifiers'"
    ).fetchall()
    conn.close()
    names = [r[0] for r in rows]
    assert any("idx_customer_identifiers_type_value" in n for n in names)


def test_schema_customer_interactions_table_exists():
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='customer_interactions'"
    ).fetchone()
    conn.close()
    assert row is not None


def test_schema_customer_merges_table_exists():
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='customer_merges'"
    ).fetchone()
    conn.close()
    assert row is not None


# --- Lookup / create ---

def test_customer_lookup_returns_none_for_unknown():
    assert state_registry.customer_lookup("email", "nobody@nowhere.test") is None


def test_customer_lookup_or_create_creates_new():
    result = state_registry.customer_lookup_or_create(
        "email", "alice@test166.test", display_name="Alice T"
    )
    assert result["id"] > 0
    assert result["display_name"] == "Alice T"
    _cleanup([result["id"]])


def test_customer_lookup_or_create_is_idempotent():
    a = state_registry.customer_lookup_or_create("email", "bob@test166.test", display_name="Bob")
    b = state_registry.customer_lookup_or_create("email", "bob@test166.test", display_name="Bob")
    assert a["id"] == b["id"]
    _cleanup([a["id"]])


def test_customer_lookup_or_create_backfills_display_name():
    """Brief 166: if the existing row has a blank display_name, a later lookup
    with a name populates it."""
    a = state_registry.customer_lookup_or_create("email", "carol@test166.test")
    assert a["display_name"] == ""
    b = state_registry.customer_lookup_or_create("email", "carol@test166.test", display_name="Carol")
    assert b["display_name"] == "Carol"
    _cleanup([a["id"]])


# --- Identifier / merge ---

def test_customer_add_identifier_merges_on_cross_channel_collision():
    """Brief 166: the Calvin scenario.
    Customer contacts us on WhatsApp → row with wa_conversation_id.
    Later, we learn their email and it's already linked to a different row → merge."""
    wa = state_registry.customer_lookup_or_create(
        "wa_conversation_id", "69d41ae77d2c605d08114697_t166", display_name="Calvin"
    )
    em = state_registry.customer_lookup_or_create(
        "email", "calvin_t166@gaimin.io", display_name="Calvin Adamus"
    )
    assert wa["id"] != em["id"]
    result = state_registry.customer_add_identifier(wa["id"], "email", "calvin_t166@gaimin.io")
    assert result["action"] == "merged"
    surviving_id = result["customer_id"]
    full = state_registry.customer_get_full(surviving_id)
    ident_values = {i["value"] for i in full["identifiers"]}
    assert "69d41ae77d2c605d08114697_t166" in ident_values
    assert "calvin_t166@gaimin.io" in ident_values
    _cleanup([wa["id"], em["id"]])


def test_customer_add_identifier_no_conflict_adds_cleanly():
    c = state_registry.customer_lookup_or_create("email", "dave@test166.test")
    result = state_registry.customer_add_identifier(c["id"], "phone", "+1-555-0001-t166")
    assert result["action"] == "added"
    assert result["customer_id"] == c["id"]
    full = state_registry.customer_get_full(c["id"])
    assert len(full["identifiers"]) == 2
    _cleanup([c["id"]])


def test_customer_add_identifier_already_linked_noop():
    c = state_registry.customer_lookup_or_create("email", "eve@test166.test")
    result = state_registry.customer_add_identifier(c["id"], "email", "eve@test166.test")
    assert result["action"] == "already_linked"
    _cleanup([c["id"]])


def test_customer_merge_audit_row_written():
    a = state_registry.customer_lookup_or_create("email", "hank1@test166.test")
    b = state_registry.customer_lookup_or_create("email", "hank2@test166.test")
    state_registry.customer_merge(a["id"], b["id"])
    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT surviving_id, absorbed_id FROM customer_merges "
        "WHERE surviving_id = ? AND absorbed_id = ?",
        (a["id"], b["id"]),
    ).fetchone()
    conn.close()
    assert row is not None
    _cleanup([a["id"], b["id"]])


# --- Interactions ---

def test_customer_record_interaction_appends():
    c = state_registry.customer_lookup_or_create("email", "frank@test166.test")
    state_registry.customer_record_interaction(c["id"], "email", "First booking inquiry")
    state_registry.customer_record_interaction(c["id"], "whatsapp", "Follow up about date")
    full = state_registry.customer_get_full(c["id"])
    assert len(full["recent_interactions"]) == 2
    assert full["recent_interactions"][0]["summary"] == "Follow up about date"
    _cleanup([c["id"]])


def test_customer_get_full_caps_interactions_to_five():
    c = state_registry.customer_lookup_or_create("email", "grace@test166.test")
    for i in range(10):
        state_registry.customer_record_interaction(c["id"], "email", f"interaction {i}")
    full = state_registry.customer_get_full(c["id"])
    assert len(full["recent_interactions"]) == 5
    _cleanup([c["id"]])


# --- Prompt block ---

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
            {"type": "wa_conversation_id", "value": "69d41ae77d2c", "first_seen": ""},
        ],
        "recent_interactions": [
            {"channel": "email", "summary": "Asked about wheelchair",
             "created_at": "2026-04-08T01:00:00+00:00"},
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
    assert "CUSTOMER FILE — use this context" not in prompt


def test_process_message_accepts_customer_file_kwarg():
    """Brief 166: signature regression — the kwarg must be accepted without error."""
    import inspect
    sig = inspect.signature(marina_agent.process_message)
    assert "customer_file" in sig.parameters
