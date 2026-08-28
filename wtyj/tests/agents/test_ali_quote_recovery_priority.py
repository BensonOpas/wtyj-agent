import sqlite3
from datetime import datetime, timedelta, timezone

from agents.social import ali_quote_recovery as recovery
from agents.social import ali_quote_workflow as workflow


CLASS_ID = "30000000-0000-4000-8000-000000000001"
DEPOSIT_ID = "90000000-0000-4000-8000-000000000001"


def raw_config():
    return {
        "slug": "ali-car-rental",
        "workflow": {
            "type": "ali_quote",
            "required_deposit_charge_id": DEPOSIT_ID,
        },
        "features": {
            "ali_quote_automation": True,
            "ali_quote_recovery_enabled": True,
        },
    }


def rental():
    return {
        "rental_start": "2026-09-01",
        "rental_end": "2026-09-23",
        "pickup_location": "Synthetic pickup",
        "return_location": "Synthetic return",
        "vehicle_class_id": CLASS_ID,
        "vehicle_class_name": "Synthetic class",
        "driver_age": 40,
        "extra_ids": [],
        "conversation_language": "en",
    }


def configure(monkeypatch, tmp_path):
    db_path = str(tmp_path / "tenant.db")
    monkeypatch.setattr(workflow.state_registry, "DB_PATH", db_path)
    monkeypatch.setattr(recovery.state_registry, "DB_PATH", db_path)
    monkeypatch.setattr(recovery.config_loader, "get_raw", raw_config)
    recovery.ensure_schema()


def create_quote(conversation_id):
    customer = {
        "name": "Synthetic Customer",
        "whatsapp": "+59990000000",
    }
    _, summary_hash = workflow.normalized_summary(customer, rental())
    quote, created = workflow.create_confirmed_quote(
        conversation_id,
        "synthetic-account",
        customer,
        rental(),
        summary_hash,
        "yes",
        DEPOSIT_ID,
        raw_config=raw_config(),
    )
    assert created
    return quote


def set_updated(public_id, value):
    conn = sqlite3.connect(workflow.state_registry.DB_PATH)
    conn.execute(
        "UPDATE ali_quotes SET updated_at = ? WHERE public_id = ?",
        (
            value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            public_id,
        ),
    )
    conn.commit()
    conn.close()


def test_new_replacement_quote_cannot_be_starved_by_old_attention_rows(
    monkeypatch, tmp_path,
):
    configure(monkeypatch, tmp_path)
    current = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    for index in range(25):
        old = create_quote(f"old-nonretryable-{index}")
        workflow.update_quote(
            old["public_id"],
            status="attention_required",
            attempt_count=1,
            last_error_code="pdf_integrity_failed",
        )
        set_updated(old["public_id"], current - timedelta(days=1))

    replacement = create_quote("new-confirmed-replacement")
    set_updated(replacement["public_id"], current - timedelta(seconds=31))

    candidates = recovery.list_recoverable_quotes(now=current, limit=20)
    assert [item["public_id"] for item in candidates] == [
        replacement["public_id"],
    ]


def test_legacy_processor_unconfigured_row_is_bounded_recoverable(
    monkeypatch, tmp_path,
):
    configure(monkeypatch, tmp_path)
    current = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    quote = create_quote("legacy-misclassified-replacement")
    workflow.update_quote(
        quote["public_id"],
        status="attention_required",
        attempt_count=1,
        last_error_code="processor_unconfigured",
    )
    set_updated(quote["public_id"], current - timedelta(hours=1))

    assert recovery.quote_is_recoverable(
        workflow.get_quote(quote["public_id"]),
        now=current,
    )

    workflow.update_quote(
        quote["public_id"],
        status="attention_required",
        attempt_count=recovery.MAX_ATTEMPTS,
        last_error_code="processor_unconfigured",
    )
    assert not recovery.quote_is_recoverable(
        workflow.get_quote(quote["public_id"]),
        now=current,
    )
