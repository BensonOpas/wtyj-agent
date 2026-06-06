# bluemarlin/agents/social/social_agent.py
# Created: Brief 068
# Last modified: Brief 100
# Purpose: WhatsApp booking orchestrator with escalation — calls marina_agent, validates, holds, confirms, escalates

import random
import re
import string
import time
import json
import uuid
from datetime import datetime, timezone, timedelta
from shared import appointment_detector
from shared import state_registry
from shared import auto_block
from shared import bm_logger
from shared import config_loader
from agents.marina import marina_agent
from agents.marina import gws_calendar
from agents.marina import payment_stub
from agents.marina import sheets_writer


_BOOKING_INTENTS = {"booking", "reschedule"}
_ORDER_INTENTS = {"order"}

_BOOKING_FLAGS_TO_RESET = {
    "hold_created", "booking_confirmed", "booking_ref", "hold_id",
    "payment_id", "payment_link", "payment_status",
    "event_id", "event_link",
    "slot_checked", "slot_available", "spots_remaining", "trip_capacity",
    "awaiting_booking_confirmation",
    "hold_service_key", "hold_date", "hold_slot_time",
    "awaiting_escalation_email", "needs_escalation_email",
    "awaiting_order_confirmation", "order_confirmed",
    "waiting_for_human_order_confirmation", "order_escalation_id",
}

_PERSISTENT_FIELDS = {"customer_name", "phone", "email"}

_MAX_REPLIES_PER_HOUR = 50
_REPLY_WINDOW_SECONDS = 3600
_STALE_CONVERSATION_SECONDS = 86400  # 24 hours — matches wa_get_history window


def _day_matches(day_name, days_available):
    """Check if day_name matches the service's days_available string."""
    if days_available.lower() == "daily":
        return True
    return day_name.lower() in days_available.lower()


def _build_action_context(flags):
    """Build action_context string for the Claude prompt based on flags."""
    if flags.get("awaiting_order_confirmation"):
        return (
            "ACTION: An order summary was sent and the customer was asked "
            "whether everything looks correct. The customer is replying now. "
            "If they confirm with yes, perfect, looks good, let's do it, or "
            "similar, set order_confirmed: true and "
            "awaiting_order_confirmation: false. Reply with this exact message: "
            "\"Perfect 💛 We've received your order.\n\n"
            "We'll give you a call shortly to confirm the details and delivery.\n\n"
            "Thank you for choosing Wibrandt.\" "
            "If they change something, extract the changed fields, set "
            "awaiting_order_confirmation: false, and continue the order flow. "
            "If unclear, ask one short clarification question. Do NOT set "
            "booking_confirmed and do NOT create a booking summary."
        )
    if flags.get("awaiting_booking_confirmation"):
        return (
            "ACTION: A booking summary was sent and the customer was asked if they "
            "want you to check availability. The customer is replying. "
            "Determine if they are: (a) confirming — set booking_confirmed: true, "
            "awaiting_booking_confirmation: false, write a warm confirmation reply "
            "with the exact string [PAYMENT_LINK] where the payment link goes. "
            "Also write reply_hold_failed — an apologetic message if the slot turns "
            "out to be unavailable, without [PAYMENT_LINK]; "
            "(b) changing something — extract new fields, set "
            "awaiting_booking_confirmation: false; "
            "(c) unclear — ask for clarification; "
            "(d) declining or saying no — set awaiting_booking_confirmation: false, "
            "use intent 'inquiry' (not 'booking'), acknowledge gracefully and ask "
            "if they'd like to look at something else. "
            "Do NOT generate a new booking summary."
        )
    return ""


def _is_wibrandt_order_tenant():
    """Keep product-order orchestration scoped to Wibrandt."""
    raw = config_loader.get_raw() or {}
    business = raw.get("business") or {}
    slug = str(raw.get("tenant_slug") or raw.get("slug") or business.get("slug") or "").lower()
    name = str(business.get("name") or "").lower()
    return slug == "wibrandt" or name == "wibrandt"


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _order_quantity(fields):
    return _coerce_int(fields.get("quantity") or fields.get("guests"), 0)


def _order_address(fields):
    return (fields.get("delivery_address") or fields.get("address") or "").strip()


def _order_lines(fields):
    products = fields.get("products") or []
    lines = []
    if isinstance(products, list):
        for item in products:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            qty = _coerce_int(item.get("quantity"), _order_quantity(fields) or 1)
            unit_price = _coerce_float(item.get("unit_price"))
            subtotal = _coerce_float(item.get("subtotal"))
            if subtotal is None and unit_price is not None:
                subtotal = unit_price * qty
            lines.append({
                "name": name,
                "quantity": qty,
                "unit_price": unit_price,
                "subtotal": subtotal,
            })
    if not lines:
        name = (fields.get("product_name") or fields.get("service_name") or "").strip()
        if name:
            qty = _order_quantity(fields) or 1
            unit_price = _coerce_float(fields.get("unit_price"))
            subtotal = _coerce_float(fields.get("subtotal"))
            if subtotal is None and unit_price is not None:
                subtotal = unit_price * qty
            lines.append({
                "name": name,
                "quantity": qty,
                "unit_price": unit_price,
                "subtotal": subtotal,
            })
    return lines


def _has_order_required_fields(fields):
    return bool(_order_lines(fields) and _order_quantity(fields) and _order_address(fields))


def _is_wibrandt_order_like(result, fields, flags):
    if not _is_wibrandt_order_tenant():
        return False
    intents = set(result.get("intents") or [])
    if intents & _ORDER_INTENTS:
        return True
    if flags.get("awaiting_order_confirmation") or flags.get("order_confirmed"):
        return True
    if any(fields.get(k) for k in ("products", "product_name", "quantity",
                                   "delivery_address", "order_total")):
        return True
    return False


def _money(value, currency):
    amount = _coerce_float(value)
    if amount is None:
        return "(not calculated)"
    if float(amount).is_integer():
        display = str(int(amount))
    else:
        display = f"{amount:.2f}"
    return f"{currency} {display}".strip()


