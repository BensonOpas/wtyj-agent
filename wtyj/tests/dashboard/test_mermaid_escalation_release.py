"""Mermaid dashboard handback must release the reservation, not only the UI."""

import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from agents.social import mermaid_reservation_store as reservation_store
from agents.social.webhook_server import app
from dashboard import api as dashboard_api
from shared import config_loader, state_registry


ROOT = Path(__file__).resolve().parents[3]
MERMAID_CONFIG = ROOT / "clients" / "mermaid" / "config" / "client.json"
client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_mermaid_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(MERMAID_CONFIG))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(dashboard_api, "_current_tenant_slug", lambda: "mermaid")
    monkeypatch.setattr(state_registry, "_alert_dispatcher", None)
    monkeypatch.setattr(state_registry, "_summary_dispatcher", None)


def _auth() -> dict[str, str]:
    response = client.post("/dashboard/api/login", json={"password": "testpass"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _intake() -> dict:
    return {
        "trip_date": "2026-09-12",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Release Test",
        "contact_phone": "+59990000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }


def _seed_frozen_escalation(conversation_id: str, *, mode: str = "hard") -> tuple[int, dict]:
    reservation = reservation_store.confirm_reservation(
        conversation_id,
        _intake(),
        idempotency_key=f"confirm:{conversation_id}",
    )
    reservation_store.freeze_for_human(reservation["public_id"])
    state_registry.wa_save_booking_state(
        conversation_id,
        {"mermaid_intake": {"phase": "human_takeover"}},
        {"fully_escalated": True},
        [],
    )
    escalation_id = state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Mermaid reservation review",
        "The reservation is waiting for an operator.",
        mode=mode,
    )
    state_registry.set_ai_muted(
        conversation_id, mode == "hard", "whatsapp"
    )
    return escalation_id, reservation


def _notification(escalation_id: int):
    conn = state_registry._get_conn()
    try:
        return conn.execute(
            "SELECT status, mode FROM pending_notifications WHERE id = ?",
            (escalation_id,),
        ).fetchone()
    finally:
        conn.close()


def _content_revision(escalation_id: int) -> int:
    conn = state_registry._get_conn()
    try:
        row = conn.execute(
            "SELECT content_revision FROM pending_notifications WHERE id = ?",
            (escalation_id,),
        ).fetchone()
        assert row is not None
        return int(row[0])
    finally:
        conn.close()


def _assert_released(conversation_id: str, reservation_id: str) -> None:
    assert state_registry.get_ai_muted(conversation_id) is False
    assert state_registry.get_human_takeover_at(conversation_id) is None
    assert state_registry.get_conversation_status(conversation_id) == "resolved"
    assert state_registry.get_active_escalation_mode(conversation_id) is None
    assert (
        state_registry.wa_get_booking_state(conversation_id)["flags"].get(
            "fully_escalated"
        )
        is False
    )
    assert reservation_store.get_reservation(reservation_id)["human_takeover"] is False


def test_mermaid_resolve_releases_all_freezes_and_booking_can_continue():
    conversation_id = "mermaid-resolve-release"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/resolve",
        json={"resolutionNote": "Handled.", "saveAsLearning": False},
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert tuple(_notification(escalation_id)) == ("resolved", "hard")
    _assert_released(conversation_id, reservation["public_id"])
    continued = reservation_store.transition(
        reservation["public_id"],
        "quote_ready",
        idempotency_key="continue-after-resolve",
        actor="tracy",
        reason="Operator released the review",
    )
    assert continued["state"] == "quote_ready"


def test_mermaid_handback_resolves_soft_item_and_booking_can_continue():
    conversation_id = "mermaid-handback-release"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/handback",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    assert response.json()["mode"] == "soft"
    assert tuple(_notification(escalation_id)) == ("resolved", "soft")
    _assert_released(conversation_id, reservation["public_id"])
    continued = reservation_store.transition(
        reservation["public_id"],
        "quote_ready",
        idempotency_key="continue-after-handback",
        actor="tracy",
        reason="Operator handed the conversation back",
    )
    assert continued["state"] == "quote_ready"


def test_resolving_one_of_two_active_reviews_keeps_reservation_frozen():
    conversation_id = "mermaid-two-active-reviews"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)
    relay_id = state_registry.create_pending_notification(
        "relay",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Crew question",
        "The crew still needs to answer this question.",
        mode="soft",
    )
    assert state_registry.get_active_escalation_mode(conversation_id) == "hard"

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/resolve",
        json={"resolutionNote": "Handled.", "saveAsLearning": False},
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert tuple(_notification(escalation_id)) == ("resolved", "hard")
    assert tuple(_notification(relay_id)) == ("pending", "soft")
    assert state_registry.get_active_escalation_mode(conversation_id) == "soft"
    assert state_registry.get_conversation_status(conversation_id) == "open"
    assert state_registry.get_ai_muted(conversation_id) is False
    assert (
        state_registry.wa_get_booking_state(conversation_id)["flags"].get(
            "fully_escalated"
        )
        is False
    )
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True
    with pytest.raises(
        reservation_store.MermaidReservationError, match="frozen"
    ):
        reservation_store.transition(
            reservation["public_id"],
            "quote_ready",
            idempotency_key="blocked-by-second-review",
            actor="tracy",
            reason="The remaining relay must keep this frozen",
        )


def test_confirmed_operator_reply_releases_the_last_mermaid_review():
    conversation_id = "mermaid-reply-release"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)

    result = state_registry.reply_mermaid_escalation(escalation_id)

    assert result["status"] == "replied"
    assert result["active_review"] is False
    assert tuple(_notification(escalation_id)) == ("replied", "hard")
    _assert_released(conversation_id, reservation["public_id"])


