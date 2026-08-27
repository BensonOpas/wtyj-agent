"""Issue 241 dashboard/public API contracts."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from dashboard import api


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(api.ali_quote_workflow, "tenant_configured", lambda: True)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {api._SESSION_TOKEN}"}


def test_customer_file_and_configuration_are_authenticated_no_store(client, monkeypatch):
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "configuration_status",
        lambda: {"enabled": False, "ready": False, "blockers": ["feature_disabled"]},
    )
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "get_customer_file",
        lambda public_id: {"public_id": public_id, "missing_requirements": ["documents"]},
    )

    assert client.get("/dashboard/api/ali-dossier/configuration").status_code == 401
    configuration = client.get(
        "/dashboard/api/ali-dossier/configuration", headers=_auth(),
    )
    customer_file = client.get(
        "/dashboard/api/ali-reservations/res-241/customer-file", headers=_auth(),
    )

    assert configuration.status_code == 200
    assert configuration.json()["blockers"] == ["feature_disabled"]
    assert "no-store" in configuration.headers["cache-control"]
    assert customer_file.json()["public_id"] == "res-241"
    assert "no-store" in customer_file.headers["cache-control"]


def test_tenant_settings_and_template_upload_are_authenticated_no_store(client, monkeypatch):
    captured = {}
    settings = {
        "status": {"enabled": False, "ready": False, "configurationReady": False, "blockers": []},
        "contractTemplate": None,
        "payment": {
            "mode": "per_reservation",
            "providerName": "",
            "defaultLinkConfigured": False,
            "defaultDomain": None,
            "allowedDomains": ["pay.example.test"],
        },
        "retention": {
            "documentRetentionDays": 90,
            "paperShreddingPolicy": "Securely shred paper copies after 90 days.",
        },
    }
    monkeypatch.setattr(api.ali_customer_dossier, "tenant_settings", lambda: settings)
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "save_tenant_settings",
        lambda **kwargs: captured.update({"settings": kwargs}) or settings,
    )
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "upload_contract_template",
        lambda version, filename, content_type, payload, actor: captured.update({
            "version": version,
            "filename": filename,
            "content_type": content_type,
            "payload": payload,
            "actor": actor,
        }) or settings,
    )

    assert client.get("/dashboard/api/ali-dossier/settings").status_code == 401
    fetched = client.get("/dashboard/api/ali-dossier/settings", headers=_auth())
    updated = client.put(
        "/dashboard/api/ali-dossier/settings",
        headers=_auth(),
        json={
            "paymentMode": "per_reservation",
            "paymentProviderName": "Synthetic Pay",
            "clearPaymentUrl": True,
            "paymentAllowedDomains": ["pay.example.test"],
            "documentRetentionDays": 90,
            "paperShreddingPolicy": "Securely shred paper copies after 90 days.",
        },
    )
    uploaded = client.post(
        "/dashboard/api/ali-dossier/settings/contract-template",
        headers=_auth(),
        data={"version": "owner-v1"},
        files={"file": ("contract.md", b"Approved terms", "text/markdown")},
    )

    assert fetched.status_code == 200
    assert updated.status_code == 200
    assert uploaded.status_code == 200
    assert "no-store" in fetched.headers["cache-control"]
    assert "no-store" in updated.headers["cache-control"]
    assert "no-store" in uploaded.headers["cache-control"]
    assert captured["settings"]["document_retention_days"] == 90
    assert captured["payload"] == b"Approved terms"
    assert captured["actor"] == "dashboard"


def test_tenant_activation_is_authenticated_strict_and_no_store(client, monkeypatch):
    captured = {}
    settings = {
        "status": {
            "enabled": True,
            "ready": True,
            "configurationReady": True,
            "blockers": [],
        },
        "contractTemplate": {"publicId": "template-241", "version": "owner-v1"},
        "payment": {"mode": "per_reservation", "allowedDomains": ["pay.example.test"]},
        "retention": {"documentRetentionDays": 90},
    }
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "set_tenant_activation",
        lambda enabled, actor: captured.update({
            "enabled": enabled,
            "actor": actor,
        }) or settings,
    )

    path = "/dashboard/api/ali-dossier/settings/activation"
    assert client.put(path, json={"enabled": True}).status_code == 401
    assert client.put(
        path,
        headers=_auth(),
        json={"enabled": "true"},
    ).status_code == 422
    activated = client.put(
        path,
        headers=_auth(),
        json={"enabled": True},
    )

    assert activated.status_code == 200
    assert activated.json()["status"]["ready"] is True
    assert "no-store" in activated.headers["cache-control"]
    assert captured == {"enabled": True, "actor": "dashboard"}


def test_document_mutations_require_revision_and_auth(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "review_document",
        lambda public_id, document_id, decision, actor, expected_revision=None: (
            captured.update({
                "public_id": public_id,
                "document_id": document_id,
                "decision": decision,
                "actor": actor,
                "expected_revision": expected_revision,
            })
            or {"status": decision}
        ),
    )

    missing_revision = client.post(
        "/dashboard/api/ali-reservations/res-241/documents/doc-1/review",
        headers=_auth(),
        json={"decision": "verified"},
    )
    unauthorized = client.post(
        "/dashboard/api/ali-reservations/res-241/documents/doc-1/review",
        json={"decision": "verified", "expectedRevision": 4},
    )
    response = client.post(
        "/dashboard/api/ali-reservations/res-241/documents/doc-1/review",
        headers=_auth(),
        json={"decision": "verified", "expectedRevision": 4},
    )

    assert missing_revision.status_code == 422
    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert captured == {
        "public_id": "res-241",
        "document_id": "doc-1",
        "decision": "verified",
        "actor": "dashboard",
        "expected_revision": 4,
    }


def test_replacement_request_delivers_fresh_link(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "request_document_replacement",
        lambda public_id, document_id, actor, expected_revision=None: {
            "links": [{"slot": "license_front", "url": "https://example.test/fresh"}],
        },
    )
    monkeypatch.setattr(
        api.ali_quote_delivery,
        "send_customer_requirement_link",
        lambda public_id, requirement, payload: captured.update({
            "public_id": public_id,
            "requirement": requirement,
            "payload": payload,
        }) or True,
    )
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "get_customer_file",
        lambda public_id: {"public_id": public_id, "revision": 8},
    )

    response = client.post(
        "/dashboard/api/ali-reservations/res-241/documents/doc-1/request-replacement",
        headers=_auth(),
        json={"expectedRevision": 7},
    )

    assert response.status_code == 200
    assert response.json()["delivered"] is True
    assert captured["requirement"] == "documents"
    assert captured["payload"]["links"][0]["url"].endswith("/fresh")


def test_pickup_inspection_is_revision_bound(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        api.ali_reservation_workflow,
        "record_original_document_inspection",
        lambda public_id, item, actor, expected_revision=None: captured.update({
            "public_id": public_id,
            "item": item,
            "actor": actor,
            "expected_revision": expected_revision,
        }) or {"status": "confirmed"},
    )

    response = client.post(
        "/dashboard/api/ali-reservations/res-241/pickup-inspection",
        headers=_auth(),
        json={"item": "identity", "expectedRevision": 12},
    )

    assert response.status_code == 200
    assert captured == {
        "public_id": "res-241",
        "item": "identity",
        "actor": "dashboard",
        "expected_revision": 12,
    }


def test_document_download_never_caches_private_bytes(client, monkeypatch):
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "document_bytes",
        lambda public_id, document_id: (b"synthetic-image", "image/png"),
    )

    response = client.get(
        "/dashboard/api/ali-reservations/res-241/documents/doc-1/content",
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.content == b"synthetic-image"
    assert response.headers["content-type"].startswith("image/png")
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["content-disposition"] == "inline; filename=document"


def test_public_upload_is_slot_bound_and_has_no_store(client, monkeypatch):
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "document_upload_context",
        lambda token: {
            "slot": "license_front",
            "accept": ["image/png"],
            "maxBytes": 1024,
            "expiresAt": "2099-01-01T00:00:00Z",
        },
    )
    captured = {}
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "store_document_upload",
        lambda token, payload, mime: captured.update(
            {"token": token, "payload": payload, "mime": mime}
        ) or {"public_id": "doc-1"},
    )

    page = client.get("/dashboard/api/ali-reservations/public/documents/token-241")
    uploaded = client.post(
        "/dashboard/api/ali-reservations/public/documents/token-241",
        files={"file": ("synthetic.png", b"png-bytes", "image/png")},
    )

    assert page.status_code == 200
    assert "License Front".casefold() in page.text.casefold()
    assert "no-store" in page.headers["cache-control"]
    assert uploaded.status_code == 200
    assert captured == {
        "token": "token-241",
        "payload": b"png-bytes",
        "mime": "image/png",
    }


def test_contract_signature_page_allows_same_origin_submit_and_recovers(
    client, monkeypatch,
):
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "contract_review_context",
        lambda token: {
            "contract": {"publicId": "contract-241"},
            "pdfBase64": "JVBERi0xLjQK",
            "consentRequired": True,
        },
    )

    page = client.get(
        "/dashboard/api/ali-reservations/public/contracts/token-241",
    )

    assert page.status_code == 200
    policy = page.headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "connect-src 'self'" in policy
    assert "<button id=\"sign\" type=\"button\">" in page.text
    assert "location.pathname.replace(/[/]$/,'')+'/sign'" in page.text
    assert "new AbortController()" in page.text
    assert "if(submitting||signed)return" in page.text
    assert "catch(error)" in page.text
    assert "if(!signed)b.disabled=false" in page.text
    assert "Unable to sign. Please check your connection and try again." in page.text

    upload_page = api._public_ali_html("Upload", "<p>Upload</p>")
    assert "connect-src" not in upload_page.headers["content-security-policy"]


def test_contract_signature_public_endpoint_requires_explicit_consent(client, monkeypatch):
    captured = {}
    events = []
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "sign_contract",
        lambda token, **kwargs: captured.update({"token": token, **kwargs})
        or {"status": "signed"},
    )
    monkeypatch.setattr(
        api.bm_logger,
        "log",
        lambda event, **fields: events.append((event, fields)),
    )

    invalid = client.post(
        "/dashboard/api/ali-reservations/public/contracts/token-241/sign",
        json={
            "consent": False,
            "legalName": "Synthetic Customer",
            "signatureData": "data:image/png;base64," + "a" * 40,
        },
    )
    valid = client.post(
        "/dashboard/api/ali-reservations/public/contracts/token-241/sign",
        json={
            "consent": True,
            "legalName": "Synthetic Customer",
            "signatureData": "data:image/png;base64," + "a" * 40,
        },
    )

    # Pydantic validates the boolean type; the workflow enforces that it is true.
    assert invalid.status_code == 200
    assert valid.status_code == 200
    assert captured["token"] == "token-241"
    assert captured["consent"] is True
    assert [event for event, _fields in events] == [
        "ali_public_contract_sign_requested",
        "ali_public_contract_sign_succeeded",
        "ali_public_contract_sign_requested",
        "ali_public_contract_sign_succeeded",
    ]
    assert "token-241" not in repr(events)
    assert "Synthetic Customer" not in repr(events)
    assert "data:image/png" not in repr(events)


def test_contract_signature_failure_is_sanitized_and_returns(client, monkeypatch):
    events = []
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "sign_contract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            api.ali_reservation_workflow.AliReservationError(
                "invalid_signature_image", 422,
            )
        ),
    )
    monkeypatch.setattr(
        api.bm_logger,
        "log",
        lambda event, **fields: events.append((event, fields)),
    )

    response = client.post(
        "/dashboard/api/ali-reservations/public/contracts/token-secret/sign",
        json={
            "consent": True,
            "legalName": "Sensitive Name",
            "signatureData": "data:image/png;base64," + "a" * 40,
        },
    )

    assert response.status_code == 422
    assert [event for event, _fields in events] == [
        "ali_public_contract_sign_requested",
        "ali_public_contract_sign_failed",
        "ali_reservation_dashboard_rejected",
    ]
    assert events[1][1]["error_code"] == "invalid_signature_image"
    assert "token-secret" not in repr(events)
    assert "Sensitive Name" not in repr(events)
    assert "data:image/png" not in repr(events)


def test_dossier_print_is_authenticated_streamed_and_revision_bound(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "generate_dossier",
        lambda public_id, actor, **kwargs: captured.update(
            {"public_id": public_id, "actor": actor, **kwargs}
        ) or {
            "bytes": b"%PDF-synthetic",
            "filename": "ALI-Dossier-SYNTH-v1.pdf",
            "version": 1,
            "status": "incomplete",
            "sha256": "a" * 64,
            "pageCount": 2,
        },
    )

    response = client.post(
        "/dashboard/api/ali-reservations/res-241/dossier.pdf",
        headers=_auth(),
        json={"expectedRevision": 9, "allowIncomplete": True, "pageSize": "LETTER"},
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-synthetic"
    assert response.headers["content-type"].startswith("application/pdf")
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-ali-dossier-version"] == "1"
    assert captured["expected_revision"] == 9