def _create_wibrandt_order_escalation(channel, phone, channel_label, fields,
                                      flags, from_name, history, result):
    cname = fields.get("customer_name") or from_name or "Unknown"
    customer_phone = fields.get("phone") or phone
    currency = fields.get("currency") or "ANG"
    lines = _order_lines(fields)
    total = _coerce_float(fields.get("order_total"))
    if total is None:
        line_totals = [line.get("subtotal") for line in lines if line.get("subtotal") is not None]
        total = sum(line_totals) if line_totals else None
    order_payload = {
        "type": "ORDER",
        "state": "WAITING_FOR_HUMAN_ORDER_CONFIRMATION",
        "customer_name": cname,
        "phone": customer_phone,
        "products": lines,
        "delivery_address": _order_address(fields),
        "total": total,
        "currency": currency,
        "comments": fields.get("comments") or fields.get("special_requests") or "",
        "channel": channel,
        "customer_id": phone,
    }
    product_summary = ", ".join(
        f"{line.get('quantity') or 1}x {line.get('name')}" for line in lines
    ) or "order"
    subject = f"[ORDER] {cname} ({channel_label}: {phone}) - {product_summary}"
    chat_lines = []
    for msg in (history or []):
        role = str(msg.get("role", "?")).upper()
        chat_lines.append(f"[{role} | {msg.get('created_at', '')}]")
        chat_lines.append(msg.get("text", ""))
        chat_lines.append("---")
    body = (
        "=== ORDER ===\n"
        "Status: WAITING_FOR_HUMAN_ORDER_CONFIRMATION\n"
        f"Customer: {cname}\n"
        f"Phone: {customer_phone}\n"
        f"Channel: {channel_label}\n"
        f"Delivery address: {_order_address(fields) or '(not provided)'}\n"
        f"Comments: {order_payload['comments'] or '(none)'}\n"
        f"Total: {_money(total, currency)}\n\n"
        "=== PRODUCTS ===\n"
        + "\n".join(
            f"- {line.get('quantity') or 1} x {line.get('name')} "
            f"| unit: {_money(line.get('unit_price'), currency)} "
            f"| subtotal: {_money(line.get('subtotal'), currency)}"
            for line in lines
        )
        + "\n\n=== ORDER PAYLOAD ===\n"
        + json.dumps(order_payload, indent=2, ensure_ascii=False)
        + "\n\n=== CHAT LOG ===\n"
        + ("\n".join(chat_lines) or "(no messages logged)")
        + "\n\n=== HELGA INTERNAL NOTE ===\n"
        + (result.get("internal_note") or "Customer confirmed the order summary.")
    )
    escalation_id = state_registry.create_pending_notification(
        'escalation', channel, phone, cname, subject, body, mode="order")
    flags["waiting_for_human_order_confirmation"] = True
    flags["order_escalation_id"] = escalation_id
    flags["fully_escalated"] = True
    flags["awaiting_order_confirmation"] = False
    flags["order_confirmed"] = False
    state_registry.wa_store_message(
        phone, "system", "ORDER escalation created; waiting for human order confirmation")
    sheets_writer.log_escalation({
        "email": phone,
        "subject": channel_label,
        "customer_name": cname,
        "intent": "order",
        "fields_collected": order_payload,
        "internal_note": "Customer confirmed order summary; operator must call to confirm.",
        "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
    })
    bm_logger.log("wibrandt_order_escalated", phone=phone, escalation_id=escalation_id)
    return escalation_id


