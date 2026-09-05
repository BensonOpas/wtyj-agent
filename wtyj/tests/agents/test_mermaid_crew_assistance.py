"""Private wheelchair-assistance queue behavior for Mermaid."""

import json
import sqlite3
import threading
from pathlib import Path

import pytest
from pypdf import PdfReader

from agents.social import mermaid_crew_assistance as assistance
from agents.social import mermaid_documents
from agents.social import mermaid_reservation_store as reservations
from shared import config_loader, state_registry


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(
        config_loader,
        "_CONFIG_PATH",
        str(Path(__file__).resolve().parents[3] / "clients/mermaid/config/client.json"),
    )
    monkeypatch.setattr(config_loader, "_cache", {})


def test_note_replay_is_idempotent_and_acknowledgement_records_first_actor():
    created, outcome = assistance.record_wheelchair_note(
        "conversation-1",
        note="Guest's husband uses a wheelchair.",
        relationship="husband",
        trip_date="2026-09-06",
        customer_name="Synthetic Guest",
        source_message_id="message-1",
    )
    assert outcome == "created"
    assert created["status"] == "unacknowledged"
    assert created["revision"] == 1

    replay, outcome = assistance.record_wheelchair_note(
        "conversation-1",
        note="Guest's husband uses a wheelchair.",
        relationship="husband",
        trip_date="2026-09-06",
        customer_name="Synthetic Guest",
        source_message_id="message-1",
    )
    assert outcome == "replayed"
    assert replay == created
    assert len(assistance.list_items()) == 1

    acknowledged = assistance.acknowledge(
        created["id"], expected_revision=1, acknowledged_by="Calvin"
    )
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledgedBy"] == "Calvin"
    assert acknowledged["acknowledgedAt"]

    repeated = assistance.acknowledge(
        created["id"], expected_revision=1, acknowledged_by="Another operator"
    )
    assert repeated == acknowledged
    assert [event["event_type"] for event in assistance.events(created["id"])] == [
        "created",
        "acknowledged",
    ]


def test_material_correction_and_trip_date_reopen_current_item():
    original, _ = assistance.record_wheelchair_note(
        "conversation-2",
        note="One guest uses a wheelchair.",
        trip_date="2026-09-06",
        source_message_id="message-1",
    )
    assistance.acknowledge(original["id"], expected_revision=1, acknowledged_by="Jr")

    corrected, outcome = assistance.record_wheelchair_note(
        "conversation-2",
        note="Guest's husband uses a wheelchair and requested general crew help.",
        relationship="husband",
        trip_date="2026-09-06",
        source_message_id="message-2",
    )
    assert outcome == "updated"
    assert corrected["revision"] == 2
    assert corrected["status"] == "unacknowledged"
    assert corrected["acknowledgedAt"] is None
    assert corrected["acknowledgedBy"] is None

    date_change = assistance.sync_existing(
        "conversation-2",
        trip_date="2026-09-13",
        customer_name="Updated Name",
        source_message_id="message-3",
    )
    assert date_change["revision"] == 3
    assert date_change["tripDate"] == "2026-09-13"
    assert date_change["customerName"] == "Updated Name"
    with pytest.raises(assistance.CrewAssistanceConflict):
        assistance.acknowledge(original["id"], expected_revision=2, acknowledged_by="Calvin")


def test_out_of_order_provider_replays_cannot_roll_back_or_withdraw_newer_state():
    item, _ = assistance.record_wheelchair_note(
        "conversation-out-of-order",
        note="A guest in this party uses a wheelchair.",
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id="message-1",
    )
    assistance.record_wheelchair_note(
        "conversation-out-of-order",
        note="The guest's husband uses a wheelchair.",
        relationship="husband",
        trip_date="2026-09-13",
        source_message_id="message-2",
    )
    replayed, outcome = assistance.record_wheelchair_note(
        "conversation-out-of-order",
        note="A guest in this party uses a wheelchair.",
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id="message-1",
    )
    assert outcome == "replayed"
    assert replayed["revision"] == 2
    assert replayed["relationship"] == "husband"
    assert replayed["tripDate"] == "2026-09-13"

    assistance.sync_existing(
        "conversation-out-of-order",
        trip_date="2026-09-20",
        source_message_id="date-1",
    )
    assistance.sync_existing(
        "conversation-out-of-order",
        trip_date="2026-09-27",
        source_message_id="date-2",
    )
    stale_date = assistance.sync_existing(
        "conversation-out-of-order",
        trip_date="2026-09-20",
        source_message_id="date-1",
    )
    assert stale_date["tripDate"] == "2026-09-27"

    assistance.withdraw(
        "conversation-out-of-order", source_message_id="withdraw-1"
    )
    reopened, _ = assistance.record_wheelchair_note(
        "conversation-out-of-order",
        note="The guest's husband uses a wheelchair.",
        relationship="husband",
        trip_date="2026-09-27",
        source_message_id="message-3",
    )
    assert reopened["status"] == "unacknowledged"
    stale_withdrawal = assistance.withdraw(
        "conversation-out-of-order", source_message_id="withdraw-1"
    )
    assert stale_withdrawal["status"] == "unacknowledged"
    assert stale_withdrawal["revision"] == reopened["revision"]


def test_previously_unchanged_source_cannot_roll_back_a_later_correction():
    assistance.record_wheelchair_note(
        "conversation-unchanged-replay",
        note="A guest in this party uses a wheelchair.",
        relationship="unspecified",
        source_message_id="message-1",
    )
    unchanged, outcome = assistance.record_wheelchair_note(
        "conversation-unchanged-replay",
        note="A guest in this party uses a wheelchair.",
        relationship="unspecified",
        source_message_id="message-2",
    )
    assert outcome == "unchanged"
    assert unchanged["revision"] == 1
    corrected, outcome = assistance.record_wheelchair_note(
        "conversation-unchanged-replay",
        note="The guest's husband uses a wheelchair.",
        relationship="husband",
        source_message_id="message-3",
    )
    assert outcome == "updated"

    replayed, outcome = assistance.record_wheelchair_note(
        "conversation-unchanged-replay",
        note="A guest in this party uses a wheelchair.",
        relationship="unspecified",
        source_message_id="message-2",
    )

    assert outcome == "replayed"
    assert replayed["revision"] == corrected["revision"]
    assert replayed["relationship"] == "husband"
    assert replayed["note"] == "The guest's husband uses a wheelchair."