def test_confirmed_reply_keeps_another_active_mermaid_review_frozen():
    conversation_id = "mermaid-reply-one-of-two"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)
    relay_id = state_registry.create_pending_notification(
        "relay", "whatsapp", conversation_id, "Release Test", "Second review",
        "This work item still needs an operator.", mode="soft",
    )

    result = state_registry.reply_mermaid_escalation(escalation_id)

    assert result["active_review"] is True
    assert tuple(_notification(escalation_id)) == ("replied", "hard")
    assert tuple(_notification(relay_id)) == ("pending", "soft")
    assert state_registry.get_active_escalation_mode(conversation_id) == "soft"
    assert state_registry.get_ai_muted(conversation_id) is False
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_legacy_null_review_is_canonical_soft_and_order_does_not_mask_it():
    conversation_id = "mermaid-legacy-review-with-order"
    legacy_id, reservation = _seed_frozen_escalation(
        conversation_id, mode="soft"
    )
    conn = state_registry._get_conn()
    try:
        conn.execute(
            "UPDATE pending_notifications SET mode=NULL, created_at='2026-09-01' "
            "WHERE id=?", (legacy_id,),
        )
        conn.commit()
    finally:
        conn.close()
    order_id = state_registry.create_pending_notification(
        "escalation", "whatsapp", conversation_id, "Release Test",
        "New order", "An operational order item.", mode="order",
    )

    assert order_id != legacy_id
    assert state_registry.get_active_escalation_mode(conversation_id) == "soft"
    repaired = state_registry.reconcile_mermaid_escalation_freezes()
    assert repaired["active"] == 1
    assert state_registry.get_ai_muted(conversation_id) is False
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_mermaid_takeover_endpoint_atomically_freezes_soft_review():
    conversation_id = "mermaid-dashboard-takeover"
    escalation_id, reservation = _seed_frozen_escalation(
        conversation_id, mode="soft"
    )
    state_registry.release_mermaid_escalation(escalation_id)
    state_registry.reopen_mermaid_escalation(escalation_id)

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/takeover",
        json={"content_revision": _content_revision(escalation_id)},
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert tuple(_notification(escalation_id)) == ("sent", "hard")
    assert state_registry.get_ai_muted(conversation_id) is True
    assert state_registry.get_human_takeover_at(conversation_id)
    assert (
        state_registry.wa_get_booking_state(conversation_id)["flags"].get(
            "fully_escalated"
        )
        is True
    )
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_mermaid_mode_endpoint_keeps_soft_review_frozen_while_unmuting():
    conversation_id = "mermaid-dashboard-mode"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/mode",
        json={"mode": "soft"},
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert tuple(_notification(escalation_id)) == ("pending", "soft")
    assert state_registry.get_ai_muted(conversation_id) is False
    assert (
        state_registry.wa_get_booking_state(conversation_id)["flags"].get(
            "fully_escalated"
        )
        is False
    )
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


