"""Issue 329: Mermaid demo availability and reservation aggregate."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agents.social import mermaid_reservation_store as store
from shared import config_loader, state_registry


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "clients" / "mermaid" / "config" / "client.json"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(CONFIG))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))


def intake(**changes):
    value = {
        "trip_date": "2026-09-05", "adults": 2, "children": 1, "infants": 1,
        "customer_name": "Ana Silva", "contact_phone": "+12025550123", "pickup_preference": "pier", "language": "en",
        "phase": "summary_confirmed",
    }
    value.update(changes)
    return value


def test_confirmation_creates_immutable_demo_assumed_snapshot():
    reservation = store.confirm_reservation("guest", intake(), idempotency_key="confirm-1")
    assert reservation["state"] == "demo_availability_approved"
    assert reservation["availability_source"] == "demo_assumed"
    assert reservation["booking_code"].startswith("MER-DEMO-")
    assert reservation["monetary_snapshot"]["total"] == 375
    assert reservation["monetary_snapshot"]["currency"] == "USD"
    assert reservation["catalog_version"] == "mermaid-demo-v5-2026-09-03"
    assert "available" not in reservation["intake"]
    event = store.events(reservation["public_id"])[0]
    assert event["to_state"] == "demo_availability_approved"
    assert "no inventory provider called" in event["reason"]


@pytest.mark.parametrize("workers", [2, 6, 12])
def test_confirmation_replay_and_concurrency_create_one_reservation(workers):
    def confirm(index):
        return store.confirm_reservation("guest", intake(), idempotency_key=f"confirm-{index}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(confirm, range(workers)))
    assert len({result["public_id"] for result in results}) == 1
    assert len(store.list_reservations()) == 1


def test_changed_summary_creates_new_version_without_mutating_first():
    first = store.confirm_reservation("guest", intake(), idempotency_key="one")
    second = store.confirm_reservation("guest", intake(adults=3), idempotency_key="two")
    assert first["public_id"] != second["public_id"]
    assert first["monetary_snapshot"]["total"] == 375
    assert second["monetary_snapshot"]["total"] == 525


def test_transition_is_ordered_and_replay_safe():
    reservation = store.confirm_reservation("guest", intake(), idempotency_key="one")
    quote = store.transition(
        reservation["public_id"], "quote_ready", idempotency_key="quote-one",
        actor="system", reason="quote rendered", updates={"quote_public_id": "quote_1"},
    )
    replay = store.transition(
        reservation["public_id"], "quote_ready", idempotency_key="quote-one",
        actor="system", reason="quote rendered", updates={"quote_public_id": "quote_1"},
    )
    assert quote == replay
    assert quote["revision"] == 2
    with pytest.raises(store.MermaidReservationError, match="invalid transition"):
        store.transition(
            reservation["public_id"], "booked", idempotency_key="skip",
            actor="system", reason="invalid skip",
        )


def test_cancel_before_payment_is_idempotent():
    reservation = store.confirm_reservation("guest", intake(), idempotency_key="one")
    cancelled = store.cancel(reservation["public_id"], idempotency_key="cancel-one")
    replay = store.cancel(reservation["public_id"], idempotency_key="cancel-two")
    assert cancelled["state"] == replay["state"] == "cancelled"


def test_human_takeover_freezes_automated_transition():
    reservation = store.confirm_reservation("guest", intake(), idempotency_key="one")
    store.freeze_for_human(reservation["public_id"])
    with pytest.raises(store.MermaidReservationError, match="frozen"):
        store.transition(
            reservation["public_id"], "quote_ready", idempotency_key="quote",
            actor="system", reason="should not happen",
        )


def test_tenant_isolation_is_hard_coded():
    reservation = store.confirm_reservation("guest", intake(), idempotency_key="one")
    assert reservation["tenant_slug"] == "mermaid"
    conn = store._conn()
    try:
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO mermaid_reservations (public_id, tenant_slug, conversation_id, summary_version, "
                "customer_name, language, intake_json, catalog_version, monetary_snapshot_json, state, "
                "availability_source, booking_code, created_at, updated_at) VALUES "
                "('x', 'ali-car-rental', 'c', 's', 'n', 'en', '{}', 'v', '{}', 'booked', "
                "'demo_assumed', 'MER-DEMO-X', 'now', 'now')"
            )
    finally:
        conn.close()