def test_noop_sync_and_repeated_withdrawal_sources_are_replay_safe():
    conversation = "conversation-noop-source-replay"
    assistance.record_wheelchair_note(
        conversation,
        note="A guest in this party uses a wheelchair.",
        trip_date="2026-09-06",
        source_message_id="create-1",
    )
    assistance.sync_existing(
        conversation,
        trip_date="2026-09-06",
        source_message_id="sync-noop",
    )
    assistance.sync_existing(
        conversation,
        trip_date="2026-09-13",
        source_message_id="sync-newer",
    )
    replayed_sync = assistance.sync_existing(
        conversation,
        trip_date="2026-09-06",
        source_message_id="sync-noop",
    )
    assert replayed_sync["tripDate"] == "2026-09-13"

    assistance.withdraw(conversation, source_message_id="withdraw-first")
    assistance.withdraw(conversation, source_message_id="withdraw-noop")
    assistance.record_wheelchair_note(
        conversation,
        note="A guest in this party uses a wheelchair.",
        trip_date="2026-09-20",
        source_message_id="reopen-newer",
    )
    replayed_withdrawal = assistance.withdraw(
        conversation, source_message_id="withdraw-noop"
    )
    assert replayed_withdrawal["status"] == "unacknowledged"
    assert replayed_withdrawal["tripDate"] == "2026-09-20"


