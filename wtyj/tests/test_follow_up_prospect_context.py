import json

from shared import state_registry


def _insert_follow_up(conn, conversation_id: str, updated_at: str) -> int:
    cursor = conn.execute(
        """
        INSERT INTO follow_up_requests (
            conversation_id, channel, first_name, surnames, phone_raw,
            phone_normalized, callback_preference, visit_reason, status,
            handoff_reason, source_message_id, created_at, updated_at
        ) VALUES (?, 'whatsapp', 'Ana', 'García', '+34600111222',
                  '+34600111222', 'por la tarde', 'Ansiedad', 'ready_to_call',
                  '', 'message-1', ?, ?)
        """,
        (conversation_id, updated_at, updated_at),
    )
    return cursor.lastrowid


def _insert_state(conn, conversation_id: str, fields: dict, updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO whatsapp_booking_state (
            phone, fields_json, flags_json, completed_bookings_json,
            last_activity, created_at
        ) VALUES (?, ?, '{}', '[]', ?, ?)
        """,
        (conversation_id, json.dumps(fields), updated_at, updated_at),
    )


def test_follow_up_rows_include_complete_prospect_context(tmp_path, monkeypatch):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    now = "2026-07-27T10:00:00+00:00"
    conn = state_registry._get_conn()
    request_id = _insert_follow_up(conn, "+34600111222", now)
    _insert_state(
        conn,
        "+34600111222",
        {
            "service_name": "Terapia individual",
            "preferred_clinic": "Leganés",
            "appointment_preference": "Viernes por la mañana",
            "date": "2026-08-01",
            "slot_time": "18:00",
        },
        now,
    )
    conn.commit()
    conn.close()

    listed = state_registry.list_follow_up_requests()
    selected = state_registry.get_follow_up_request(request_id)

    assert listed[0]["session_type"] == "Terapia individual"
    assert listed[0]["preferred_clinic"] == "Leganés"
    assert listed[0]["appointment_preference"] == "Viernes por la mañana"
    assert selected["session_type"] == "Terapia individual"
    assert selected["preferred_clinic"] == "Leganés"
    assert selected["appointment_preference"] == "Viernes por la mañana"
    assert selected["callback_preference"] == "por la tarde"
    assert selected["visit_reason"] == "Ansiedad"

    copied = state_registry.update_follow_up_status(request_id, "copied")
    assert copied["status"] == "copied"


def test_follow_up_uses_historical_date_and_slot_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    now = "2026-07-27T11:00:00+00:00"
    conn = state_registry._get_conn()
    _insert_follow_up(conn, "+34600999888", now)
    _insert_state(
        conn,
        "+34600999888",
        {"session_type": "Terapia de pareja", "date": "2026-08-03", "slot_time": "17:30"},
        now,
    )
    conn.commit()
    conn.close()

    prospect = state_registry.list_follow_up_requests()[0]

    assert prospect["session_type"] == "Terapia de pareja"
    assert prospect["appointment_preference"] == "2026-08-03 17:30"
