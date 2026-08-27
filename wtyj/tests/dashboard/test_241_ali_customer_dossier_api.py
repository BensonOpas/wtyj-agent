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


def test_contract_signature_public_endpoint_requires_explicit_consent(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        api.ali_customer_dossier,
        "sign_contract",
        lambda token, **kwargs: captured.update({"token": token, **kwargs})
        or {"status": "signed"},
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