def test_interleaved_acknowledgement_and_correction_never_loses_correction():
    item, _ = assistance.record_wheelchair_note(
        "conversation-race",
        note="A guest in this party uses a wheelchair.",
        trip_date="2026-09-06",
        source_message_id="race-original",
    )
    barrier = threading.Barrier(3)
    errors = []

    def acknowledge():
        barrier.wait()
        try:
            assistance.acknowledge(
                item["id"], expected_revision=1, acknowledged_by="Calvin"
            )
        except assistance.CrewAssistanceConflict:
            pass
        except Exception as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    def correct():
        barrier.wait()
        try:
            assistance.sync_existing(
                "conversation-race",
                trip_date="2026-09-13",
                source_message_id="race-correction",
            )
        except Exception as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = [threading.Thread(target=acknowledge), threading.Thread(target=correct)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    current = assistance.for_conversation("conversation-race")
    assert current["tripDate"] == "2026-09-13"
    assert current["revision"] == 2
    assert current["status"] == "unacknowledged"


def test_confirmed_reservation_keeps_private_note_links_attention_and_excludes_pdf(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MERMAID_DOCUMENT_ROOT", str(tmp_path / "documents"))
    intake = {
        "trip_date": "2026-09-06",
        "adults": 3,
        "children": 1,
        "infants": 1,
        "child_ages": [{"value": 9, "unit": "years"}, {"value": 11, "unit": "months"}],
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
        "accessibility_notes": "Guest's husband uses a wheelchair.",
        "wheelchair_relationship": "husband",
    }
    note, _ = assistance.record_wheelchair_note(
        "conversation-3",
        note=intake["accessibility_notes"],
        relationship="husband",
        trip_date=intake["trip_date"],
        customer_name=intake["customer_name"],
        source_message_id="message-1",
    )
    reservation = reservations.confirm_reservation(
        "conversation-3", intake, idempotency_key="confirm:conversation-3"
    )
    linked = assistance.for_reservation(reservation["public_id"])
    assert linked["id"] == note["id"]
    assert linked["reservationPublicId"] == reservation["public_id"]
    assert "accessibility_notes" not in reservation["intake"]
    assert "wheelchair_relationship" not in reservation["intake"]
    assert reservation["human_takeover"] is False

    document, _job = mermaid_documents.create_quote(reservation)
    rendered = "\n".join(
        page.extract_text() or "" for page in PdfReader(document["path"]).pages
    )
    assert intake["accessibility_notes"] not in rendered
    assert "wheelchair" not in rendered.casefold()
    assert "husband" not in rendered.casefold()


@pytest.mark.parametrize(
    "kind_order",
    [
        (assistance.KIND_WHEELCHAIR, assistance.KIND_BOARDING_ASSISTANCE),
        (assistance.KIND_BOARDING_ASSISTANCE, assistance.KIND_WHEELCHAIR),
    ],
)
def test_confirmation_links_both_active_kinds_and_wheelchair_withdrawal_keeps_boarding_unread(
    kind_order,
):
    conversation = f"conversation-two-kinds-{'-'.join(kind_order)}"
    created = {}
    for index, kind in enumerate(kind_order):
        values = {
            "conversation_id": conversation,
            "note": (
                "A guest in this party uses a wheelchair."
                if kind == assistance.KIND_WHEELCHAIR
                else "A guest requested general crew help while boarding."
            ),
            "relationship": "unspecified",
            # General help can be requested before the guest supplies a date.
            "trip_date": (
                "2026-09-06" if kind == assistance.KIND_WHEELCHAIR else ""
            ),
            "customer_name": "Synthetic Guest",
            "source_message_id": f"two-kinds-{index}-{kind}",
        }
        recorder = (
            assistance.record_wheelchair_note
            if kind == assistance.KIND_WHEELCHAIR
            else assistance.record_boarding_assistance_note
        )
        created[kind] = recorder(**values)[0]

    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    reservation = reservations.confirm_reservation(
        conversation, intake, idempotency_key=f"confirm:{conversation}"
    )
    replayed = reservations.confirm_reservation(
        conversation, intake, idempotency_key=f"confirm-replay:{conversation}"
    )
    assert replayed["public_id"] == reservation["public_id"]

    conn = assistance._conn()
    linked = conn.execute(
        "SELECT a.kind,r.status FROM mermaid_crew_assistance_reservations r "
        "JOIN mermaid_crew_assistance a ON a.id=r.assistance_id "
        "WHERE r.reservation_public_id=? ORDER BY a.kind",
        (reservation["public_id"],),
    ).fetchall()
    conn.close()
    assert [(row["kind"], row["status"]) for row in linked] == [
        (assistance.KIND_BOARDING_ASSISTANCE, "unacknowledged"),
        (assistance.KIND_WHEELCHAIR, "unacknowledged"),
    ]
    for item in created.values():
        assert [
            event["event_type"] for event in assistance.events(item["id"])
        ].count("reservation_linked") == 1

    withdrawn = assistance.withdraw(
        conversation, source_message_id=f"withdraw:{conversation}"
    )
    assert withdrawn["kind"] == assistance.KIND_WHEELCHAIR
    assert withdrawn["status"] == "withdrawn"
    current = assistance.for_conversation(conversation)
    assert current["id"] == created[assistance.KIND_BOARDING_ASSISTANCE]["id"]
    assert current["status"] == "unacknowledged"
    assert [item["kind"] for item in assistance.list_items("unacknowledged")] == [
        assistance.KIND_BOARDING_ASSISTANCE
    ]
    assert assistance.for_reservation(reservation["public_id"])["id"] == current["id"]
    assert assistance.for_reservations([reservation["public_id"]])[
        reservation["public_id"]
    ]["id"] == current["id"]


@pytest.mark.parametrize(
    ("kind", "note"),
    [
        (
            assistance.KIND_WHEELCHAIR,
            "A guest in this party uses a wheelchair.",
        ),
        (
            assistance.KIND_BOARDING_ASSISTANCE,
            "A guest requested general crew help while boarding.",
        ),
    ],
)
def test_same_date_second_booking_requires_explicit_assistance_reassertion(
    kind, note
):
    conversation = f"conversation-second-booking-{kind}"
    recorder = (
        assistance.record_wheelchair_note
        if kind == assistance.KIND_WHEELCHAIR
        else assistance.record_boarding_assistance_note
    )
    item, _ = recorder(
        conversation,
        note=note,
        relationship="unspecified",
        trip_date="2026-09-06",
        customer_name="First Party",
        source_message_id=f"first-source-{kind}",
    )
    base = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    first = reservations.confirm_reservation(
        conversation,
        {**base, "customer_name": "First Party"},
        idempotency_key=f"first-confirm-{kind}",
    )
    second_intake = {
        **base,
        "adults": 3,
        "customer_name": "Second Party",
    }
    second = reservations.confirm_reservation(
        conversation,
        second_intake,
        idempotency_key=f"second-confirm-{kind}",
    )

    assert second["public_id"] != first["public_id"]
    assert assistance.for_reservation(second["public_id"]) is None
    assert assistance.for_reservation(first["public_id"])["id"] == item["id"]
    assert assistance.for_conversation(conversation, kind=kind)[
        "reservationPublicId"
    ] == first["public_id"]

    reasserted, outcome = recorder(
        conversation,
        note=note,
        relationship="unspecified",
        trip_date="2026-09-06",
        customer_name="Second Party",
        source_message_id=f"second-source-{kind}",
    )
    assert outcome == "updated"
    assert reasserted["id"] == item["id"]
    assert reasserted["reservationPublicId"] is None

    replayed = reservations.confirm_reservation(
        conversation,
        second_intake,
        idempotency_key=f"second-confirm-reasserted-{kind}",
    )
    assert replayed["public_id"] == second["public_id"]
    assert assistance.for_reservation(second["public_id"])["id"] == item["id"]
    assert assistance.for_reservation(first["public_id"])["revision"] == 1


@pytest.mark.parametrize(
    ("kind", "note"),
    [
        (
            assistance.KIND_WHEELCHAIR,
            "A guest in this party uses a wheelchair.",
        ),
        (
            assistance.KIND_BOARDING_ASSISTANCE,
            "A guest requested general crew help while boarding.",
        ),
    ],
)
def test_same_reservation_restatement_preserves_lifecycle_before_and_after_ack(
    kind, note
):
    conversation = f"conversation-existing-restatement-{kind}"
    recorder = (
        assistance.record_wheelchair_note
        if kind == assistance.KIND_WHEELCHAIR
        else assistance.record_boarding_assistance_note
    )
    item, _ = recorder(
        conversation,
        note=note,
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id=f"initial-restatement-{kind}",
    )
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    reservation = reservations.confirm_reservation(
        conversation,
        intake,
        idempotency_key=f"existing-restatement-confirm-{kind}",
    )

    repeated, outcome = recorder(
        conversation,
        note=note,
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id=f"unread-restatement-{kind}",
        reservation_public_id=reservation["public_id"],
    )
    assert outcome == "unchanged"
    assert repeated["revision"] == 1
    assert repeated["reservationPublicId"] == reservation["public_id"]
    assistance.link_current(
        conversation,
        reservation["public_id"],
        idempotency_key=f"unread-restatement-link-{kind}",
    )

    assistance.acknowledge(
        item["id"], expected_revision=1, acknowledged_by="Crew Member"
    )
    acknowledged, outcome = recorder(
        conversation,
        note=note,
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id=f"ack-restatement-{kind}",
        reservation_public_id=reservation["public_id"],
    )
    assert outcome == "unchanged"
    assert acknowledged["revision"] == 1
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["reservationPublicId"] == reservation["public_id"]
    assistance.link_current(
        conversation,
        reservation["public_id"],
        idempotency_key=f"ack-restatement-link-{kind}",
    )
    linked = assistance.for_reservation(reservation["public_id"], kind=kind)
    assert linked["revision"] == 1
    assert linked["status"] == "acknowledged"


def test_corrected_summary_with_explicit_wheelchair_fact_links_replacement_row():
    conversation = "conversation-corrected-summary-wheelchair"
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
        "accessibility_notes": "A guest in this party uses a wheelchair.",
        "wheelchair_relationship": "unspecified",
    }
    first = reservations.confirm_reservation(
        conversation, intake, idempotency_key="corrected-summary-first"
    )
    second = reservations.confirm_reservation(
        conversation,
        {**intake, "adults": 3},
        idempotency_key="corrected-summary-second",
    )

    assert second["public_id"] != first["public_id"]
    assert assistance.for_reservation(first["public_id"], kind="wheelchair")[
        "revision"
    ] == 1
    corrected = assistance.for_reservation(
        second["public_id"], kind="wheelchair"
    )
    assert corrected is not None
    assert corrected["revision"] == 2
    assert corrected["reservationPublicId"] == second["public_id"]


def test_round_trip_date_correction_reclaims_existing_link_snapshot():
    conversation = "conversation-round-trip-date-correction"
    item, _ = assistance.record_wheelchair_note(
        conversation,
        note="A guest in this party uses a wheelchair.",
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id="round-trip-wheelchair",
    )
    base = {
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    first_intake = {**base, "trip_date": "2026-09-06"}
    first = reservations.confirm_reservation(
        conversation, first_intake, idempotency_key="round-trip-first"
    )
    assistance.acknowledge(
        item["id"], expected_revision=1, acknowledged_by="Crew One"
    )
    assistance.sync_existing(
        conversation,
        trip_date="2026-09-13",
        source_message_id="round-trip-to-second-date",
    )
    second = reservations.confirm_reservation(
        conversation,
        {**base, "trip_date": "2026-09-13"},
        idempotency_key="round-trip-second",
    )
    assistance.acknowledge(
        item["id"], expected_revision=2, acknowledged_by="Crew Two"
    )
    returned = assistance.sync_existing(
        conversation,
        trip_date="2026-09-06",
        source_message_id="round-trip-back-to-first-date",
    )
    assert returned["revision"] == 3
    assert returned["reservationPublicId"] is None

    replayed_first = reservations.confirm_reservation(
        conversation,
        first_intake,
        idempotency_key="round-trip-first-returned",
    )

    assert replayed_first["public_id"] == first["public_id"]
    current = assistance.for_conversation(conversation, kind="wheelchair")
    assert current["reservationPublicId"] == first["public_id"]
    assert current["revision"] == 3
    assert current["status"] == "unacknowledged"
    first_snapshot = assistance.for_reservation(first["public_id"], kind="wheelchair")
    assert first_snapshot["revision"] == 3
    assert first_snapshot["status"] == "unacknowledged"
    second_snapshot = assistance.for_reservation(
        second["public_id"], kind="wheelchair"
    )
    assert second_snapshot["revision"] == 2
    assert second_snapshot["status"] == "acknowledged"

    reservations.confirm_reservation(
        conversation,
        {**base, "trip_date": "2026-09-13"},
        idempotency_key="round-trip-stale-second-replay",
    )
    assert assistance.for_conversation(conversation, kind="wheelchair")[
        "reservationPublicId"
    ] == first["public_id"]


def test_booking_session_generation_blocks_same_date_boarding_inheritance():
    conversation = "conversation-booking-generation-boarding"
    base = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    state_registry.wa_save_booking_state(
        conversation, {}, {"mermaid_session_started_at": "generation-one"}, []
    )
    boarding, _ = assistance.record_boarding_assistance_note(
        conversation,
        note="A guest requested general crew help while boarding.",
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id="generation-one-boarding",
    )
    first = reservations.confirm_reservation(
        conversation,
        {**base, "customer_name": "First Party"},
        idempotency_key="generation-one-confirm",
        assistance_session_owned=True,
    )
    state_registry.wa_save_booking_state(
        conversation, {}, {"mermaid_session_started_at": "generation-two"}, []
    )
    second_intake = {
        **base,
        "adults": 3,
        "customer_name": "Second Party",
    }
    second = reservations.confirm_reservation(
        conversation,
        second_intake,
        idempotency_key="generation-two-confirm",
        assistance_session_owned=True,
    )

    assert assistance.for_reservation(first["public_id"])["id"] == boarding["id"]
    assert assistance.for_reservation(second["public_id"]) is None

    reasserted, _ = assistance.record_boarding_assistance_note(
        conversation,
        note="A guest requested general crew help while boarding.",
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id="generation-two-boarding",
    )
    reservations.confirm_reservation(
        conversation,
        second_intake,
        idempotency_key="generation-two-reasserted",
        assistance_session_owned=True,
    )
    assert assistance.for_reservation(second["public_id"])["id"] == reasserted["id"]
    assert assistance.for_reservation(first["public_id"])["revision"] == 1


@pytest.mark.parametrize(
    ("kind", "note"),
    [
        (
            assistance.KIND_WHEELCHAIR,
            "A guest in this party uses a wheelchair.",
        ),
        (
            assistance.KIND_BOARDING_ASSISTANCE,
            "A guest requested general crew help while boarding.",
        ),
    ],
)
def test_identical_summary_in_new_generation_creates_and_links_new_reservation(
    kind, note
):
    conversation = f"conversation-identical-summary-generation-{kind}"
    recorder = (
        assistance.record_wheelchair_note
        if kind == assistance.KIND_WHEELCHAIR
        else assistance.record_boarding_assistance_note
    )
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    state_registry.wa_save_booking_state(
        conversation, {}, {"mermaid_session_started_at": "generation-one"}, []
    )
    item, _ = recorder(
        conversation,
        note=note,
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id=f"identical-first-{kind}",
    )
    first = reservations.confirm_reservation(
        conversation,
        intake,
        idempotency_key=f"identical-first-confirm-{kind}",
        assistance_session_owned=True,
    )

    state_registry.wa_save_booking_state(
        conversation, {}, {"mermaid_session_started_at": "generation-two"}, []
    )
    reasserted, outcome = recorder(
        conversation,
        note=note,
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id=f"identical-second-{kind}",
    )
    assert outcome == "updated"
    assert reasserted["id"] == item["id"]
    assert reasserted["reservationPublicId"] is None
    second = reservations.confirm_reservation(
        conversation,
        intake,
        idempotency_key=f"identical-second-confirm-{kind}",
        assistance_session_owned=True,
    )

    assert second["public_id"] != first["public_id"]
    assert assistance.for_reservation(first["public_id"], kind=kind)["revision"] == 1
    second_link = assistance.for_reservation(second["public_id"], kind=kind)
    assert second_link["id"] == item["id"]
    assert second_link["revision"] == 2
    assert second_link["reservationPublicId"] == second["public_id"]

    replayed = reservations.confirm_reservation(
        conversation,
        intake,
        idempotency_key=f"identical-second-replay-{kind}",
        assistance_session_owned=True,
    )
    assert replayed["public_id"] == second["public_id"]


def test_embedded_legacy_summary_identity_replays_after_generation_upgrade():
    conversation = "conversation-legacy-summary-generation-replay"
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    legacy = reservations.confirm_reservation(
        conversation, intake, idempotency_key="legacy-generation-first"
    )
    state_registry.wa_save_booking_state(
        conversation,
        {},
        {"mermaid_session_started_at": "post-upgrade-generation"},
        [],
    )

    replayed = reservations.confirm_reservation(
        conversation,
        legacy["intake"],
        idempotency_key="legacy-generation-replay",
        assistance_session_owned=True,
    )

    assert replayed["public_id"] == legacy["public_id"]
    assert len(reservations.list_reservations()) == 1


def test_owned_boarding_assistance_follows_date_correction_and_safe_return():
    conversation = "conversation-owned-boarding-date-correction"
    state_registry.wa_save_booking_state(
        conversation, {}, {"mermaid_session_started_at": "owned-generation"}, []
    )
    boarding, _ = assistance.record_boarding_assistance_note(
        conversation,
        note="A guest requested general crew help while boarding.",
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id="owned-boarding-original",
    )
    base = {
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    first_intake = {**base, "trip_date": "2026-09-06"}
    first = reservations.confirm_reservation(
        conversation,
        first_intake,
        idempotency_key="owned-boarding-first",
        assistance_session_owned=True,
    )
    assistance.acknowledge(
        boarding["id"], expected_revision=1, acknowledged_by="Crew One"
    )
    second_intake = {**base, "trip_date": "2026-09-13"}
    second = reservations.confirm_reservation(
        conversation,
        second_intake,
        idempotency_key="owned-boarding-second",
        assistance_session_owned=True,
    )

    second_snapshot = assistance.for_reservation(
        second["public_id"], kind=assistance.KIND_BOARDING_ASSISTANCE
    )
    assert second_snapshot["tripDate"] == "2026-09-13"
    assert second_snapshot["revision"] == 2
    assert second_snapshot["status"] == "unacknowledged"
    assert assistance.for_reservation(first["public_id"])["revision"] == 1

    assistance.acknowledge(
        boarding["id"], expected_revision=2, acknowledged_by="Crew Two"
    )
    returned = assistance.sync_existing(
        conversation,
        kind=assistance.KIND_BOARDING_ASSISTANCE,
        trip_date="2026-09-06",
        source_message_id="owned-boarding-return",
    )
    assert returned["revision"] == 3
    assert returned["reservationPublicId"] is None
    reservations.confirm_reservation(
        conversation,
        second_intake,
        idempotency_key="owned-boarding-stale-before-return-confirm",
        assistance_session_owned=True,
    )
    pending_return = assistance.for_conversation(
        conversation, kind=assistance.KIND_BOARDING_ASSISTANCE
    )
    assert pending_return["tripDate"] == "2026-09-06"
    assert pending_return["reservationPublicId"] is None
    replayed_first = reservations.confirm_reservation(
        conversation,
        first_intake,
        idempotency_key="owned-boarding-first-returned",
        assistance_session_owned=True,
    )
    assert replayed_first["public_id"] == first["public_id"]
    current = assistance.for_conversation(
        conversation, kind=assistance.KIND_BOARDING_ASSISTANCE
    )
    assert current["reservationPublicId"] == first["public_id"]
    assert current["revision"] == 3
    assert current["status"] == "unacknowledged"
    assert assistance.for_reservation(first["public_id"])["revision"] == 3
    assert assistance.for_reservation(second["public_id"])["revision"] == 2

    reservations.confirm_reservation(
        conversation,
        second_intake,
        idempotency_key="owned-boarding-stale-second-replay",
        assistance_session_owned=True,
    )
    assert assistance.for_conversation(
        conversation, kind=assistance.KIND_BOARDING_ASSISTANCE
    )["reservationPublicId"] == first["public_id"]


def test_legacy_wheelchair_confirmation_is_not_masked_by_existing_boarding_note():
    conversation = "conversation-legacy-wheel-and-boarding"
    boarding, _ = assistance.record_boarding_assistance_note(
        conversation,
        note="A guest requested general crew help while boarding.",
        trip_date="2026-09-06",
        source_message_id="boarding-first",
    )
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
        "accessibility_notes": "A guest in this party uses a wheelchair.",
        "wheelchair_relationship": "unspecified",
    }

    reservation = reservations.confirm_reservation(
        conversation, intake, idempotency_key="legacy-wheel-and-boarding"
    )

    wheelchair = assistance.for_conversation(
        conversation, kind=assistance.KIND_WHEELCHAIR
    )
    assert wheelchair is not None
    assert "accessibility_notes" not in reservation["intake"]
    conn = assistance._conn()
    linked_ids = {
        int(row[0])
        for row in conn.execute(
            "SELECT assistance_id FROM mermaid_crew_assistance_reservations "
            "WHERE reservation_public_id=?",
            (reservation["public_id"],),
        ).fetchall()
    }
    conn.close()
    assert linked_ids == {boarding["id"], wheelchair["id"]}


def test_old_singular_link_schema_migrates_once_and_accepts_both_kinds():
    conversation = "conversation-old-link-schema"
    wheelchair, _ = assistance.record_wheelchair_note(
        conversation,
        note="A guest in this party uses a wheelchair.",
        trip_date="2026-09-06",
        source_message_id="old-schema-wheelchair",
    )
    boarding, _ = assistance.record_boarding_assistance_note(
        conversation,
        note="A guest requested general crew help while boarding.",
        trip_date="2026-09-06",
        source_message_id="old-schema-boarding",
    )
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    public_id = reservations.confirm_reservation(
        conversation, intake, idempotency_key="old-schema-first-confirm"
    )["public_id"]
    conn = sqlite3.connect(state_registry.DB_PATH)
    conn.executescript(
        """
        DROP TABLE mermaid_crew_assistance_reservations;
        CREATE TABLE mermaid_crew_assistance_reservations (
            assistance_id INTEGER NOT NULL,
            tenant_slug TEXT NOT NULL DEFAULT 'mermaid',
            reservation_public_id TEXT NOT NULL,
            customer_name TEXT NOT NULL DEFAULT '',
            note_text TEXT NOT NULL DEFAULT '',
            relationship TEXT NOT NULL DEFAULT '',
            trip_date TEXT,
            status TEXT NOT NULL DEFAULT 'unacknowledged',
            revision INTEGER NOT NULL DEFAULT 1,
            acknowledged_at TEXT,
            acknowledged_by TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (assistance_id, reservation_public_id),
            UNIQUE (tenant_slug, reservation_public_id)
        );
        """
    )
    row = conn.execute(
        "SELECT * FROM mermaid_crew_assistance WHERE id=?", (wheelchair["id"],)
    ).fetchone()
    conn.execute(
        "INSERT INTO mermaid_crew_assistance_reservations "
        "(assistance_id,tenant_slug,reservation_public_id,customer_name,note_text,"
        "relationship,trip_date,status,revision,acknowledged_at,acknowledged_by,created_at) "
        "VALUES (?,'mermaid',?,?,?,?,?,?,?,?,?,?)",
        (
            wheelchair["id"],
            public_id,
            row[3],
            row[5],
            row[6],
            row[7],
            row[9],
            row[10],
            row[13],
            row[14],
            row[15],
        ),
    )
    conn.commit()
    conn.close()

    assert reservations.confirm_reservation(
        conversation, intake, idempotency_key="old-schema-replay"
    )["public_id"] == public_id
    assert reservations.confirm_reservation(
        conversation, intake, idempotency_key="old-schema-second-replay"
    )["public_id"] == public_id

    conn = assistance._conn()
    linked_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT assistance_id FROM mermaid_crew_assistance_reservations "
            "WHERE reservation_public_id=? ORDER BY assistance_id",
            (public_id,),
        ).fetchall()
    ]
    unique_indexes = []
    for index in conn.execute(
        "PRAGMA index_list(mermaid_crew_assistance_reservations)"
    ).fetchall():
        if int(index[2]):
            unique_indexes.append(
                tuple(
                    column[2]
                    for column in conn.execute(
                        f'PRAGMA index_info("{index[1]}")'
                    ).fetchall()
                )
            )
    conn.close()
    assert linked_ids == sorted([wheelchair["id"], boarding["id"]])
    assert ("tenant_slug", "reservation_public_id") not in unique_indexes
    assert ("reservation_public_id", "assistance_id") in unique_indexes


