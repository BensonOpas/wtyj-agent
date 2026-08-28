import json
import sqlite3
from datetime import datetime, timedelta, timezone

from agents.social import ali_quote_recovery as recovery
from agents.social import ali_quote_workflow as workflow


CLASS_ID = "30000000-0000-4000-8000-000000000001"
DEPOSIT_ID = "90000000-0000-4000-8000-000000000001"


def raw_config(recovery_enabled=True):
    return {
        "slug": "ali-car-rental",
        "workflow": {
            "type": "ali_quote",
            "required_deposit_charge_id": DEPOSIT_ID,
        },
        "features": {
            "ali_quote_automation": True,
            "ali_quote_customer_delivery": True,
            "ali_quote_staff_email": True,
            "ali_quote_operator_alerts": True,
            "ali_quote_recovery_enabled": recovery_enabled,
        },
    }


def customer():
    return {"name": "Synthetic Customer", "whatsapp": "+59990000000"}


def rental(end="2026-09-08"):
    return {
        "rental_start": "2026-09-01",
        "rental_end": end,
        "pickup_location": "Synthetic airport pickup",
        "return_location": "Synthetic airport return",
        "vehicle_class_id": CLASS_ID,
        "vehicle_class_name": "Small car",
        "driver_age": 40,
        "extra_ids": [],
        "conversation_language": "en",
    }


def configure(monkeypatch, tmp_path):
    db_path = str(tmp_path / "tenant.db")
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", db_path)
    monkeypatch.setattr(recovery.state_registry, "DB_PATH", db_path)
    monkeypatch.setattr(recovery.config_loader, "get_raw", lambda: raw_config())
    recovery.ensure_schema()


def create_quote(selected_rental, version=1, conversation="replacement-conversation"):
    _, summary_hash = workflow.normalized_summary(
        customer(), selected_rental, version=version,
    )
    quote, created = workflow.create_confirmed_quote(
        conversation,
        "account-synthetic",
        customer(),
        selected_rental,
        summary_hash,
        "yes",
        DEPOSIT_ID,
        summary_version=version,
        raw_config=raw_config(),
    )
    assert created
    return quote


def set_updated_at(public_id, value):
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "UPDATE ali_quotes SET updated_at = ? WHERE public_id = ?",
        (value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), public_id),
    )
    conn.commit()
    conn.close()


def test_confirmed_fifteen_day_change_is_recovered_as_one_distinct_second_quote(
    monkeypatch, tmp_path,
):
    configure(monkeypatch, tmp_path)
    first = create_quote(rental(), version=1)
    workflow.update_quote(
        first["public_id"],
        status="complete",
        whatsapp_status="accepted",
        staff_email_status="sent",
        brand_image_status="accepted",
    )

    replacement_rental = rental(end="2026-09-23")
    second = create_quote(replacement_rental, version=2)
    assert second["public_id"] != first["public_id"]
    assert json.loads(workflow.get_quote(first["public_id"])["rental_json"])[
        "rental_end"
    ] == "2026-09-08"
    assert json.loads(second["rental_json"])["rental_end"] == "2026-09-23"

    current = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    set_updated_at(second["public_id"], current - timedelta(seconds=31))
    processed = []

    def processor(public_id):
        processed.append(public_id)
        workflow.update_quote(
            public_id,
            status="complete",
            whatsapp_status="accepted",
            staff_email_status="sent",
            brand_image_status="accepted",
        )

    assert recovery.recover_once(processor=processor, now=current) == 1
    assert processed == [second["public_id"]]
    assert workflow.get_quote(second["public_id"])["whatsapp_status"] == "accepted"

    # A replay cannot create or deliver a third quote.
    assert recovery.recover_once(processor=processor, now=current) == 0
    assert processed == [second["public_id"]]
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    quote_count = conn.execute(
        "SELECT COUNT(*) FROM ali_quotes WHERE conversation_id = ?",
        ("replacement-conversation",),
    ).fetchone()[0]
    conn.close()
    assert quote_count == 2


def test_recovery_lease_blocks_parallel_worker_and_reclaims_expiry(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    quote = create_quote(rental())
    current = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    assert recovery.acquire_lease(
        quote["public_id"], owner_token="worker-a", now=current,
        lease_seconds=600,
    ) == "worker-a"
    assert recovery.acquire_lease(
        quote["public_id"], owner_token="worker-b", now=current,
        lease_seconds=600,
    ) is None
    assert recovery.release_lease(quote["public_id"], "worker-b") is False

    assert recovery.acquire_lease(
        quote["public_id"], owner_token="worker-b",
        now=current + timedelta(seconds=601), lease_seconds=600,
    ) == "worker-b"
    assert recovery.release_lease(quote["public_id"], "worker-b") is True


def test_retryable_attention_required_is_bounded_and_nonretryable_is_not_requeued(
    monkeypatch, tmp_path,
):
    configure(monkeypatch, tmp_path)
    quote = create_quote(rental())
    current = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    workflow.update_quote(
        quote["public_id"],
        status="attention_required",
        attempt_count=1,
        last_error_code="whatsapp_delivery_failed",
    )
    set_updated_at(quote["public_id"], current - timedelta(seconds=16))
    assert recovery.quote_is_recoverable(
        workflow.get_quote(quote["public_id"]), now=current,
    )

    workflow.update_quote(
        quote["public_id"],
        status="attention_required",
        attempt_count=1,
        last_error_code="processor_unconfigured",
    )
    set_updated_at(quote["public_id"], current - timedelta(hours=1))
    assert not recovery.quote_is_recoverable(
        workflow.get_quote(quote["public_id"]), now=current,
    )

    workflow.update_quote(
        quote["public_id"],
        status="attention_required",
        attempt_count=recovery.MAX_ATTEMPTS,
        last_error_code="whatsapp_delivery_failed",
    )
    assert not recovery.quote_is_recoverable(
        workflow.get_quote(quote["public_id"]), now=current,
    )


def test_delivering_quote_is_not_reclaimed_during_three_minute_customer_delay(
    monkeypatch, tmp_path,
):
    configure(monkeypatch, tmp_path)
    quote = create_quote(rental())
    workflow.update_quote(quote["public_id"], status="delivering")
    current = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    set_updated_at(quote["public_id"], current - timedelta(seconds=180))
    assert not recovery.quote_is_recoverable(
        workflow.get_quote(quote["public_id"]), now=current,
    )

    set_updated_at(quote["public_id"], current - timedelta(seconds=241))
    assert recovery.quote_is_recoverable(
        workflow.get_quote(quote["public_id"]), now=current,
    )


def test_recovery_switch_is_ali_only_and_can_be_rolled_back(monkeypatch):
    assert recovery.feature_enabled(raw_config())
    assert not recovery.feature_enabled(raw_config(recovery_enabled=False))
    other = raw_config()
    other["slug"] = "other-tenant"
    assert not recovery.feature_enabled(other)