def _post_validate(fields, flags, result, service):
    """
    Decide whether to advance booking state to awaiting_booking_confirmation.

    Brief 161: returns (None, should_set_awaiting). Always returns None for
    reply_override — Marina generates all booking-flow replies in the
    customer's language via her prompt (see BOOKING VALIDATION block in
    marina_agent._build_system_prompt). This function is now a pure state
    manager. It still runs the validation CHECKS so that state is never
    advanced to awaiting_booking_confirmation on a past date, wrong day, or
    ambiguous multi-departure, but it never overrides Marina's reply text.
    """
    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("service_name", "date", "guests", "service_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    slots = service.get("slots", [])

    # Day-of-week: do not advance state on wrong day (Marina's reply will
    # have told the customer which days the service runs).
    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = service.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            return None, False
    except ValueError:
        pass

    # Past date: do not advance state on past date.
    try:
        _pv_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        _pv_today = datetime.now(timezone(timedelta(hours=-4))).date()
        if _pv_date_obj < _pv_today:
            return None, False
    except ValueError:
        pass

    # Multi-departure: do not advance until the customer has chosen a slot.
    if len(slots) > 1 and not fields.get("slot_time"):
        return None, False

    # Child pricing: Marina is still gathering ages.
    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    # All checks pass — advance state. Marina has already written the summary
    # in the customer's language.
    return None, True


def _maybe_reset_stale_conversation(last_activity, fields, flags, completed_bookings):
    """Reset booking state if >24h since last activity. Returns True if reset happened."""
    if not last_activity:
        return False
    try:
        last = datetime.fromisoformat(last_activity)
        now = datetime.now(timezone.utc)
        if (now - last).total_seconds() < _STALE_CONVERSATION_SECONDS:
            return False
    except (ValueError, TypeError):
        return False

    # Archive current booking if one exists
    if flags.get("hold_created"):
        archived = {
            "booking_ref": flags.get("booking_ref", ""),
            "service_key": fields.get("service_key", ""),
            "service_name": fields.get("service_name", ""),
            "date": fields.get("date", ""),
            "guests": fields.get("guests", ""),
            "slot_time": fields.get("slot_time", ""),
            "payment_link": flags.get("payment_link", ""),
        }
        completed_bookings.append(archived)

    # Reset fields — keep customer identity
    preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
    fields.clear()
    fields.update(preserved)

    # Reset all booking + escalation + rate-limit flags
    for fk in _BOOKING_FLAGS_TO_RESET:
        flags.pop(fk, None)
    for fk in ("fully_escalated", "awaiting_relay", "relay_token",
               "relay_question", "reply_times", "returning_booking"):
        flags.pop(fk, None)

    return True


def handle_incoming_whatsapp_message(message: dict, channel: str = "whatsapp",
                                     inbound_already_stored: bool = False) -> str:
    """
    Process a WhatsApp message: full booking orchestrator.
    Fetch state + history -> build action_context -> call marina_agent ->
    merge fields/flags -> post-validate -> availability + hold ->
    booking confirmation -> persist state -> return reply.
    """
    phone = message.get("from", "")
    text = message.get("text", "")
    from_name = message.get("from_name", "")

    _channel_label = {"whatsapp": "WhatsApp", "instagram_dm": "Instagram",
                      "facebook_dm": "Facebook", "twitter_dm": "X/Twitter"}.get(channel, channel)

    ignored = state_registry.match_ignored_contact(
        channel=channel,
        sender_id=phone,
        phone=phone,
    )
    if ignored:
        state_registry.record_ignored_contact_event(
            contact_id=ignored.get("id"),
            channel=channel,
            sender_identifier=phone,
        )
        bm_logger.log("ignored_contact_inbound_suppressed",
                      channel=channel,
                      sender=phone[:50],
                      reason="Ignored inbound message because sender is on Excluded Contacts / Ignore List.")
        return ""

    _moderation = auto_block.evaluate_inbound(
        channel=channel,
        user_identifier=phone,
        text=text,
        customer_name=from_name,
    )
    if _moderation.get("action") == "blocked":
        bm_logger.log("whatsapp_auto_blocked", phone=phone[:50],
                      category=_moderation.get("category"))
        return ""
    if _moderation.get("action") == "warn":
        bm_logger.log("whatsapp_auto_block_warning", phone=phone[:50])
        return _moderation.get("reply", "")

    # Get existing booking state
    state = state_registry.wa_get_booking_state(phone)
    fields = state.get("fields", {})
    flags = state.get("flags", {})
    completed_bookings = state.get("completed_bookings", [])
    last_activity = state.get("last_activity")

    # Stale conversation reset — 24h inactivity gap means new conversation
    if _maybe_reset_stale_conversation(last_activity, fields, flags, completed_bookings):
        bm_logger.log("whatsapp_stale_reset", phone=phone)
        state_registry.wa_store_message(phone, "system", "Conversation reset after 24h inactivity")

    # Anti-loop guard — rate limit per phone
    _reply_times = flags.get("reply_times", [])
    _now_ts = int(time.time())
    _reply_times = [t for t in _reply_times if _now_ts - t <= _REPLY_WINDOW_SECONDS]
    flags["reply_times"] = _reply_times
    if len(_reply_times) >= _MAX_REPLIES_PER_HOUR:
        bm_logger.log("whatsapp_rate_limited", phone=phone,
                      count=len(_reply_times))
        state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
        return ""

    # Get conversation history (last 10 messages, 24h window)
    history = state_registry.wa_get_history(phone, limit=10)
    if inbound_already_stored and history:
        # The webhook layer may persist the inbound before model/order
        # processing for reliability. Keep the current inbound out of the
        # prompt history because it is already passed as the active body.
        for idx in range(len(history) - 1, -1, -1):
            if history[idx].get("role") == "user" and history[idx].get("text") == text:
                history.pop(idx)
                break

    # Build from identifier with name if available
    display_name = fields.get("customer_name") or from_name
    from_id = f"{phone} ({display_name})" if display_name else phone

    bm_logger.log("whatsapp_processing", phone=phone, text=text[:100],
                  from_name=from_name)

    def _upsert_appointment_signal(reply_text: str):
        _cname = fields.get("customer_name") or from_name or ""
        appointment_detector.upsert_pending_from_exchange(
            conversation_id=phone,
            channel=channel,
            customer_name=_cname,
            user_text=text,
            assistant_reply=reply_text or "",
            history=history,
        )

    # Brief 166: cross-channel customer lookup. Use a typed identifier so WhatsApp
    # conversation ids don't collide with IG/FB/X DMs.
    from agents.social.whatsapp_client import _is_zernio_conversation_id
    _cust_type = "wa_conversation_id" if _is_zernio_conversation_id(phone) else "phone"
    _cust_row = None
    _cust_file = None
    try:
        _cust_row = state_registry.customer_lookup_or_create(
            _cust_type, phone, display_name=from_name or ""
        )
        _cust_file = state_registry.customer_get_full(_cust_row["id"])
    except Exception as _e:
        bm_logger.log("customer_lookup_failed", phone=phone, error=str(_e))

    # Fully escalated guard — still calls marina_agent (one Claude call), skip booking flow
    if flags.get("fully_escalated"):
        _esc_flags = dict(flags)
        for _rk in ("awaiting_relay", "relay_token", "relay_question", "reply_times"):
            _esc_flags.pop(_rk, None)
        esc_result = marina_agent.process_message(
            from_email=from_id, subject="", body=text,
            thread_fields=fields, thread_flags=_esc_flags,
            channel=channel, messages=history,
            customer_file=_cust_file,
        )
        esc_reply = esc_result.get("reply", "")
        bm_logger.log("whatsapp_escalated_reply", phone=phone,
                      reply_length=len(esc_reply))

        # Brief 184: even in fully-escalated mode, Marina may flag a relay question
        # (e.g. wheelchair accessibility) that the operator needs to answer.
        # semi_escalation and requires_human are TOP-LEVEL keys in the response.
        if esc_result.get("semi_escalation"):
            _relay_q = esc_result.get("relay_question", "(no question captured)")
            _relay_token = uuid.uuid4().hex[:12]
            _cname = fields.get("customer_name") or from_name or "Unknown"
            _ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
            _alert_subject = f"[RELAY-{_relay_token}] {_ref} - {_cname}"
            _alert_body = (
                f"Customer: {_cname} ({_channel_label}: {phone})\n"
                f"Their question: {_relay_q}\n\n"
                f"Booking context:\n"
                f"  Trip: {fields.get('service_key', '')} | "
                f"Date: {fields.get('date', '')} | "
                f"Guests: {fields.get('guests', '')}\n"
                f"  Ref: {_ref}\n\n"
                f"INSTRUCTIONS: Reply to this email with your answer.\n"
                f"Marina will relay it to the customer in her own words."
            )
            state_registry.create_pending_notification(
                'relay', channel, phone, _cname,
                _alert_subject, _alert_body, relay_token=_relay_token)
            flags["awaiting_relay"] = True
            flags["relay_token"] = _relay_token
            flags["relay_question"] = _relay_q
            bm_logger.log("whatsapp_escalated_semi_relay", phone=phone,
                          relay_question=_relay_q, relay_token=_relay_token)
            state_registry.wa_store_message(phone, "system",
                f"Relay question sent to team: {_relay_q}")

        _esc_req_human = esc_result.get("requires_human")
        if _esc_req_human and not esc_result.get("semi_escalation"):
            _cname = fields.get("customer_name") or from_name or "Unknown"
            _ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
            _esc_note = esc_result.get("internal_note", "")
            state_registry.create_pending_notification(
                'escalation', channel, phone, _cname,
                f"[ESCALATION] {_ref} - {_cname} ({_channel_label}: {phone}) - {_esc_note[:200]}",
                f"=== RE-ESCALATION (fully_escalated conversation) ===\n"
                f"Customer: {_cname}\nNew issue: {_esc_note}\n\n"
                f"=== CHAT LOG ===\n" + "\n".join(
                    f"[{m.get('role','?').upper()}] {m.get('text','')}" for m in (history or [])
                ),
                mode="hard")
            bm_logger.log("whatsapp_escalated_re_escalation", phone=phone)

        # Record reply timestamp + persist (early return bypasses end-of-function persistence)
        if esc_reply:
            _upsert_appointment_signal(esc_reply)
            _reply_times = flags.get("reply_times", [])
            _reply_times.append(int(time.time()))
            flags["reply_times"] = _reply_times
        state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
        return esc_reply

    # Brief 188: conversation is being handled by AI → status "pending"
    state_registry.set_conversation_status(phone, "pending", channel)

    # Step 1: Build action context
    action_context = _build_action_context(flags)

    # Filter relay flags + internal state before marina_agent call
    agent_flags = dict(flags)
    for _rk in ("awaiting_relay", "relay_token", "relay_question", "reply_times"):
        agent_flags.pop(_rk, None)

    # Returning customer — booking ref detection
    # Brief 161: require at least one digit so all-caps service words like
    # "SUNSET" or "FRIDAY" don't get misread as booking references.
    _detected_ref = None
    _ref_match = re.search(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b', text)
    if _ref_match:
        _detected_ref = _ref_match.group()
        if not flags.get("booking_ref"):
            _past_booking = state_registry.get_booking(_detected_ref)
            if _past_booking:
                flags["returning_booking"] = _detected_ref
                agent_flags["returning_booking"] = _detected_ref
                for _rbk in ("service_key", "date", "guests", "customer_name", "slot_time"):
                    _rbv = _past_booking.get(_rbk)
                    if _rbv and not fields.get(_rbk):
                        fields[_rbk] = _rbv if not isinstance(_rbv, int) else str(_rbv)
                bm_logger.log("whatsapp_returning_customer", phone=phone, booking_ref=_detected_ref)
            else:
                flags["unknown_ref"] = _detected_ref
                agent_flags["unknown_ref"] = _detected_ref
                bm_logger.log("whatsapp_unknown_ref", phone=phone, ref=_detected_ref)

    # Returning customer — phone-based lookup (cross-thread memory)
    if not _detected_ref and not completed_bookings:
        _phone_bookings = state_registry.get_bookings_by_email(phone)
        if _phone_bookings:
            _eb_lines = []
            for _eb in _phone_bookings[:3]:
                _eb_lines.append(
                    f"  - {_eb['service_key']} on {_eb['date']} for {_eb['guests']} guests "
                    f"(ref: {_eb['booking_ref']})")
            agent_flags["_past_customer_bookings"] = "\n".join(_eb_lines)
            bm_logger.log("whatsapp_returning_by_phone", phone=phone,
                          past_count=len(_phone_bookings))

    # Completed bookings context for multi-service conversations
    if completed_bookings:
        _cb_lines = []
        for _cb in completed_bookings:
            _cb_lines.append(
                f"  - {_cb.get('service_name', _cb.get('service_key', '?'))} on "
                f"{_cb.get('date', '?')} for {_cb.get('guests', '?')} guests "
                f"(ref: {_cb.get('booking_ref', 'N/A')})")
        agent_flags["_completed_bookings_summary"] = "\n".join(_cb_lines)
        _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
        if len(completed_bookings) >= _max_bk and flags.get("hold_created"):
            agent_flags["_max_bookings_reached"] = True

    # Call marina_agent with actual channel
    result = marina_agent.process_message(
        from_email=from_id,
        subject="",
        body=text,
        thread_fields=fields,
        thread_flags=agent_flags,
        action_context=action_context,
        channel=channel,
        messages=history,
        customer_file=_cust_file,
    )

    # Brief 166: record interaction + merge any new identifiers Marina extracted
    if _cust_row and _cust_row.get("id"):
        try:
            state_registry.customer_record_interaction(
                _cust_row["id"], channel, f"{_channel_label}/DM: {text[:80]}"
            )
            _new_fields_for_merge = result.get("fields", {}) or {}
            for _ftype, _fkey in (("email", "email"), ("phone", "phone")):
                _val = _new_fields_for_merge.get(_fkey)
                if _val and str(_val).strip() and str(_val).strip() != phone:
                    state_registry.customer_add_identifier(
                        _cust_row["id"], _ftype, str(_val).strip()
                    )
            # Brief 181: update customer display_name when Marina extracts a
            # different name from the conversation (e.g. customer says "Hi, Mark
            # here" but Zernio sender_name was "Calvin Adamus").
            _extracted_name = (_new_fields_for_merge.get("customer_name") or "").strip()
            if _extracted_name and _extracted_name != (_cust_row.get("display_name") or ""):
                state_registry.customer_update_display_name(_cust_row["id"], _extracted_name)
                _cust_row["display_name"] = _extracted_name
        except Exception as _e:
            bm_logger.log("customer_postprocess_failed", phone=phone, error=str(_e))

    reply = result.get("reply", "")

    if not reply:
        bm_logger.log("whatsapp_empty_reply", phone=phone,
                      intents=result.get("intents", []),
                      confidence=result.get("confidence", ""),
                      internal_note=result.get("internal_note", "")[:200])
        return ""

    # Multi-service: if booking intent + previous booking completed, archive and reset
    if (any(i in _BOOKING_INTENTS for i in result.get("intents", []))
            and flags.get("hold_created")):
        _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
        if len(completed_bookings) < _max_bk:
            archived = {
                "booking_ref": flags.get("booking_ref", ""),
                "service_key": fields.get("service_key", ""),
                "service_name": fields.get("service_name", ""),
                "date": fields.get("date", ""),
                "guests": fields.get("guests", ""),
                "slot_time": fields.get("slot_time", ""),
                "payment_link": flags.get("payment_link", ""),
            }
            completed_bookings.append(archived)
            preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
            fields.clear()
            fields.update(preserved)
            for _fk in _BOOKING_FLAGS_TO_RESET:
                flags.pop(_fk, None)
            bm_logger.log("whatsapp_multi_trip_reset", phone=phone,
                          booking_number=len(completed_bookings))
            state_registry.wa_store_message(phone, "system",
                f"Previous booking archived ({archived.get('service_key', '')} {archived.get('date', '')}). Starting new booking.")

    # Clear one-shot flags after Claude has seen them
    flags.pop("unknown_ref", None)

    # Step 3: Merge fields — overwrite when Claude returns non-empty values
    new_fields = result.get("fields", {}) or {}
    for k, v in new_fields.items():
        if v is not None and v != "":
            fields[k] = v
        elif v == "" and k in fields:
            del fields[k]

    # Step 4: Merge flags — Python manages awaiting_booking_confirmation (set only)
    new_flags = result.get("flags", {}) or {}
    _was_awaiting = flags.get("awaiting_booking_confirmation", False)
    if new_flags.get("awaiting_booking_confirmation"):
        new_flags.pop("awaiting_booking_confirmation")
    flags.update(new_flags)

    # Step 5: Change detection — cancel soft hold if customer changed booking details
    if (_was_awaiting and not flags.get("awaiting_booking_confirmation")
            and not flags.get("booking_confirmed")):
        if flags.get("hold_id"):
            state_registry.cancel_hold(flags["hold_id"])
            _h_svc = flags.pop("hold_service_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_slot_time", "")
            flags.pop("hold_id", None)
            if _h_svc and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        bm_logger.log("whatsapp_hold_cancelled", phone=phone,
                      reason="customer_changed_details")

    reply_text = reply

    # Wibrandt product order flow: confirmed orders are not bookings and do
    # not mean "customer needs reply". Once the customer confirms an order
    # summary, create a dedicated ORDER escalation for the operator to call.
    _skip_booking = False
    _wibrandt_order_like = _is_wibrandt_order_like(result, fields, flags)
    if _wibrandt_order_like:
        if flags.get("order_confirmed") and not flags.get("order_escalation_id"):
            reply_text = (
                "Perfect 💛 We've received your order.\n\n"
                "We'll give you a call shortly to confirm the details and delivery.\n\n"
                "Thank you for choosing Wibrandt."
            )
            _create_wibrandt_order_escalation(
                channel, phone, _channel_label, fields, flags, from_name, history, result)
            _skip_booking = True
        elif _has_order_required_fields(fields) and not flags.get("awaiting_order_confirmation"):
            flags["awaiting_order_confirmation"] = True
            flags.pop("booking_confirmed", None)
            if "look correct" not in reply_text.lower() and "everything correct" not in reply_text.lower():
                reply_text = reply_text.rstrip() + "\n\nDoes everything look correct?"
            _skip_booking = True
        elif result.get("intents") and any(i in _ORDER_INTENTS for i in result.get("intents", [])):
            flags.pop("booking_confirmed", None)
            _skip_booking = True

    # Step 6: Post-validation (booking intents only)
    _pv_service_key = fields.get("service_key", "")
    _pv_service = config_loader.get_service(_pv_service_key) if _pv_service_key else {}
    _run_pv = (not _skip_booking and any(i in _BOOKING_INTENTS for i in result.get("intents", [])))
    # Guard: if customer was responding to a booking summary and didn't change
    # any booking fields, skip post-validate to prevent decline loop
    if _run_pv and _was_awaiting and not flags.get("booking_confirmed"):
        _new_f = result.get("fields", {}) or {}
        if not any(_new_f.get(k) for k in ("service_name", "date", "guests", "service_key", "slot_time")):
            _run_pv = False
    if _run_pv:
        # Brief 161: _post_validate no longer returns reply text — Marina
        # writes all booking-flow replies in the customer's language via her
        # prompt. This step only decides whether to advance state.
        _pv_override, _pv_set_awaiting = _post_validate(fields, flags, result, _pv_service)
        if _pv_set_awaiting:
            flags["awaiting_booking_confirmation"] = True

    _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)

    # Step 7: Availability pre-check + soft hold (SKIP when booking_flow is OFF)
    if (_booking_flow_on
            and flags.get("awaiting_booking_confirmation")
            and not flags.get("slot_checked")):
        _ck_svc = fields.get("service_key", "")
        _ck_deps = config_loader.get_service(_ck_svc).get("slots", []) if _ck_svc else []
        _ck_start = (fields.get("slot_time")
                     or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
        _ck_guests = int(fields.get("guests") or 1)
        _svc_capacity = config_loader.get_service(_ck_svc).get("capacity", 20) if _ck_svc else 20
        if _ck_guests > _svc_capacity:
            # Group exceeds capacity — escalate, don't check availability
            flags["slot_checked"] = True
            flags["slot_available"] = False
            flags["awaiting_booking_confirmation"] = False
            _cname = fields.get("customer_name") or from_name or "Unknown"
            state_registry.create_pending_notification(
                'escalation', channel, phone, _cname,
                f"[LARGE GROUP] {_cname} ({_channel_label}: {phone}) — {_ck_guests} guests exceeds {_svc_capacity} capacity",
                (f"=== LARGE GROUP — EXCEEDS CAPACITY ===\n"
                 f"Customer: {_cname}\nPhone: {phone}\n"
                 f"Service: {fields.get('service_name', _ck_svc)}\n"
                 f"Date: {fields.get('date', '?')}\n"
                 f"Guests: {_ck_guests} (capacity: {_svc_capacity})\n\n"
                 f"Group exceeds standard capacity. Contact customer to discuss options."),
                mode="soft")
            bm_logger.log("whatsapp_large_group_exceeds_capacity", phone=phone,
                          guests=_ck_guests, capacity=_svc_capacity,
                          service_key=_ck_svc)
            # Use Marina's original conversational reply (not the booking summary)
            reply_text = reply
        else:
            avail = gws_calendar.check_availability(
                _ck_svc, fields.get("date", ""), _ck_start, _ck_guests)
            flags["slot_checked"] = True
            flags["slot_available"] = avail.get("available", False)
            flags["spots_remaining"] = avail.get("spots_remaining", 0)
            flags["trip_capacity"] = avail.get("capacity", 0)
            if avail.get("available"):
                hold_id = state_registry.create_soft_hold(
                    _ck_svc,
                    fields.get("date", ""),
                    _ck_start,
                    _ck_guests,
                    avail.get("capacity", 20),
                    customer_name=fields.get("customer_name", ""),
                    customer_email=fields.get("email") or phone,
                )
                if hold_id is not None:
                    flags["hold_id"] = hold_id
                    flags["hold_service_key"] = _ck_svc
                    flags["hold_date"] = fields.get("date", "")
                    flags["hold_slot_time"] = _ck_start
                    bm_logger.log("whatsapp_soft_hold_created", phone=phone,
                                  hold_id=hold_id, service_key=_ck_svc)
                else:
                    # Race: capacity was grabbed between check and insert
                    flags["slot_available"] = False
                    flags["awaiting_booking_confirmation"] = False
                    flags["slot_checked"] = False
                    _unavail_name = _pv_service.get("display_name", _ck_svc)
                    reply_text = (
                        f"Unfortunately the {_unavail_name} is fully booked on that date. "
                        f"Would you like to try a different date?"
                    )
                    bm_logger.log("whatsapp_soft_hold_race", phone=phone, service_key=_ck_svc)
            else:
                flags["awaiting_booking_confirmation"] = False
                flags["slot_checked"] = False
                _unavail_name = _pv_service.get("display_name", _ck_svc)
                reply_text = (
                    f"Unfortunately the {_unavail_name} is fully booked on that date. "
                    f"Would you like to try a different date?"
                )
                bm_logger.log("whatsapp_slot_unavailable", phone=phone, service_key=_ck_svc,
                              spots=avail.get("spots_remaining", 0))

    # Step 7.5: Semi-escalation → create relay (operator notified via email poller)
    if result.get("semi_escalation"):
        relay_question = result.get("relay_question", "(no question captured)")
        # Cancel any soft hold (capacity leak prevention)
        if flags.get("hold_id"):
            state_registry.cancel_hold(flags["hold_id"])
            _h_svc = flags.pop("hold_service_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_slot_time", "")
            flags.pop("hold_id", None)
            if _h_svc and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        flags["awaiting_booking_confirmation"] = False
        # Set relay flags (proper relay bridge, not promote to full)
        relay_token = uuid.uuid4().hex[:12]
        flags["awaiting_relay"] = True
        flags["relay_token"] = relay_token
        flags["relay_question"] = relay_question
        reply_text = result["reply"]
        # Build relay alert for operator
        _ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
        _cname = fields.get("customer_name") or from_name or "Unknown"
        _alert_subject = f"[RELAY-{relay_token}] {_ref} - {_cname}"
        _alert_body = (
            f"Customer: {_cname} ({_channel_label}: {phone})\n"
            f"Their question: {relay_question}\n\n"
            f"Booking context:\n"
            f"  Trip: {fields.get('service_key', '')} | "
            f"Date: {fields.get('date', '')} | "
            f"Guests: {fields.get('guests', '')}\n"
            f"  Ref: {_ref}\n\n"
            f"INSTRUCTIONS: Reply to this email with your answer.\n"
            f"Marina will relay it to the customer in her own words."
        )
        state_registry.create_pending_notification(
            'relay', channel, phone, _cname,
            _alert_subject, _alert_body, relay_token=relay_token)
        sheets_writer.log_escalation({
            "email": phone,
            "subject": _channel_label,
            "customer_name": _cname,
            "intent": "semi_escalation",
            "fields_collected": fields,
            "internal_note": f"Relay question: {relay_question}",
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_semi_escalation", phone=phone,
                      relay_question=relay_question, relay_token=relay_token)
        state_registry.wa_store_message(phone, "system", f"Relay question sent to team: {relay_question}")
        _skip_booking = True

    # Step 7.5: Awaiting escalation email — email provided, now fire escalation
    if flags.get("awaiting_escalation_email") and fields.get("email"):
        flags.pop("awaiting_escalation_email", None)
        flags.pop("needs_escalation_email", None)
        result["requires_human"] = True
        bm_logger.log("whatsapp_escalation_email_received", phone=phone,
                      email=fields.get("email", "")[:50])

    # Step 7.55: Needs escalation email — hold escalation, ask for email
    if not _skip_booking and result.get("flags", {}).get("needs_escalation_email"):
        flags["awaiting_escalation_email"] = True
        reply_text = result["reply"]
        _skip_booking = True

    # Step 7.6: Full escalation — requires_human, holding reply to customer
    if not _skip_booking and result.get("requires_human"):
        # Cancel any soft hold (same pattern as semi-escalation — capacity leak prevention)
        if flags.get("hold_id"):
            state_registry.cancel_hold(flags["hold_id"])
            _h_svc = flags.pop("hold_service_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_slot_time", "")
            flags.pop("hold_id", None)
            if _h_svc and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        flags["fully_escalated"] = True
        flags["awaiting_booking_confirmation"] = False
        reply_text = result["reply"]  # Claude's warm holding reply
        _cname = fields.get("customer_name") or from_name or "Unknown"
        sheets_writer.log_escalation({
            "email": phone,
            "subject": _channel_label,
            "customer_name": _cname,
            "intent": (result.get("intents") or ["unknown"])[0],
            "fields_collected": fields,
            "internal_note": result.get("internal_note", ""),
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_full_escalation", phone=phone,
                      intents=result.get("intents", []))
        _esc_intent = (result.get("intents") or ["unknown"])[0]
        state_registry.wa_store_message(phone, "system", f"Escalated to human: {_esc_intent}")
        # Build escalation alert for operator
        _esc_ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
        _esc_intents = ", ".join(result.get("intents") or ["unknown"])
        _esc_history = state_registry.wa_get_history(phone, limit=20)
        _esc_chat_lines = []
        for _em in _esc_history:
            _esc_chat_lines.append(
                f"[{_em['role'].upper()} | {_em.get('created_at', '')}]")
            _esc_chat_lines.append(_em.get("text", ""))
            _esc_chat_lines.append("---")
        _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
        _esc_note = result.get("internal_note", "").strip()
        _esc_summary = _esc_note if _esc_note else _esc_intents
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"({_channel_label}: {phone}) - {_esc_summary}")
        _customer_email = fields.get("email", "")
        _esc_body = (
            f"=== CUSTOMER ===\n"
            f"{_channel_label}: {phone}\n"
            f"Name: {_cname}\n"
            f"Email: {_customer_email or '(not provided)'}\n\n"
            f"=== CHAT LOG ===\n{_esc_chat_log}\n\n"
            f"=== BOOKING FIELDS ===\n"
            f"{json.dumps(fields, indent=2, ensure_ascii=False)}\n\n"
            f"=== MARINA'S INTERNAL NOTE ===\n"
            f"{result.get('internal_note', '')}"
        )
        state_registry.create_pending_notification(
            'escalation', channel, phone, _cname,
            _esc_subject, _esc_body, mode="hard")
        _skip_booking = True

    # Step 7.8: Booking flow toggle — if OFF, escalate booking intents instead
    if not _skip_booking and not _booking_flow_on:
        if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
            if fields.get("service_name") or fields.get("date") or fields.get("guests"):
                _cname = fields.get("customer_name", phone)
                _customer_email = fields.get("email", "")
                _esc_msgs = state_registry.wa_get_full_history(phone, limit=20)
                _esc_chat_lines = []
                for _em in _esc_msgs:
                    _esc_chat_lines.append(
                        f"[{_em['role'].upper()} | {_em.get('created_at', '')}]")
                    _esc_chat_lines.append(_em.get("text", ""))
                    _esc_chat_lines.append("---")
                _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
                _esc_note = result.get("internal_note", "")
                _esc_subject = (
                    f"[BOOKING REQUEST] {_cname} "
                    f"({_channel_label}: {phone}) - {_esc_note or 'wants to book'}")
                _esc_body = (
                    f"=== BOOKING REQUEST (booking_flow OFF) ===\n\n"
                    f"=== CUSTOMER ===\n"
                    f"{_channel_label}: {phone}\n"
                    f"Name: {_cname}\n"
                    f"Email: {_customer_email or '(not provided)'}\n\n"
                    f"=== COLLECTED FIELDS ===\n"
                    f"{json.dumps(fields, indent=2, ensure_ascii=False)}\n\n"
                    f"=== CHAT LOG ===\n{_esc_chat_log}\n\n"
                    f"=== MARINA'S NOTE ===\n{_esc_note}"
                )
                state_registry.create_pending_notification(
                    'escalation', channel, phone, _cname,
                    _esc_subject, _esc_body, mode="soft")
                bm_logger.log("booking_flow_off_escalated", phone=phone)
                _skip_booking = True

    # Step 8: Booking confirmation flow (skip if escalated)
    if not _skip_booking and any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        if (fields.get("service_name") and fields.get("date")
                and fields.get("guests") and fields.get("service_key")
                and flags.get("booking_confirmed")
                and not flags.get("hold_created")):
            bm_logger.log("whatsapp_booking_attempted", phone=phone,
                          service_key=fields.get("service_key"),
                          date=fields.get("date"), guests=fields.get("guests"))

            # Generate booking_ref + set on soft hold BEFORE manifest creation
            _chars = string.ascii_uppercase + string.digits
            booking_ref = ''.join(random.choices(_chars, k=6))
            flags["booking_ref"] = booking_ref
            if flags.get("hold_id"):
                state_registry.set_booking_ref(flags["hold_id"], booking_ref)

            res = gws_calendar.create_or_update_manifest(fields)
            if not res.get("ok"):
                _manifest_error = str(res.get("error", ""))
                _is_api_error = any(s in _manifest_error for s in (
                    '"code": 404', '"code": 500', '"code": 403', '"code": 401',
                    "'code': 404", "'code': 500", "'code': 403", "'code': 401",
                    'Calendar ID not configured'))
                bm_logger.log("whatsapp_manifest_failed", phone=phone,
                              error=_manifest_error[:200],
                              error_type="api" if _is_api_error else "business")
                if flags.get("hold_id"):
                    state_registry.cancel_hold(flags["hold_id"])
                    _h_svc = flags.pop("hold_service_key", "")
                    _h_date = flags.pop("hold_date", "")
                    _h_dep = flags.pop("hold_slot_time", "")
                    flags.pop("hold_id", None)
                    if _h_svc and _h_date and _h_dep:
                        gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                flags["slot_checked"] = False
                flags["slot_available"] = False
                if _is_api_error:
                    _retry_count = flags.get("manifest_retry_count", 0) + 1
                    flags["manifest_retry_count"] = _retry_count
                    if _retry_count >= 2:
                        _cname = fields.get("customer_name") or from_name or "Unknown"
                        state_registry.create_pending_notification(
                            'escalation', channel, phone, _cname,
                            f"[SYSTEM] Manifest failure for {_cname} ({_channel_label}: {phone})",
                            f"Booking failed {_retry_count} times due to API error.\n"
                            f"Error: {_manifest_error[:300]}\n"
                            f"Fields: {json.dumps(fields, indent=2, ensure_ascii=False)}",
                            mode="hard")
                        bm_logger.log("whatsapp_manifest_escalated", phone=phone,
                                      retry_count=_retry_count)
                    flags["booking_confirmed"] = False
                    flags["awaiting_booking_confirmation"] = True
                reply_text = result.get("reply_hold_failed") or reply_text
                sheets_writer.log_hold_failed({
                    "email": phone, "subject": _channel_label,
                    "service_name": fields.get("service_name"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "error": _manifest_error[:200],
                })
            else:
                flags.pop("manifest_retry_count", None)
                flags["hold_created"] = True
                if flags.get("hold_id"):
                    state_registry.confirm_hold(flags["hold_id"])
                    # Brief 168: set payment window if the client has configured one
                    # AND the service requires payment (timing=upfront/deposit).
                    _raw_for_window = config_loader.get_raw() or {}
                    _pt_for_window = _raw_for_window.get("payment", {}).get("timing", "upfront")
                    _hold_hours = _raw_for_window.get("payment", {}).get("hold_duration_hours")
                    if _pt_for_window in ("upfront", "deposit") and _hold_hours:
                        try:
                            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                            _payment_expires_at = (
                                _dt.now(_tz.utc) + _td(hours=float(_hold_hours))
                            ).isoformat()
                            state_registry.set_payment_window(
                                flags["hold_id"], _payment_expires_at,
                                customer_phone=str(phone or "")
                            )
                            flags["payment_expires_at"] = _payment_expires_at
                        except Exception as _e:
                            bm_logger.log("payment_window_set_failed",
                                          phone=phone, error=str(_e))
                flags["event_id"] = res.get("eventId")
                flags["event_link"] = res.get("htmlLink")
                service_key = fields.get("service_key", "")
                price_usd = (config_loader.get_service(service_key).get("price", 0)
                             if service_key else 0)
                reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)

                # Payment timing: only generate link for upfront/deposit
                _payment_timing = config_loader.get_raw().get("payment", {}).get("timing", "upfront")
                if _payment_timing in ("upfront", "deposit"):
                    pay = payment_stub.generate_payment_link(booking_ref, price_usd)
                    pay_link = f"https://demo.pay/{pay['payment_id']}"
                    flags["payment_id"] = pay.get("payment_id")
                    flags["payment_link"] = pay_link
                    flags["payment_status"] = pay.get("status")
                    reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                else:
                    reply_text = reply_text.replace("[PAYMENT_LINK]", "")
                    flags["payment_status"] = "not_required"
                bm_logger.log("whatsapp_booking_confirmed", phone=phone,
                              booking_ref=booking_ref, service_key=service_key)
                # Brief 163: wording depends on payment state.
                # If payment is required (upfront/deposit), the hold is placed but the booking
                # is NOT yet confirmed — say "Hold placed — awaiting payment" so the dashboard
                # tag stays amber until the payment webhook fires (Brief 168).
                # If no payment is required (timing="none", e.g. restaurant reservations), the
                # hold IS the confirmation — keep the "Booking confirmed" wording.
                if _payment_timing in ("upfront", "deposit"):
                    _system_msg = (f"Hold placed — awaiting payment: "
                                   f"{fields.get('service_name', service_key)}, "
                                   f"{fields.get('date', '')}, "
                                   f"{fields.get('guests', '')} guests (Ref: {booking_ref})")
                else:
                    _system_msg = (f"Booking confirmed: "
                                   f"{fields.get('service_name', service_key)}, "
                                   f"{fields.get('date', '')}, "
                                   f"{fields.get('guests', '')} guests (Ref: {booking_ref})")
                state_registry.wa_store_message(phone, "system", _system_msg)
                sheets_writer.log_hold_created({
                    "booking_ref": booking_ref,
                    "email": phone, "subject": _channel_label,
                    "customer_name": fields.get("customer_name"),
                    "service_name": fields.get("service_name"),
                    "service_key": fields.get("service_key"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "slot_time": fields.get("slot_time"),
                    "phone": phone,
                    "special_requests": fields.get("special_requests"),
                    "total_price": int(fields.get("guests") or 0) * price_usd,
                    "html_link": flags.get("event_link"),
                    "payment_link": flags.get("payment_link"),
                    "payment_status": flags.get("payment_status", ""),
                })
                # Log manifest summary to Sheets
                _m_passengers = state_registry.get_slot_passengers(
                    service_key, fields.get("date", ""), fields.get("slot_time", ""))
                _m_confirmed = sum(1 for p in _m_passengers if p["status"] == "confirmed")
                _m_pending = sum(1 for p in _m_passengers if p["status"] == "soft_hold")
                _m_total_guests = sum(p["guests"] for p in _m_passengers)
                _m_total_revenue = _m_total_guests * price_usd
                _m_capacity = config_loader.get_service(service_key).get("capacity", 20)
                sheets_writer.log_manifest_update({
                    "service_key": service_key,
                    "date": fields.get("date", ""),
                    "slot_time": fields.get("slot_time", ""),
                    "total_guests": _m_total_guests,
                    "capacity": _m_capacity,
                    "confirmed_count": _m_confirmed,
                    "pending_count": _m_pending,
                    "total_revenue": _m_total_revenue,
                    "calendar_link": flags.get("event_link", ""),
                    "booking_ref": booking_ref,
                })
                # Save booking for cross-thread memory
                state_registry.save_booking(
                    booking_ref, fields, flags,
                    customer_email=fields.get("email") or phone,
                )

                # Large group notification — operator review after auto-confirm
                _lg_threshold = config_loader.get_booking_rules().get("group_threshold_requires_human", 15)
                _lg_guests = int(fields.get("guests", 0) or 0)
                if _lg_guests >= _lg_threshold:
                    _lg_ref = flags.get("booking_ref", "NO-REF")
                    _lg_name = fields.get("customer_name", "Unknown")
                    _lg_note = (f"Large group booking: {_lg_guests} guests for "
                                f"{fields.get('service_name', '?')} on {fields.get('date', '?')}. "
                                f"Ref: {_lg_ref}. Auto-confirmed — operator review recommended.")
                    state_registry.create_pending_notification(
                        'escalation', channel, phone, _lg_name,
                        f"[LARGE GROUP] {_lg_ref} - {_lg_name} ({_channel_label}: {phone}) - {_lg_note}",
                        (f"=== LARGE GROUP BOOKING ===\n"
                         f"Ref: {_lg_ref}\nGuests: {_lg_guests}\n"
                         f"Trip: {fields.get('service_name', '?')}\n"
                         f"Date: {fields.get('date', '?')}\n"
                         f"Customer: {_lg_name}\nPhone: {phone}\n"
                         f"Email: {fields.get('email', 'not provided')}\n\n"
                         f"This booking was auto-confirmed. Review and adjust if needed."),
                        mode="soft")
                    state_registry.wa_store_message(phone, "system",
                        f"Large group booking ({_lg_guests} guests) — operator notified for review")
                    bm_logger.log("large_group_booking", phone=phone,
                                  guests=str(_lg_guests), booking_ref=_lg_ref)

    # Step 9: Strip remaining placeholders (safety net)
    reply_text = reply_text.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")

    # Record reply timestamp for anti-loop tracking
    if reply_text:
        _reply_times = flags.get("reply_times", [])
        _reply_times.append(int(time.time()))
        flags["reply_times"] = _reply_times

    # Persist state + log
    _upsert_appointment_signal(reply_text)
    state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
    bm_logger.log("whatsapp_agent_reply", phone=phone,
                  intents=result.get("intents", []), reply_length=len(reply_text))

    return reply_text