def test_reopened_wheelchair_note_drops_old_pointer_until_new_trip_is_confirmed():
    conversation = "conversation-reopened-new-trip"
    wheelchair, _ = assistance.record_wheelchair_note(
        conversation,
        note="A guest in this party uses a wheelchair.",
        trip_date="2026-09-06",
        source_message_id="old-trip-wheelchair",
    )
    base = {
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    old_reservation = reservations.confirm_reservation(
        conversation,
        {**base, "trip_date": "2026-09-06"},
        idempotency_key="old-trip-confirm",
    )
    assistance.withdraw(conversation, source_message_id="old-trip-withdraw")

    reopened, _ = assistance.record_wheelchair_note(
        conversation,
        note="A guest in this party uses a wheelchair.",
        trip_date="2026-09-13",
        source_message_id="new-trip-wheelchair",
    )

    assert reopened["id"] == wheelchair["id"]
    assert reopened["status"] == "unacknowledged"
    assert reopened["reservationPublicId"] is None
    assert assistance.for_reservation(old_reservation["public_id"])["status"] == (
        "withdrawn"
    )

    new_reservation = reservations.confirm_reservation(
        conversation,
        {**base, "trip_date": "2026-09-13"},
        idempotency_key="new-trip-confirm",
    )
    assert assistance.for_conversation(conversation)["reservationPublicId"] == (
        new_reservation["public_id"]
    )
    assert assistance.for_reservation(old_reservation["public_id"])["status"] == (
        "withdrawn"
    )


def test_new_session_confirmation_does_not_inherit_old_active_assistance():
    conversation = "conversation-stale-assistance-session"
    assistance.record_wheelchair_note(
        conversation,
        note="A guest in this party uses a wheelchair.",
        trip_date="2026-09-06",
        source_message_id="old-session-wheelchair",
    )
    assistance.record_boarding_assistance_note(
        conversation,
        note="A guest requested general crew help while boarding.",
        trip_date="2026-09-06",
        source_message_id="old-session-boarding",
    )
    base = {
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    old_reservation = reservations.confirm_reservation(
        conversation,
        {**base, "trip_date": "2026-09-06"},
        idempotency_key="old-session-confirm",
    )
    state_registry.wa_save_booking_state(
        conversation,
        {},
        {"mermaid_session_started_at": "2026-09-04T12:00:00+00:00"},
        [],
    )

    new_reservation = reservations.confirm_reservation(
        conversation,
        {**base, "trip_date": "2026-09-13"},
        idempotency_key="new-session-confirm",
    )

    assert old_reservation["public_id"] != new_reservation["public_id"]
    assert assistance.for_reservation(new_reservation["public_id"]) is None

    boarding, _ = assistance.record_boarding_assistance_note(
        conversation,
        note="A guest requested general crew help while boarding.",
        trip_date="2026-09-13",
        source_message_id="new-session-boarding",
    )
    replayed = reservations.confirm_reservation(
        conversation,
        {**base, "trip_date": "2026-09-13"},
        idempotency_key="new-session-confirm-replay",
    )

    assert replayed["public_id"] == new_reservation["public_id"]
    assert assistance.for_reservation(new_reservation["public_id"])["id"] == boarding[
        "id"
    ]
    conn = assistance._conn()
    new_kinds = [
        row[0]
        for row in conn.execute(
            "SELECT a.kind FROM mermaid_crew_assistance_reservations link "
            "JOIN mermaid_crew_assistance a ON a.id=link.assistance_id "
            "WHERE link.reservation_public_id=? ORDER BY a.kind",
            (new_reservation["public_id"],),
        ).fetchall()
    ]
    conn.close()
    assert new_kinds == [assistance.KIND_BOARDING_ASSISTANCE]

def test_legacy_wheelchair_intake_is_migrated_before_private_snapshot_is_stripped():
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
        "accessibility_notes": "A guest uses a wheelchair.",
    }

    reservation = reservations.confirm_reservation(
        "conversation-legacy", intake, idempotency_key="legacy-confirm"
    )

    item = assistance.for_conversation("conversation-legacy")
    assert item is not None
    assert item["relationship"] == "unspecified"
    assert item["reservationPublicId"] == reservation["public_id"]
    assert "accessibility_notes" not in reservation["intake"]


def test_non_wheelchair_legacy_accessibility_note_is_not_misclassified():
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
        "accessibility_notes": "Guest travels with an oxygen concentrator.",
    }

    reservation = reservations.confirm_reservation(
        "conversation-non-wheelchair", intake, idempotency_key="non-wheelchair"
    )

    assert assistance.for_conversation("conversation-non-wheelchair") is None
    assert reservation["intake"]["accessibility_notes"] == intake[
        "accessibility_notes"
    ]


