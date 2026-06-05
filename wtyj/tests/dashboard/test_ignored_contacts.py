import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("TENANT_ID", "ignored-test")

from dashboard.api import router
from shared import state_registry


def _client() -> tuple[TestClient, str]:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = client.post("/dashboard/api/login", json={"password": "testpass"}).json()["token"]
    return client, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _wipe():
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM ignored_contact_events WHERE tenant_id = 'ignored-test'")
    conn.execute("DELETE FROM ignored_contacts WHERE tenant_id = 'ignored-test'")
    conn.execute("DELETE FROM alert_settings")
    conn.commit()
    conn.close()


def test_state_registry_ignored_contact_match_and_remove():
    try:
        _wipe()
        row = state_registry.add_ignored_contact(
            name="Owner",
            phone="+599 9 688 1585",
            email="Owner@Example.COM",
            label="Owner",
            created_by="test",
        )
        assert row["phone_normalized"] == "59996881585"
        assert row["email_normalized"] == "owner@example.com"

        assert state_registry.match_ignored_contact(
            channel="whatsapp",
            sender_id="+59996881585",
            phone="+599 9 688 1585",
        )["id"] == row["id"]
        assert state_registry.match_ignored_contact(email="OWNER@example.com")["id"] == row["id"]

        state_registry.record_ignored_contact_event(
            contact_id=row["id"],
            channel="whatsapp",
            sender_identifier="+59996881585",
            message_id="msg-1",
        )
        events = state_registry.list_ignored_contact_events()
        assert events[0]["reason"] == "Ignored inbound message because sender is on Excluded Contacts / Ignore List."

        assert state_registry.delete_ignored_contact(row["id"]) is True
        assert state_registry.match_ignored_contact(phone="+599 9 688 1585") is None
    finally:
        _wipe()


def test_operator_whatsapp_destination_cannot_be_ignored():
    try:
        _wipe()
        state_registry.save_alert_settings(
            {
                "email": {"enabled": False, "destination": ""},
                "whatsapp": {"enabled": True, "destination": "+351963618003"},
                "telegram": {"enabled": False, "destination": ""},
                "messenger": {"enabled": False, "destination": ""},
            }
        )
        row = state_registry.add_ignored_contact(
            name="Operator",
            phone="+351963618003",
            email="calvin@example.com",
            label="Other",
            created_by="tenant-import",
        )
        customer = state_registry.add_ignored_contact(
            name="Customer",
            phone="+599 9 688 1585",
            label="Other",
            created_by="tenant-import",
        )

        assert row["phone_normalized"] == "351963618003"
        assert state_registry.match_ignored_contact(
            channel="whatsapp",
            sender_id="351963618003",
            phone="351963618003",
        ) is None
        assert state_registry.match_ignored_contact(
            channel="whatsapp",
            sender_id="59996881585",
            phone="+599 9 688 1585",
        )["id"] == customer["id"]
    finally:
        _wipe()


def test_ignored_contacts_api_manual_add_list_delete():
    try:
        _wipe()
        client, token = _client()
        response = client.post(
            "/dashboard/api/ignored-contacts",
            headers=_auth(token),
            json={
                "name": "Supplier",
                "email": "supplier@example.com",
                "label": "Supplier",
                "note": "Do not route automated replies.",
            },
        )
        assert response.status_code == 200, response.text
        contact = response.json()["contact"]
        assert contact["emailNormalized"] == "supplier@example.com"

        listing = client.get("/dashboard/api/ignored-contacts", headers=_auth(token))
        assert listing.status_code == 200, listing.text
        assert len(listing.json()["contacts"]) == 1

        delete = client.delete(f"/dashboard/api/ignored-contacts/{contact['id']}", headers=_auth(token))
        assert delete.status_code == 200, delete.text
        assert client.get("/dashboard/api/ignored-contacts", headers=_auth(token)).json()["contacts"] == []
    finally:
        _wipe()


def test_ignored_contacts_csv_preview_and_import_deselects_invalid_rows():
    try:
        _wipe()
        client, token = _client()
        csv_body = (
            "name,phone,email,label,note,channel\n"
            "Owner,+599 9 688 1585,,Owner,owner phone,whatsapp\n"
            "Owner duplicate,+59996881585,,Owner,duplicate,whatsapp\n"
            "Bad,,,,,\n"
        )
        preview = client.post(
            "/dashboard/api/ignored-contacts/import/validate",
            headers=_auth(token),
            files={"file": ("contacts.csv", csv_body, "text/csv")},
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["summary"]["total"] == 3
        assert body["summary"]["toAdd"] == 1
        assert body["summary"]["duplicates"] == 1
        assert body["summary"]["invalid"] == 1

        selected = [c for c in body["contacts"] if c["selected"]]
        imported = client.post(
            "/dashboard/api/ignored-contacts/import",
            headers=_auth(token),
            json={"contacts": selected},
        )
        assert imported.status_code == 200, imported.text
        assert len(imported.json()["added"]) == 1
        assert client.get("/dashboard/api/ignored-contacts", headers=_auth(token)).json()["contacts"][0]["phoneNormalized"] == "59996881585"
    finally:
        _wipe()


def test_ignored_contacts_vcf_preview():
    try:
        _wipe()
        client, token = _client()
        vcf = """BEGIN:VCARD
VERSION:3.0
FN:Private Contact
TEL;TYPE=CELL:+34 600 111 222
EMAIL:private@example.com
END:VCARD
"""
        preview = client.post(
            "/dashboard/api/ignored-contacts/import/validate",
            headers=_auth(token),
            files={"file": ("contacts.vcf", vcf, "text/vcard")},
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["summary"]["toAdd"] == 1
        assert body["contacts"][0]["name"] == "Private Contact"
        assert body["contacts"][0]["emailNormalized"] == "private@example.com"
    finally:
        _wipe()
