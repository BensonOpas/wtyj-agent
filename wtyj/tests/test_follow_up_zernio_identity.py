"""Regression tests for Consulta Despertares follow-up identities."""

import asyncio
import json

import pytest

from fastapi import Response

from agents.social.channels.whatsapp_zernio import WhatsAppZernioChannel
from agents.social import whatsapp_client
from dashboard import api
from shared import tenant_guard


def test_whatsapp_zernio_adapter_preserves_participant_phone():
    result = WhatsAppZernioChannel.from_zernio({
        "conversation_id": "0123456789abcdef01234567",
        "sender_id": "+34612345678",
        "sender_name": "Lucía Carrillo",
        "message_id": "message-1",
        "channel": "whatsapp",
        "account_id": "account-1",
        "text": "Hola",
    })

    assert result["from"] == "0123456789abcdef01234567"
    assert result["_zernio_sender_id"] == "+34612345678"


def test_zernio_contact_resolver_reads_participant_metadata(monkeypatch):
    conversation_id = "0123456789abcdef01234567"
    payload = {
        "data": [{
            "id": conversation_id,
            "accountId": "account-1",
            "participantId": "+34612345678",
            "participantName": "Lucía Carrillo",
        }],
        "pagination": {"hasMore": False, "nextCursor": ""},
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(
        whatsapp_client,
        "_candidate_zernio_account_ids",
        lambda _publisher: ["account-1"],
    )
    monkeypatch.setattr(tenant_guard, "is_account_allowed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(whatsapp_client.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    whatsapp_client._zernio_contact_cache.clear()
    whatsapp_client._zernio_contact_attempted_at.clear()

    result = whatsapp_client.resolve_zernio_conversation_contacts([conversation_id])

    assert result[conversation_id]["phone"] == "+34612345678"
    assert result[conversation_id]["name"] == "Lucía Carrillo"


@pytest.mark.parametrize("decisions", [[False], [True, False]])
def test_zernio_contact_cache_reassignment_invalidates_private_metadata(
    monkeypatch, decisions,
):
    conversation_id = "a" * 24
    monkeypatch.setattr(whatsapp_client, "_zernio_contact_cache", {
        conversation_id: {"account_id": "former-account", "phone": "+15551234567"},
    })
    monkeypatch.setattr(whatsapp_client, "_zernio_contact_attempted_at", {})
    states = iter(decisions)
    monkeypatch.setattr(
        tenant_guard, "is_account_allowed", lambda *_a, **_k: next(states, False),
    )
    monkeypatch.setattr(whatsapp_client, "_candidate_zernio_account_ids", lambda _: [])

    assert whatsapp_client.resolve_zernio_conversation_contacts([conversation_id]) == {}
    assert conversation_id not in whatsapp_client._zernio_contact_cache


@pytest.mark.parametrize("row_account_id", [None, "foreign-account", " mermaid-account "])
def test_zernio_contact_rows_require_exact_account_identity(monkeypatch, row_account_id):
    conversation_id = "a" * 24
    payload = {"data": [{
        "id": conversation_id, "participantId": "+15551234567",
        **({"accountId": row_account_id} if row_account_id is not None else {}),
    }]}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(whatsapp_client, "_zernio_contact_cache", {})
    monkeypatch.setattr(whatsapp_client, "_zernio_contact_attempted_at", {})
    monkeypatch.setattr(
        whatsapp_client, "_candidate_zernio_account_ids", lambda _: ["mermaid-account"],
    )
    monkeypatch.setattr(tenant_guard, "is_account_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(whatsapp_client.urllib.request, "urlopen", lambda *_a, **_k: Response())

    assert whatsapp_client.resolve_zernio_conversation_contacts([conversation_id]) == {}
    assert whatsapp_client._zernio_contact_cache == {}


def test_zernio_contact_pagination_rechecks_ownership_before_next_get(monkeypatch):
    first, second = "a" * 24, "b" * 24
    payload = {"data": [{
        "id": first, "accountId": "mermaid-account", "participantId": "+15551234567",
    }], "pagination": {"hasMore": True, "nextCursor": "next-page"}}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setenv("LATE_API_KEY", "test-key")
    monkeypatch.setattr(whatsapp_client, "_zernio_contact_cache", {})
    monkeypatch.setattr(whatsapp_client, "_zernio_contact_attempted_at", {})
    monkeypatch.setattr(
        whatsapp_client, "_candidate_zernio_account_ids", lambda _: ["mermaid-account"],
    )
    # Candidate, page preflight, response, first row; then ownership is revoked.
    decisions = iter([True, True, True, True])
    monkeypatch.setattr(
        tenant_guard, "is_account_allowed", lambda *_a, **_k: next(decisions, False),
    )
    gets = []
    monkeypatch.setattr(
        whatsapp_client.urllib.request, "urlopen",
        lambda *_a, **_k: gets.append(True) or Response(),
    )

    assert whatsapp_client.resolve_zernio_conversation_contacts([first, second]) == {}
    assert gets == [True]
    assert whatsapp_client._zernio_contact_cache == {}


def test_follow_up_hydration_persists_phone_and_name(monkeypatch):
    conversation_id = "0123456789abcdef01234567"
    rows = [{
        "id": 7,
        "conversation_id": conversation_id,
        "channel": "whatsapp",
        "first_name": "",
        "surnames": "",
        "phone_raw": "",
    }]
    captured = {}

    monkeypatch.setattr(
        api,
        "resolve_zernio_conversation_contacts",
        lambda _ids: {
            conversation_id: {"phone": "+34612345678", "name": "Lucía Carrillo"}
        },
    )

    def fake_upsert(conversation_id_arg, channel, **fields):
        captured.update({"conversation_id": conversation_id_arg, "channel": channel, **fields})
        return {**rows[0], **fields}

    monkeypatch.setattr(api.state_registry, "upsert_follow_up_request", fake_upsert)

    result = api._hydrate_follow_up_contact_identities(rows)

    assert captured["phone_raw"] == "+34612345678"
    assert captured["phone_normalized"] == "34612345678"
    assert captured["first_name"] == "Lucía"
    assert captured["surnames"] == "Carrillo"
    assert result[0]["phone_raw"] == "+34612345678"


def test_copied_follow_up_status_is_forwarded(monkeypatch):
    row = {"id": 7, "status": "collecting"}
    monkeypatch.setattr(api, "_require_callback_followups", lambda: None)
    monkeypatch.setattr(api.state_registry, "get_follow_up_request", lambda _id: row)
    monkeypatch.setattr(
        api.state_registry,
        "update_follow_up_status",
        lambda _id, status: {**row, "status": status},
    )

    result = asyncio.run(
        api.update_follow_up_status_endpoint(
            7,
            api.FollowUpStatusRequest(status="copied"),
        )
    )

    assert result["status"] == "copied"


def test_follow_up_list_disables_browser_and_proxy_caching(monkeypatch):
    monkeypatch.setattr(api, "_require_callback_followups", lambda: None)
    monkeypatch.setattr(api.state_registry, "list_follow_up_requests", lambda status=None: [])
    monkeypatch.setattr(api, "_hydrate_follow_up_contact_identities", lambda items: items)
    response = Response()

    result = asyncio.run(api.list_follow_ups_endpoint(response=response))

    assert result == {"items": [], "followUps": []}
    assert response.headers["cache-control"] == (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"