@pytest.mark.parametrize(
    ("action", "mode"),
    [
        ("resolve", "hard"),
        ("takeover", "soft"),
        ("handback", "hard"),
        ("mode", "hard"),
        ("delete", "hard"),
    ],
)
def test_stale_dashboard_action_cannot_mutate_newer_guest_revision(action, mode):
    conversation_id = f"mermaid-stale-{action}"
    escalation_id, reservation = _seed_frozen_escalation(
        conversation_id, mode=mode
    )
    updated_id = state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Updated Mermaid reservation review",
        "A newer guest message now needs the operator.",
        mode=mode,
        preserve_hard_mode=(mode == "hard"),
    )
    assert updated_id == escalation_id
    assert _content_revision(escalation_id) == 2

    path = f"/dashboard/api/escalations/{escalation_id}"
    if action == "delete":
        response = client.request(
            "DELETE",
            path,
            json={"content_revision": 1},
            headers=_auth(),
        )
    elif action == "mode":
        response = client.post(
            path + "/mode",
            json={"mode": "soft", "content_revision": 1},
            headers=_auth(),
        )
    else:
        response = client.post(
            path + f"/{action}",
            json={"content_revision": 1},
            headers=_auth(),
        )

    assert response.status_code == 409, response.text
    assert "case changed" in response.json()["detail"].lower()
    assert tuple(_notification(escalation_id)) == ("pending", mode)
    assert _content_revision(escalation_id) == 2
    assert state_registry.get_ai_muted(conversation_id) is (mode == "hard")
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_stale_unresolve_cannot_reopen_a_newer_resolved_revision():
    conversation_id = "mermaid-stale-unresolve"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)
    released = state_registry.release_mermaid_escalation(
        escalation_id, expected_content_revision=1
    )
    assert released["content_revision"] == 2
    _assert_released(conversation_id, reservation["public_id"])

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/unresolve",
        json={"content_revision": 1},
        headers=_auth(),
    )

    assert response.status_code == 409, response.text
    assert tuple(_notification(escalation_id)) == ("resolved", "hard")
    assert _content_revision(escalation_id) == 2
    _assert_released(conversation_id, reservation["public_id"])