def test_one_customer_wheelchair_note_remains_linked_to_multiple_reservations():
    base = {
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
        "accessibility_notes": "A guest in this party uses a wheelchair.",
        "wheelchair_relationship": "unspecified",
    }
    note, _ = assistance.record_wheelchair_note(
        "conversation-two-trips",
        note=base["accessibility_notes"],
        relationship="unspecified",
        trip_date="2026-09-06",
        source_message_id="trip-one-note",
    )
    first = reservations.confirm_reservation(
        "conversation-two-trips",
        {**base, "trip_date": "2026-09-06"},
        idempotency_key="trip-one-confirm",
    )
    assistance.acknowledge(
        note["id"], expected_revision=1, acknowledged_by="Crew-A"
    )
    assistance.sync_existing(
        "conversation-two-trips",
        trip_date="2026-09-13",
        source_message_id="trip-two-date",
    )
    second = reservations.confirm_reservation(
        "conversation-two-trips",
        {**base, "trip_date": "2026-09-13"},
        idempotency_key="trip-two-confirm",
    )

    assert first["public_id"] != second["public_id"]
    first_note = assistance.for_reservation(first["public_id"])
    second_note = assistance.for_reservation(second["public_id"])
    assert first_note["id"] == note["id"]
    assert first_note["tripDate"] == "2026-09-06"
    assert first_note["revision"] == 1
    assert first_note["status"] == "acknowledged"
    assert first_note["acknowledgedBy"] == "Crew-A"
    assert second_note["id"] == note["id"]
    assert second_note["tripDate"] == "2026-09-13"
    assert second_note["revision"] == 2
    assert second_note["status"] == "unacknowledged"
    assert set(
        assistance.for_reservations([first["public_id"], second["public_id"]])
    ) == {first["public_id"], second["public_id"]}

    # Replaying the old confirmation cannot move the queue pointer away from
    # the newer trip or corrupt either frozen reservation snapshot.
    replayed_first = reservations.confirm_reservation(
        "conversation-two-trips",
        {**base, "trip_date": "2026-09-06"},
        idempotency_key="trip-one-replayed-after-two",
    )
    assert replayed_first["public_id"] == first["public_id"]
    assert assistance.for_conversation("conversation-two-trips")[
        "reservationPublicId"
    ] == second["public_id"]
    assert assistance.for_reservation(first["public_id"])["acknowledgedBy"] == "Crew-A"
    assert assistance.for_reservation(second["public_id"])["status"] == "unacknowledged"

    assistance.acknowledge(
        note["id"], expected_revision=2, acknowledged_by="Crew-B"
    )
    assert assistance.for_reservation(first["public_id"])["acknowledgedBy"] == "Crew-A"
    assert assistance.for_reservation(second["public_id"])["acknowledgedBy"] == "Crew-B"


