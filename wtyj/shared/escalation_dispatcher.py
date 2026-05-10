"""Brief 235: shared registrant for the Brief 227 escalation summary
dispatcher. Importing this module triggers
`state_registry.set_summary_dispatcher(...)` as a load-time side effect,
so any process that imports it gets the dispatcher live.

The dashboard webhook process imports it via `dashboard/api.py`. The
email poller process imports it directly at the top of
`agents/marina/email_poller.py`. Each process gets its own registration
(globals are per-process; the side effect runs per import in each).
"""
from shared import state_registry
from dashboard import escalation_summary as _esc_summary


def _generate_escalation_summary(escalation_id: int, channel: str,
                                  customer_id: str, customer_name: str) -> dict:
    """Brief 227: dispatcher wrapper. Loads the relevant conversation history
    for this channel, calls the Claude generator, returns the dict (or None).
    Brief 235: extracted from dashboard/api.py to be importable from
    email_poller without pulling in FastAPI."""
    try:
        mode = state_registry.get_active_escalation_mode(customer_id)
    except Exception:
        mode = None

    history = []
    try:
        if channel == "email":
            thread_key = state_registry._find_email_thread_key_for(customer_id)
            if thread_key:
                detail = state_registry.email_get_conversation(thread_key)
                history = detail.get("messages", []) or []
        elif channel in ("instagram", "facebook", "messenger"):
            history = state_registry.dm_get_history(customer_id, channel,
                                                     limit=20)
        else:  # whatsapp + anything else
            history = state_registry.wa_get_full_history(customer_id, limit=20)
    except Exception:
        history = []

    summary_dict = _esc_summary.generate_summary(
        channel=channel,
        customer_id=customer_id,
        customer_name=customer_name,
        mode=mode,
        history=history,
    )

    if summary_dict and history:
        # Brief 239: surface the most recent customer-side message in the
        # summary so the alert email and dashboard can display it verbatim
        # without the operator having to scroll the conversation. Walk the
        # history newest-last and pick the most recent message whose role
        # is customer/user/incoming.
        for _msg in reversed(history):
            _role = (_msg.get("role") or "").lower()
            if _role in ("user", "customer", "incoming"):
                _text = (_msg.get("text") or _msg.get("content")
                         or _msg.get("body") or "").strip()
                if _text:
                    summary_dict["latestCustomerMessage"] = _text
                    break

    # Brief 228: best-effort appointment row write. Only fires when the
    # summary indicates scheduling intent. Failure here never blocks
    # summary persistence.
    if summary_dict:
        try:
            details = (summary_dict.get("extractedDetails") or {})
            if details.get("intent") == "scheduling":
                proposed = details.get("proposedTimes") or []
                topic = details.get("topic") or "Meeting"
                if channel == "email":
                    thread_key = state_registry._find_email_thread_key_for(customer_id)
                    conv_id = f"email::{thread_key}" if thread_key else customer_id
                else:
                    conv_id = customer_id
                status = ("pending_team_confirmation"
                          if proposed else "detected")
                state_registry.appointment_upsert(
                    conversation_id=conv_id,
                    channel=channel,
                    customer_name=customer_name or "",
                    title=topic,
                    proposed_times=proposed,
                    status=status,
                )
        except Exception:
            pass

    return summary_dict


# Side-effect registration: importing this module installs the dispatcher
# in this process's state_registry global. Brief 235.
state_registry.set_summary_dispatcher(_generate_escalation_summary)