def test_legacy_missing_revision_defaults_to_one_and_fails_closed_after_reuse():
    conversation_id = "mermaid-legacy-revision-default"
    escalation_id, reservation = _seed_frozen_escalation(
        conversation_id, mode="soft"
    )
    state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Updated question",
        "New guest content makes a revision-less dashboard stale.",
        mode="soft",
    )

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/takeover",
        headers=_auth(),
    )

    assert response.status_code == 409, response.text
    assert tuple(_notification(escalation_id)) == ("pending", "soft")
    assert _content_revision(escalation_id) == 2
    assert state_registry.get_ai_muted(conversation_id) is False
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_send_and_resolve_only_closes_the_revision_that_was_delivered():
    conversation_id = "mermaid-send-resolve-revision"
    escalation_id, reservation = _seed_frozen_escalation(
        conversation_id, mode="soft"
    )
    delivered_revision = _content_revision(escalation_id)
    # Models a guest re-escalation that lands while the provider send is in
    # flight. The delivery finishes for revision 1, while revision 2 remains
    # the active work item.
    state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Release Test",
        "New question during delivery",
        "The guest added a different question before Send & Resolve finished.",
        mode="soft",
    )

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/resolve",
        json={
            "resolutionNote": "Answer sent for the earlier question.",
            "content_revision": delivered_revision,
        },
        headers=_auth(),
    )

    assert response.status_code == 409, response.text
    assert tuple(_notification(escalation_id)) == ("pending", "soft")
    assert _content_revision(escalation_id) == 2
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_overlapping_summary_generation_cannot_overwrite_newer_revision():
    conversation_id = "mermaid-overlapping-summary"
    escalation_id = state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Initial question",
        "Initial body",
        mode="soft",
    )
    conn = state_registry._get_conn()
    try:
        conn.execute(
            "UPDATE pending_notifications SET escalation_summary=? WHERE id=?",
            (
                json.dumps({"latestCustomerMessage": "Old guest message"}),
                escalation_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    entered = threading.Event()
    release = threading.Event()
    errors = []

    def slow_summary(*_args):
        entered.set()
        assert release.wait(5)
        return {"latestCustomerMessage": "Superseded guest message"}

    state_registry._summary_dispatcher = slow_summary

    def update_second_revision():
        try:
            state_registry.create_pending_notification(
                "escalation",
                "whatsapp",
                conversation_id,
                "Release Test",
                "Second question",
                "Second body",
                mode="soft",
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    worker = threading.Thread(target=update_second_revision)
    worker.start()
    assert entered.wait(5)

    conn = state_registry._get_conn()
    try:
        while_second_is_generating = conn.execute(
            "SELECT body,content_revision,escalation_summary "
            "FROM pending_notifications WHERE id=?",
            (escalation_id,),
        ).fetchone()
    finally:
        conn.close()
    assert tuple(while_second_is_generating) == ("Second body", 2, None)

    state_registry._summary_dispatcher = lambda *_args: {
        "latestCustomerMessage": "Newest guest message"
    }
    newest_id = state_registry.create_pending_notification(
        "escalation",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Newest question",
        "Newest body",
        mode="soft",
    )
    assert newest_id == escalation_id
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []

    row = next(
        item
        for item in state_registry.get_all_escalations()
        if item["id"] == escalation_id
    )
    assert row["body"] == "Newest body"
    assert row["content_revision"] == 3
    assert row["escalationSummary"] == {
        "latestCustomerMessage": "Newest guest message"
    }


def test_startup_reconciliation_releases_orphaned_freezes():
    conversation_id = "mermaid-orphaned-freeze"
    reservation = reservation_store.confirm_reservation(
        conversation_id,
        _intake(),
        idempotency_key="confirm-orphaned-freeze",
    )
    reservation_store.freeze_for_human(reservation["public_id"])
    state_registry.wa_save_booking_state(
        conversation_id,
        {"mermaid_intake": {"phase": "human_takeover"}},
        {"fully_escalated": True},
        [],
    )
    state_registry.set_ai_muted(conversation_id, True, "whatsapp")

    result = state_registry.reconcile_mermaid_escalation_freezes()

    assert result == {"conversations": 1, "active": 0, "hard": 0}
    _assert_released(conversation_id, reservation["public_id"])


def test_startup_reconciliation_restores_missing_soft_review_freeze():
    conversation_id = "mermaid-missing-freeze"
    reservation = reservation_store.confirm_reservation(
        conversation_id,
        _intake(),
        idempotency_key="confirm-missing-freeze",
    )
    state_registry.create_pending_notification(
        "relay",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Crew question",
        "Crew response is pending.",
        mode="soft",
    )

    result = state_registry.reconcile_mermaid_escalation_freezes()

    assert result == {"conversations": 1, "active": 1, "hard": 0}
    assert state_registry.get_ai_muted(conversation_id) is False
    assert state_registry.get_conversation_status(conversation_id) == "open"
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_mermaid_delete_releases_single_review_atomically():
    conversation_id = "mermaid-delete-single"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)

    response = client.delete(
        f"/dashboard/api/escalations/{escalation_id}", headers=_auth()
    )

    assert response.status_code == 200, response.text
    assert _notification(escalation_id) is None
    _assert_released(conversation_id, reservation["public_id"])


def test_mermaid_delete_keeps_freeze_for_second_active_review():
    conversation_id = "mermaid-delete-multi"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)
    relay_id = state_registry.create_pending_notification(
        "relay",
        "whatsapp",
        conversation_id,
        "Release Test",
        "Crew question",
        "Crew response is pending.",
        mode="soft",
    )

    response = client.delete(
        f"/dashboard/api/escalations/{escalation_id}", headers=_auth()
    )

    assert response.status_code == 200, response.text
    assert _notification(escalation_id) is None
    assert tuple(_notification(relay_id)) == ("pending", "soft")
    assert state_registry.get_active_escalation_mode(conversation_id) == "soft"
    assert state_registry.get_ai_muted(conversation_id) is False
    assert reservation_store.get_reservation(
        reservation["public_id"]
    )["human_takeover"] is True


def test_mermaid_release_rolls_back_every_state_if_reservation_unfreeze_fails():
    conversation_id = "mermaid-release-rollback"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)
    conn = state_registry._get_conn()
    try:
        conn.execute(
            "CREATE TRIGGER fail_mermaid_release "
            "BEFORE UPDATE OF human_takeover ON mermaid_reservations "
            "WHEN NEW.human_takeover = 0 "
            "BEGIN SELECT RAISE(ABORT, 'forced release failure'); END"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="forced release failure"):
        state_registry.release_mermaid_escalation(escalation_id)

    assert tuple(_notification(escalation_id)) == ("pending", "hard")
    assert state_registry.get_ai_muted(conversation_id) is True
    assert state_registry.get_conversation_status(conversation_id) == "open"
    assert (
        state_registry.wa_get_booking_state(conversation_id)["flags"].get(
            "fully_escalated"
        )
        is True
    )
    assert reservation_store.get_reservation(reservation["public_id"])["human_takeover"] is True