def test_replaying_returned_public_intake_does_not_duplicate_private_reservation():
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
        "accessibility_notes": "A guest uses a wheelchair.",
        "wheelchair_relationship": "unspecified",
    }

    first = reservations.confirm_reservation(
        "conversation-public-replay", intake, idempotency_key="public-first"
    )
    replayed = reservations.confirm_reservation(
        "conversation-public-replay",
        first["intake"],
        idempotency_key="public-second-key",
    )

    assert replayed["public_id"] == first["public_id"]
    assert len(reservations.list_reservations()) == 1


@pytest.mark.parametrize("with_accessibility", [False, True])
def test_pre_upgrade_summary_identity_does_not_create_duplicate_reservation(
    with_accessibility,
):
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    if with_accessibility:
        intake.update(
            accessibility_notes="A guest uses a wheelchair.",
            wheelchair_relationship="unspecified",
        )
    first = reservations.confirm_reservation(
        f"conversation-identity-{with_accessibility}",
        intake,
        idempotency_key=f"identity-first-{with_accessibility}",
    )
    # Simulate the pre-upgrade row shape, which retained the private fields in
    # intake_json while using the legacy summary hash.
    conn = reservations._conn()
    conn.execute(
        "UPDATE mermaid_reservations SET intake_json=? WHERE public_id=?",
        (json.dumps(intake, sort_keys=True), first["public_id"]),
    )
    conn.commit()
    conn.close()

    retried = reservations.confirm_reservation(
        f"conversation-identity-{with_accessibility}",
        intake,
        idempotency_key=f"identity-retry-{with_accessibility}",
    )

    assert retried["public_id"] == first["public_id"]
    assert len(reservations.list_reservations()) == 1
    if with_accessibility:
        assert "accessibility_notes" not in retried["intake"]
        assert "wheelchair_relationship" not in retried["intake"]


