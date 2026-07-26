"""One-time, non-destructive migration of existing WhatsApp state to follow-ups."""

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone


def _fields(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def migrate(database_path: str) -> tuple[int, int]:
    connection = sqlite3.connect(database_path)
    rows = connection.execute(
        "SELECT phone, fields_json, created_at, last_activity "
        "FROM whatsapp_booking_state ORDER BY created_at"
    ).fetchall()
    inserted = 0
    now = datetime.now(timezone.utc).isoformat()

    with connection:
        for conversation_id, raw_fields, created_at, last_activity in rows:
            fields = _fields(raw_fields)
            display_name = str(fields.get("customer_name") or "").strip()
            if not display_name:
                sender = connection.execute(
                    "SELECT sender_name FROM whatsapp_threads "
                    "WHERE phone = ? AND sender_name != '' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                display_name = str(sender[0]).strip() if sender else ""

            name_parts = display_name.split(maxsplit=1)
            first_name = name_parts[0] if name_parts else ""
            surnames = name_parts[1] if len(name_parts) > 1 else ""
            phone_raw = str(fields.get("phone") or conversation_id or "").strip()
            digits = re.sub(r"[^0-9]", "", phone_raw)
            phone_normalized = f"+{digits}" if digits else ""

            callback_parts = [
                str(fields.get("date") or "").strip(),
                str(fields.get("slot_time") or "").strip(),
            ]
            callback_preference = " ".join(part for part in callback_parts if part)
            visit_reason = str(
                fields.get("special_requests")
                or fields.get("comments")
                or fields.get("service_name")
                or ""
            ).strip()
            status = (
                "ready_to_call"
                if first_name and surnames and phone_raw and callback_preference
                else "collecting"
            )
            cursor = connection.execute(
                "INSERT OR IGNORE INTO follow_up_requests ("
                "conversation_id, channel, first_name, surnames, phone_raw, "
                "phone_normalized, callback_preference, visit_reason, status, "
                "handoff_reason, created_at, updated_at"
                ") VALUES (?, 'whatsapp', ?, ?, ?, ?, ?, ?, ?, "
                "'schedule_callback', ?, ?)",
                (
                    conversation_id,
                    first_name,
                    surnames,
                    phone_raw,
                    phone_normalized,
                    callback_preference,
                    visit_reason,
                    status,
                    created_at or now,
                    last_activity or now,
                ),
            )
            inserted += cursor.rowcount

    total = connection.execute(
        "SELECT COUNT(*) FROM follow_up_requests"
    ).fetchone()[0]
    connection.close()
    return inserted, total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database_path")
    args = parser.parse_args()
    inserted_count, total_count = migrate(args.database_path)
    print(f"inserted={inserted_count} total={total_count}")