def test_mermaid_unresolve_refreezes_hard_review_atomically():
    conversation_id = "mermaid-unresolve-refreeze"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)
    state_registry.release_mermaid_escalation(escalation_id)
    _assert_released(conversation_id, reservation["public_id"])

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/unresolve",
        json={"content_revision": _content_revision(escalation_id)},
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "sent"
    assert response.json()["mode"] == "hard"
    assert tuple(_notification(escalation_id)) == ("sent", "hard")
    assert state_registry.get_ai_muted(conversation_id) is True
    assert state_registry.get_human_takeover_at(conversation_id)
    assert state_registry.get_conversation_status(conversation_id) == "open"
    assert state_registry.get_active_escalation_mode(conversation_id) == "hard"
    assert (
        state_registry.wa_get_booking_state(conversation_id)["flags"].get(
            "fully_escalated"
        )
        is True
    )
    assert reservation_store.get_reservation(reservation["public_id"])["human_takeover"] is True


def test_non_mermaid_handback_keeps_existing_generic_semantics(monkeypatch):
    conversation_id = "generic-handback-preserved"
    escalation_id, reservation = _seed_frozen_escalation(conversation_id)
    monkeypatch.setattr(dashboard_api, "_current_tenant_slug", lambda: "unboks")

    response = client.post(
        f"/dashboard/api/escalations/{escalation_id}/handback",
        headers=_auth(),
    )

    assert response.status_code == 200, response.text
    assert tuple(_notification(escalation_id)) == ("pending", "soft")
    assert state_registry.get_ai_muted(conversation_id) is False
    assert state_registry.get_active_escalation_mode(conversation_id) == "soft"
    assert (
        state_registry.wa_get_booking_state(conversation_id)["flags"].get(
            "fully_escalated"
        )
        is True
    )
    assert reservation_store.get_reservation(reservation["public_id"])["human_takeover"] is True


def test_non_mermaid_takeover_and_handback_commit_mode_with_mute(monkeypatch):
    conversation_id = "generic-atomic-takeover-handback"
    escalation_id, reservation = _seed_frozen_escalation(
        conversation_id, mode="soft"
    )
    monkeypatch.setattr(dashboard_api, "_current_tenant_slug", lambda: "unboks")
    monkeypatch.setattr(
        state_registry,
        "set_ai_muted",
        lambda *_args, **_kwargs: pytest.fail(
            "takeover state must not use a second database transaction"
        ),
    )

    takeover = client.post(
        f"/dashboard/api/escalations/{escalation_id}/takeover",
        json={"content_revision": 1},
        headers=_auth(),
    )
    assert takeover.status_code == 200, takeover.text
    assert tuple(_notification(escalation_id)) == ("pending", "hard")
    assert _content_revision(escalation_id) == 2
    assert state_registry.get_ai_muted(conversation_id) is True

    handback = client.post(
        f"/dashboard/api/escalations/{escalation_id}/handback",
        json={"content_revision": 2},
        headers=_auth(),
    )
    assert handback.status_code == 200, handback.text
    assert tuple(_notification(escalation_id)) == ("pending", "soft")
    assert _content_revision(escalation_id) == 3
    assert state_registry.get_ai_muted(conversation_id) is False
    assert reservation_store.get_reservation(reservation["public_id"])["human_takeover"] is True