def test_invalid_acknowledgement_and_status_are_rejected():
    with pytest.raises(assistance.CrewAssistanceNotFound):
        assistance.acknowledge(999, expected_revision=1, acknowledged_by="Calvin")
    with pytest.raises(assistance.CrewAssistanceError):
        assistance.list_items("pending")


def test_messages_trash_deletes_private_note_with_only_a_fabricated_link():
    item, _ = assistance.record_wheelchair_note(
        "conversation-delete",
        note="A guest uses a wheelchair.",
        customer_name="Synthetic Guest",
        source_message_id="message-delete",
    )
    conn = assistance._conn()
    assistance.link_reservation(
        conn,
        "conversation-delete",
        "mer_still_active",
        idempotency_key="active-link",
    )
    conn.commit()
    conn.close()
    state_registry.dm_store_message(
        "conversation-delete", "whatsapp", "user", "test message"
    )

    deleted = state_registry.wa_delete_conversation("conversation-delete")

    assert deleted >= 1
    assert assistance.for_conversation("conversation-delete") is None
    assert assistance.for_reservation("mer_still_active") is None
    assert assistance.events(item["id"]) == []
    conn = assistance._conn()
    assert conn.execute(
        "SELECT 1 FROM mermaid_crew_assistance_sources WHERE conversation_id=?",
        ("conversation-delete",),
    ).fetchone() is None
    conn.close()


