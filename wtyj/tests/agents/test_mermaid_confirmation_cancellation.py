"""Issue 342 A3: one guest confirmation and atomic unpaid cancellation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading
from unittest.mock import Mock

import pytest

from agents.marina import marina_agent
from agents.social import mermaid_demo_payment as checkout
from agents.social import mermaid_reservation_store as store
from agents.social import mermaid_reservation_workflow as workflow
from shared import config_loader, state_registry


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    config = Path(__file__).resolve().parents[3] / "clients/mermaid/config/client.json"
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(state_registry, "_alert_dispatcher", None)
    monkeypatch.setattr(state_registry, "_summary_dispatcher", None)
    monkeypatch.setenv("MERMAID_DOCUMENT_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("MERMAID_DEMO_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://demo.example")


def intake(locale="en"):
    return {
        "trip_date": "2026-09-12", "adults": 4, "children": 1, "infants": 1,
        "customer_name": "Mila Tromp", "contact_phone": "+12025550025",
        "pickup_preference": "pickup_requested", "pickup_location": "Hotel Alpha",
        "language": locale, "phase": "summary_confirmed",
    }


def understood(action="details", **kwargs):
    return dict(language="en", mermaid_action=action, fields={}, reply="Model answer",
                has_open_question=False, guest_question_excerpt="", requires_human=False) | kwargs


def pending(locale="en"):
    reservation = store.confirm_reservation("guest", intake(locale), idempotency_key="confirm")
    for state in ("quote_ready", "demo_payment_pending"):
        reservation = store.transition(reservation["public_id"], state, idempotency_key=state,
                                       actor="system", reason="test")
    state_registry.wa_save_booking_state("guest", {"mermaid_intake": intake(locale)}, {})
    return reservation


def counts(reservation_id):
    conn = store._conn()
    try:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE reservation_public_id=?",
                                  (reservation_id,)).fetchone()[0]
                     for table in ("mermaid_demo_payments", "mermaid_checkout_links"))
    finally:
        conn.close()


@pytest.mark.parametrize("excerpt", ["", "Would you like to go ahead with these details?"])
def test_tracys_own_question_does_not_add_a_confirmation_turn(monkeypatch, excerpt):
    facts = {key: value for key, value in intake().items() if key not in {"phase", "language"}}
    model = Mock(return_value=understood("question", fields=facts, has_open_question=True,
                                       guest_question_excerpt=excerpt, reply="Would you like to go ahead with these details?"))
    monkeypatch.setattr(marina_agent, "process_message", model)
    result = workflow.handle_demo_message({"from": "guest", "text": "These are my trip details.", "message_id": "facts"}, True, use_model=True)
    assert state_registry.wa_get_booking_state("guest")["fields"]["mermaid_intake"]["phase"] == "awaiting_summary_confirmation"
    assert "800" in result["text"] and "Mila Tromp" in result["text"]
    model.return_value = understood("confirm_summary")
    message = {"from": "guest", "text": "Yes, all those details are correct.", "message_id": "yes"}
    quote = workflow.handle_demo_message(message, True, use_model=True)
    replay = workflow.handle_demo_message(message, True, use_model=True)
    assert quote["media"] == replay["media"] and quote["media"] is not None
    assert quote["mermaid_delivery_commit"] == replay["mermaid_delivery_commit"]
    # A second unambiguous YES is a status turn, not another reservation.
    again = workflow.handle_demo_message(message | {"message_id": "another-yes"}, True, use_model=True)
    assert again["media"] is None
    assert len(store.list_reservations()) == 1
    assert store.latest_for_conversation("guest")["state"] == "demo_payment_pending"
    assert model.call_count == 3


def test_guest_question_even_in_confirmation_action_prevents_booking(monkeypatch):
    fields = intake() | {"phase": "awaiting_summary_confirmation"}
    state_registry.wa_save_booking_state("guest", {"mermaid_intake": fields}, {})
    model = Mock(return_value=understood("confirm_summary", guest_question_excerpt="Is lunch included?",
                                       has_open_question=False, reply="Lunch is included."))
    monkeypatch.setattr(marina_agent, "process_message", model)
    result = workflow.handle_demo_message({"from": "guest", "text": "Yes. Is lunch included?", "message_id": "question"}, True, use_model=True)
    assert result["text"] == "Lunch is included."
    assert store.latest_for_conversation("guest") is None
    assert state_registry.wa_get_booking_state("guest")["fields"]["mermaid_intake"] == fields
    model.return_value = understood("confirm_summary")
    assert workflow.handle_demo_message({"from": "guest", "text": "Yes", "message_id": "yes"}, True, use_model=True)["media"]


@pytest.mark.parametrize("locale", workflow.SUPPORTED_LOCALES)
def test_unpaid_cancel_overrides_generic_model_review_and_revokes_all_links(monkeypatch, locale):
    reservation = pending(locale)
    tokens = [checkout.build_payment_url("https://demo.example", reservation["public_id"], "test-secret").rsplit("/", 1)[1] for _ in range(2)]
    monkeypatch.setattr(marina_agent, "process_message", lambda **_: understood("cancel", language=locale, requires_human=True, reply="Cancellation after payment needs staff."))
    message = {"from": "guest", "text": "Cancel my unpaid quote", "message_id": "cancel"}
    result = workflow.handle_demo_message(message, True, use_model=True)
    assert result["text"] == workflow.COPY[locale]["cancelled"]
    assert store.get_reservation(reservation["public_id"])["state"] == "cancelled"
    assert counts(reservation["public_id"]) == (0, 0)
    assert state_registry.get_active_escalation_mode("guest") is None
    assert all(checkout.short_checkout_page(token).status_code == 404 for token in tokens)
    assert workflow.handle_demo_message(message, True, use_model=True)["text"] == result["text"]
    assert workflow.handle_demo_message(message | {"message_id": "cancel-again"}, True, use_model=True)["text"] == result["text"]
    assert len([event for event in store.events(reservation["public_id"]) if event["to_state"] == "cancelled"]) == 1


def test_cancellation_and_link_revocation_roll_back_together():
    reservation = pending()
    checkout.build_payment_url("https://demo.example", reservation["public_id"], "test-secret")
    conn = store._conn()
    try:
        conn.execute("CREATE TRIGGER fail_revoke BEFORE DELETE ON mermaid_checkout_links BEGIN SELECT RAISE(ABORT, 'injected revoke failure'); END")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(sqlite3.IntegrityError, match="injected revoke failure"):
        store.cancel(reservation["public_id"], idempotency_key="cancel")
    assert store.get_reservation(reservation["public_id"])["state"] == "demo_payment_pending"
    assert counts(reservation["public_id"]) == (0, 1)
    assert all(event["to_state"] != "cancelled" for event in store.events(reservation["public_id"]))


def ordered_writer_race(monkeypatch, first, operations):
    real_conn = store._conn
    ready = threading.Barrier(2)
    acquired, attempted, release = threading.Event(), threading.Event(), threading.Event()

    class HeldConnection:
        def __init__(self, conn, operation):
            self.conn, self.operation = conn, operation

        def execute(self, sql, *args):
            if sql == "BEGIN IMMEDIATE":
                if self.operation != first:
                    assert acquired.wait(5)
                    attempted.set()
                result = self.conn.execute(sql, *args)
                if self.operation == first:
                    acquired.set()
                    assert release.wait(5)
                return result
            return self.conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def close(self):
            pass

    connections = threading.local()
    monkeypatch.setattr(store, "_conn", lambda: connections.conn)
    real_state_conn = state_registry._get_conn
    monkeypatch.setattr(state_registry, "_get_conn", lambda: connections.conn)

    def run(operation):
        connections.conn = HeldConnection(real_conn(), operation)
        ready.wait(timeout=5)
        try:
            return operations[operation](connections.conn)
        except store.MermaidReservationError as error:
            return error
        finally:
            connections.conn.conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {operation: pool.submit(run, operation) for operation in operations}
        try:
            assert attempted.wait(5)
        finally:
            release.set()
        results = {operation: future.result(timeout=5) for operation, future in futures.items()}
    monkeypatch.setattr(store, "_conn", real_conn)
    monkeypatch.setattr(state_registry, "_get_conn", real_state_conn)
    return results


@pytest.mark.parametrize("first", ["cancel", "payment"])
def test_real_payment_cancellation_race_has_one_authoritative_winner(monkeypatch, first):
    reservation = pending()
    checkout.build_payment_url("https://demo.example", reservation["public_id"], "test-secret")
    results = ordered_writer_race(monkeypatch, first, {
        "cancel": lambda _: store.cancel(reservation["public_id"], idempotency_key="cancel"),
        "payment": lambda _: store.complete_demo_payment(reservation["public_id"], payment_reference="PAY-DEMO-RACE", idempotency_key="pay"),
    })
    cancelled, paid = results["cancel"], results["payment"]
    if first == "cancel":
        assert cancelled["state"] == "cancelled"
        assert isinstance(paid, store.MermaidReservationError)
        assert counts(reservation["public_id"]) == (0, 0)
    else:
        assert isinstance(cancelled, store.MermaidCancellationReviewRequired)
        assert paid[0]["state"] == "booked"
        assert counts(reservation["public_id"])[0] == 1
        assert not any(event["to_state"] == "cancelled" for event in store.events(reservation["public_id"]))


@pytest.mark.parametrize("first", ["cancel", "takeover"])
def test_operator_takeover_and_cancellation_obey_transaction_order(monkeypatch, first):
    reservation = pending()
    def takeover(conn):
        conn.execute("BEGIN IMMEDIATE")
        state_registry.set_ai_muted("guest", True)
    results = ordered_writer_race(monkeypatch, first, {
        "cancel": lambda _: store.cancel(reservation["public_id"], idempotency_key="cancel"),
        "takeover": takeover,
    })
    assert state_registry.get_ai_muted("guest")
    if first == "takeover":
        assert isinstance(results["cancel"], store.MermaidCancellationReviewRequired)
        assert store.get_reservation(reservation["public_id"])["state"] == "demo_payment_pending"
    else:
        assert results["cancel"]["state"] == "cancelled"
    assert counts(reservation["public_id"])[0] == 0


@pytest.mark.parametrize("review", ["mute", "soft", "hard"])
def test_operator_review_after_handler_check_is_rechecked_atomically(monkeypatch, review):
    reservation = pending()
    real_cancel = store.cancel
    def operator_wins(*args, **kwargs):
        if review == "mute":
            state_registry.set_ai_muted("guest", True)
        else:
            state_registry.create_pending_notification("escalation", "whatsapp", "guest", "Guest", "review", "review", mode=review)
        return real_cancel(*args, **kwargs)
    monkeypatch.setattr(store, "cancel", operator_wins)
    monkeypatch.setattr(marina_agent, "process_message", lambda **_: understood("cancel"))
    result = workflow.handle_demo_message({"from": "guest", "text": "Cancel", "message_id": "cancel"}, True, use_model=True)
    assert result["text"] != workflow.COPY["en"]["cancelled"]
    current = store.get_reservation(reservation["public_id"])
    assert current["state"] == "demo_payment_pending" and current["human_takeover"]
    assert state_registry.get_active_escalation_mode("guest") == ("hard" if review == "hard" else "soft")
    assert state_registry.get_ai_muted("guest") is (review == "mute")


def test_payment_winning_after_model_snapshot_returns_review_not_cancelled(monkeypatch):
    reservation = pending()
    def model(**_):
        store.complete_demo_payment(reservation["public_id"], payment_reference="PAY-DEMO-WINNER", idempotency_key="pay")
        return understood("cancel")
    monkeypatch.setattr(marina_agent, "process_message", model)
    result = workflow.handle_demo_message({"from": "guest", "text": "Cancel", "message_id": "cancel"}, True, use_model=True)
    assert result["text"] != workflow.COPY["en"]["cancelled"]
    assert store.get_reservation(reservation["public_id"])["state"] == "booked"
    assert store.get_reservation(reservation["public_id"])["human_takeover"]
    assert state_registry.get_active_escalation_mode("guest") == "soft"
    assert state_registry.get_ai_muted("guest") is False
    assert state_registry.wa_get_booking_state("guest")["fields"]["mermaid_intake"]["phase"] == "human_takeover"


def test_cancelled_signed_checkout_is_unavailable(monkeypatch):
    reservation = pending()
    monkeypatch.setattr(checkout.time, "time", lambda: 1000)
    signature = checkout.sign_payment(reservation["public_id"], 4600, "test-secret")
    store.cancel(reservation["public_id"], idempotency_key="cancel")
    assert checkout.checkout_page(reservation["public_id"], 4600, signature).status_code == 404
    assert checkout.complete_checkout(reservation["public_id"], 4600, signature, "success").status_code == 404
    assert checkout.complete_checkout(reservation["public_id"], 4600, signature, "cancel").status_code == 404


def test_signed_callback_cancellation_after_initial_read_returns_unavailable(monkeypatch):
    reservation = pending()
    monkeypatch.setattr(checkout.time, "time", lambda: 1000)
    signature = checkout.sign_payment(reservation["public_id"], 4600, "test-secret")
    real_payment = store.complete_demo_payment
    def cancellation_wins(*args, **kwargs):
        store.cancel(reservation["public_id"], idempotency_key="cancel")
        return real_payment(*args, **kwargs)
    monkeypatch.setattr(store, "complete_demo_payment", cancellation_wins)
    assert checkout.complete_checkout(reservation["public_id"], 4600, signature, "success").status_code == 404
    assert counts(reservation["public_id"])[0] == 0


def test_closing_paid_checkout_does_not_claim_unpaid_or_cancelled(monkeypatch):
    reservation = pending()
    store.complete_demo_payment(reservation["public_id"], payment_reference="PAY-DEMO-PAID", idempotency_key="pay")
    monkeypatch.setattr(checkout.time, "time", lambda: 1000)
    signature = checkout.sign_payment(reservation["public_id"], 4600, "test-secret")
    response = checkout.complete_checkout(reservation["public_id"], 4600, signature, "cancel")
    assert "already paid" in response.body.decode()
    assert "No payment was recorded" not in response.body.decode()
    assert store.get_reservation(reservation["public_id"])["state"] == "booked"


@pytest.mark.parametrize("mode", ["soft", "hard", "frozen"])
def test_cancel_keeps_existing_review_or_operator_takeover(monkeypatch, mode):
    reservation = pending()
    if mode == "frozen":
        store.freeze_for_human(reservation["public_id"])
    else:
        state_registry.create_pending_notification("escalation", "whatsapp", "guest", "Guest", "review", "review", mode=mode)
    if mode == "hard":
        state_registry.set_ai_muted("guest", True)
    monkeypatch.setattr(marina_agent, "process_message", lambda **_: understood("cancel", requires_human=True))
    result = workflow.handle_demo_message({"from": "guest", "text": "Cancel", "message_id": "cancel"}, True, use_model=True)
    assert result["text"] != workflow.COPY["en"]["cancelled"]
    assert store.get_reservation(reservation["public_id"])["state"] == "demo_payment_pending"
    assert store.get_reservation(reservation["public_id"])["human_takeover"]
    if mode == "hard":
        assert state_registry.get_active_escalation_mode("guest") == "hard"
        assert state_registry.get_ai_muted("guest")


def test_stale_confirmation_cannot_reopen_cancelled_quote(monkeypatch):
    reservation = pending()
    store.cancel(reservation["public_id"], idempotency_key="cancel")
    monkeypatch.setattr(marina_agent, "process_message", lambda **_: understood("confirm_summary"))
    for message_id in ("yes", "another-yes"):
        result = workflow.handle_demo_message({"from": "guest", "text": "Yes", "message_id": message_id}, True, use_model=True)
        assert result["text"] == workflow.COPY["en"]["cancelled"]
        assert result["media"] is None
    assert store.get_reservation(reservation["public_id"])["state"] == "cancelled"
    assert len(store.list_reservations()) == 1


def test_token_mint_cannot_publish_a_token_after_cancellation(monkeypatch):
    reservation = pending()
    real_conn = store._conn
    checked, attempted, cancelled, release = (threading.Event() for _ in range(4))

    class MintConnection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            cursor = self.conn.execute(sql, *args)
            if sql.startswith("SELECT public_id FROM mermaid_reservations"):
                row = cursor.fetchone()
                checked.set()
                assert release.wait(5)
                return Mock(fetchone=lambda: row)
            return cursor

        def __enter__(self):
            self.conn.__enter__()
            return self

        def __exit__(self, *args):
            return self.conn.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.conn, name)

    def connection():
        conn = real_conn()
        return MintConnection(conn) if threading.current_thread().name == "mint" else conn
    monkeypatch.setattr(store, "_conn", connection)
    errors = []
    def mint():
        try:
            checkout.build_payment_url("https://demo.example", reservation["public_id"], "test-secret")
        except Exception as error:
            errors.append(error)
    def cancel():
        attempted.set()
        try:
            store.cancel(reservation["public_id"], idempotency_key="cancel")
            cancelled.set()
        except Exception as error:
            errors.append(error)
    mint_thread, cancel_thread = threading.Thread(target=mint, name="mint"), threading.Thread(target=cancel, name="cancel")
    mint_thread.start()
    try:
        assert checked.wait(5)
        cancel_thread.start()
        assert attempted.wait(5)
        # The old mint path reads outside a write transaction: cancellation
        # completes here and it subsequently inserts a token for cancelled state.
        cancelled.wait(0.25)
    finally:
        release.set()
        mint_thread.join(5)
        cancel_thread.join(5)
    assert not mint_thread.is_alive() and not cancel_thread.is_alive()
    assert errors == []
    assert cancelled.is_set()
    assert counts(reservation["public_id"]) == (0, 0)
