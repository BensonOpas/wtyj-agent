"""Tests for Brief 233 — distinguish operator-typed email replies from
Marina-generated ones via a `role="operator"` value on the persisted
message."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from shared import state_registry


def _seed_thread(tmp_path, monkeypatch, customer_email, with_customer=True):
    """Write a fake email_thread_state.json with one customer message
    and monkeypatch the path resolver. Returns the thread_key."""
    thread_key = f"subj:{customer_email}:test233"
    messages = []
    if with_customer:
        messages.append({
            "role": "customer",
            "ts": "2026-05-08T10:00:00+00:00",
            "body": "Hi, can you help?",
        })
    state = {
        "threads": {
            thread_key: {
                "messages": messages,
                "fields": {},
                "flags": {},
            }
        }
    }
    fake_path = tmp_path / "email_thread_state.json"
    fake_path.write_text(json.dumps(state))
    monkeypatch.setattr(state_registry, "_get_email_state_path",
                        lambda: str(fake_path))
    return thread_key, fake_path


def test_default_role_is_marina(tmp_path, monkeypatch):
    """Brief 233: backward compat — calls without an explicit role
    persist as `marina` so legacy callers (Brief 214 guidance path) keep
    working."""
    customer = "test233-alice@example.com"
    thread_key, fake_path = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Marina's reformulated reply")
    state = json.loads(fake_path.read_text())
    last = state["threads"][thread_key]["messages"][-1]
    assert last["role"] == "marina"


def test_operator_role_persisted_when_specified(tmp_path, monkeypatch):
    """Brief 233: passing role='operator' stores the new value verbatim."""
    customer = "test233-bob@example.com"
    thread_key, fake_path = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Operator's verbatim reply", role="operator")
    state = json.loads(fake_path.read_text())
    last = state["threads"][thread_key]["messages"][-1]
    assert last["role"] == "operator"
    assert last["body"] == "Operator's verbatim reply"


def test_get_conversation_passes_operator_role_through(tmp_path, monkeypatch):
    """Brief 233: the email_get_conversation mapper passes 'operator'
    through unchanged. Customer still maps to 'user', marina still maps
    to 'assistant', operator stays as 'operator' so the frontend can
    distinguish."""
    customer = "test233-carol@example.com"
    thread_key, _ = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Marina-generated", role="marina")
    state_registry.email_append_assistant_message(
        customer, "Operator-typed", role="operator")
    detail = state_registry.email_get_conversation(thread_key)
    msgs = detail["messages"]
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "operator"
    assert msgs[2]["text"] == "Operator-typed"


def test_list_conversations_surfaces_operator_role(tmp_path, monkeypatch):
    """Brief 233: when the most recent message in a thread is from an
    operator, email_list_conversations returns last_message_role
    ='operator' (not 'assistant')."""
    customer = "test233-dan@example.com"
    thread_key, _ = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "Operator's reply", role="operator")
    rows = state_registry.email_list_conversations()
    matches = [r for r in rows if r["phone"] == f"email::{thread_key}"]
    assert len(matches) == 1
    assert matches[0]["last_message_role"] == "operator"


def test_marina_role_still_maps_to_assistant_for_legacy(tmp_path, monkeypatch):
    """Brief 233: legacy threads with role='marina' continue to map to
    'assistant' so existing data renders unchanged."""
    customer = "test233-eve@example.com"
    thread_key, _ = _seed_thread(tmp_path, monkeypatch, customer)
    state_registry.email_append_assistant_message(
        customer, "legacy marina write")  # default role
    detail = state_registry.email_get_conversation(thread_key)
    assert detail["messages"][-1]["role"] == "assistant"