def test_messages_trash_preserves_private_note_owned_by_a_real_reservation():
    conversation = "conversation-delete-real-reservation"
    item, _ = assistance.record_wheelchair_note(
        conversation,
        note="A guest uses a wheelchair.",
        customer_name="Synthetic Guest",
        source_message_id="message-delete-real",
    )
    intake = {
        "trip_date": "2026-09-06",
        "adults": 2,
        "children": 0,
        "infants": 0,
        "customer_name": "Synthetic Guest",
        "contact_phone": "+5999000000",
        "pickup_preference": "pier",
        "language": "en",
        "phase": "summary_confirmed",
    }
    reservation = reservations.confirm_reservation(
        conversation,
        intake,
        idempotency_key="delete-real-reservation",
    )
    state_registry.dm_store_message(conversation, "whatsapp", "user", "test message")

    deleted = state_registry.wa_delete_conversation(conversation)

    assert deleted >= 1
    assert reservations.get_reservation(reservation["public_id"])["public_id"] == reservation[
        "public_id"
    ]
    assert assistance.for_conversation(conversation)["id"] == item["id"]
    assert assistance.for_reservation(reservation["public_id"])["id"] == item["id"]
    assert assistance.events(item["id"])
    conn = assistance._conn()
    assert conn.execute(
        "SELECT 1 FROM mermaid_crew_assistance_sources "
        "WHERE conversation_id=? AND assistance_id=?",
        (conversation, item["id"]),
    ).fetchone() is not None
    conn.close()

    changed_intake = {**intake, "adults": 3}
    later = reservations.confirm_reservation(
        conversation,
        changed_intake,
        idempotency_key="same-date-after-conversation-trash",
    )
    assert later["public_id"] != reservation["public_id"]
    assert assistance.for_reservation(later["public_id"]) is None
    assert assistance.for_reservation(reservation["public_id"])["id"] == item["id"]

    reasserted, _ = assistance.record_wheelchair_note(
        conversation,
        note="A guest uses a wheelchair.",
        trip_date="2026-09-06",
        customer_name="Synthetic Guest",
        source_message_id="message-reassert-after-trash",
    )
    replayed = reservations.confirm_reservation(
        conversation,
        changed_intake,
        idempotency_key="same-date-after-explicit-reassertion",
    )
    assert replayed["public_id"] == later["public_id"]
    assert assistance.for_reservation(later["public_id"])["id"] == reasserted["id"]


def test_generic_tenant_conversation_trash_does_not_apply_mermaid_cleanup(monkeypatch):
    conversation = "conversation-delete-other-tenant"
    item, _ = assistance.record_wheelchair_note(
        conversation,
        note="A guest uses a wheelchair.",
        source_message_id="message-delete-other-tenant",
    )
    state_registry.dm_store_message(conversation, "whatsapp", "user", "test message")
    monkeypatch.setattr(state_registry, "_current_tenant_id", lambda: "other-tenant")

    state_registry.wa_delete_conversation(conversation)

    assert assistance.for_conversation(conversation)["id"] == item["id"]


def test_customer_export_and_delete_include_private_assistance_data(tmp_path):
    phone = "+5999000042"
    item, _ = assistance.record_wheelchair_note(
        phone,
        note="A guest uses a wheelchair.",
        customer_name="Synthetic Guest",
        source_message_id="message-export",
    )
    conn = state_registry._get_conn()
    now = "2026-09-04T12:00:00+00:00"
    customer = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Synthetic Guest", now, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'phone',?,?)",
        (customer, phone, now),
    )
    conn.commit()
    conn.close()

    exported = state_registry.export_all_customer_data(str(tmp_path), "mermaid")
    with open(exported["exportPath"], encoding="utf-8") as handle:
        payload = json.load(handle)
    assert [row["id"] for row in payload["mermaid_crew_assistance"]] == [
        item["id"]
    ]
    assert payload["mermaid_crew_assistance_events"]

    result = state_registry.delete_customer_data(phone, "phone", "delete", True)
    assert result["ok"] is True
    assert assistance.for_conversation(phone) is None
    assert assistance.events(item["id"]) == []


def test_customer_anonymize_withdraws_and_redacts_private_assistance_data():
    phone = "+5999000043"
    item, _ = assistance.record_wheelchair_note(
        phone,
        note="The guest's husband uses a wheelchair.",
        relationship="husband",
        trip_date="2026-09-13",
        customer_name="Synthetic Guest",
        source_message_id="message-anonymize",
    )
    conn = state_registry._get_conn()
    now = "2026-09-04T12:00:00+00:00"
    customer = conn.execute(
        "INSERT INTO customers (display_name,first_seen,last_seen) VALUES (?,?,?)",
        ("Synthetic Guest", now, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO customer_identifiers (customer_id,type,value,first_seen) "
        "VALUES (?,'phone',?,?)",
        (customer, phone, now),
    )
    conn.commit()
    conn.close()

    result = state_registry.delete_customer_data(
        phone, "phone", "anonymize", True
    )
    assert result["ok"] is True
    assert assistance.for_conversation(phone) is None

    conn = state_registry._get_conn()
    row = conn.execute(
        "SELECT conversation_id,customer_name,note_text,relationship,trip_date,"
        "reservation_public_id,status FROM mermaid_crew_assistance WHERE id=?",
        (item["id"],),
    ).fetchone()
    event = conn.execute(
        "SELECT source_message_id,payload_json FROM mermaid_crew_assistance_events "
        "WHERE assistance_id=?",
        (item["id"],),
    ).fetchone()
    conn.close()
    assert row == (
        f"[redacted]:{item['id']}",
        "[redacted]",
        "[redacted]",
        "",
        None,
        None,
        "withdrawn",
    )
    assert event == ("", "{}")
