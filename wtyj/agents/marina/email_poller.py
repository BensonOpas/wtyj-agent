#!/usr/bin/env python3
# bluemarlin/agents/marina/email_poller.py
# Last modified: Brief 077
# Purpose: Core orchestrator. IMAP → marina_agent → calendar → sheets → SMTP
import email, json, time, os, re, uuid, random, string, sys
from datetime import datetime, timezone, timedelta
from email.utils import parseaddr

# Package path setup — add bluemarlin/ root to sys.path
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

from shared import state_registry
from shared import bm_logger
from shared import config_loader
# Brief 235: register the Brief 227 escalation summary dispatcher in this
# process. The side-effect import installs _generate_escalation_summary
# as state_registry._summary_dispatcher so escalations created by the
# email poller get summaries generated (matches the webhook_server
# process which registers the same dispatcher via dashboard.api).
from shared import escalation_dispatcher  # noqa: F401
from agents.marina import marina_agent
from agents.marina import sheets_writer
from agents.marina import gws_calendar
from agents.marina import payment_stub
from agents.social.whatsapp_client import send_whatsapp_message

# Brief 189: adapter layer extracted to email_adapter.py. Re-export for backward
# compat — existing tests and any code that imports these from email_poller
# continue to work unchanged.
from agents.marina.email_adapter import (  # noqa: F401
    log, _decode_subj, sha, normalize_subject,
    get_refresh_token, oauth_token, imap_connect, smtp_send,
    extract_text, strip_quotes, resolve_thread_key, _is_new_email,
    CLIENT_ID, TENANT_ID, EMAIL_ADDR, IMAP_HOST, IMAP_PORT,
    SMTP_HOST, SMTP_PORT, REFRESH_TOKEN_PATH, SESSION_ID,
    _MODULE_DIR, _CONFIG_DIR,
)

MAILBOX = "INBOX"
# Demo-phase value — overridable via env var, default 10s for responsive demo UX.
# Bump back toward 30-60s once running at scale to reduce IMAP/Graph throttling risk.
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))

STATE_DIR = _CONFIG_DIR
THREAD_STATE_PATH = os.path.join(_CONFIG_DIR, "email_thread_state.json")

# Anti-loop: max replies per thread within window
MAX_REPLIES_PER_THREAD = 10
REPLY_WINDOW_SECONDS = 60 * 60

# Per-sender rate limit (cross-thread)
# 20/hr is generous: a real customer doing multi-service + questions tops out at ~10.
# Matches the per-thread limit (10) doubled to allow multi-thread legitimate use.
SENDER_RATE_LIMIT = 20
SENDER_RATE_WINDOW = 3600  # 1 hour, same window as per-thread anti-loop

# Thread cleanup — 30 days covers the longest booking-to-service cycle.
# Booking data survives in SQLite bookings table; this only prunes conversation state.
THREAD_RETENTION_DAYS = 30
ARCHIVE_PATH = os.path.join(_CONFIG_DIR, "archived_threads.jsonl")
HEARTBEAT_PATH = os.path.join(_CONFIG_DIR, "heartbeat.txt")

# Error alerting — 3 consecutive errors ≈ 30 seconds of failures (3 × 10s poll at default).
# One-off exceptions are normal (network hiccup); sustained failure warrants alert.
_ERROR_ALERT_THRESHOLD = 3
# Brief 179: forced process exit after sustained failure (~5 min with exponential backoff).
# Supervisord restarts the process fresh (new IMAP connection, new OAuth token, clean state).
_ERROR_EXIT_THRESHOLD = 30
# Brief 182: reconnect every 45 min to refresh the OAuth token (expires at 60 min).
_TOKEN_REFRESH_SECONDS = 2700

# Intents that activate the Python booking validation and hold-creation flow.
# "reschedule" is included because mid-thread date/time changes are booking
# modifications that need the same validation (day-of-week, departure, summary).
_BOOKING_INTENTS = {"booking", "reschedule"}

# System/automated email prefixes to skip (never reply to these)
_SYSTEM_EMAIL_PREFIXES = (
    "noreply", "no-reply", "no_reply", "do-not-reply", "donotreply",
    "mailer-daemon@", "postmaster@", "bounce@", "dmarc",
)


def _business_sender_emails() -> set:
    """Brief 164: return all business-owned email addresses (lowercased) that
    should never be treated as customer senders. Inbound messages from these
    addresses are skipped unless they match a relay/escalation reply subject.

    Pulls from client.json business.email, business.support_email,
    business.booking_email, business.demo_support_email. Deduplicates and
    lowercases. Empty/None values are filtered out.
    """
    biz = config_loader.get_business()
    candidates = (
        biz.get("email"),
        biz.get("support_email"),
        biz.get("booking_email"),
        biz.get("demo_support_email"),
    )
    return {e.strip().lower() for e in candidates if e and isinstance(e, str) and e.strip()}


# ========= HELPERS =========

# _decode_subj, log — moved to email_adapter.py (Brief 189)

def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default

def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


# sha, normalize_subject — moved to email_adapter.py (Brief 189)

def _un_archive_thread_if_deleted(th: dict) -> bool:
    """Brief 232: when a fresh inbound message arrives on a thread that was
    previously archived (flags.deleted=true via Brief 218's dashboard delete
    button), pop the flag so email_list_conversations stops filtering it out.
    Returns True if the flag was cleared (i.e., this thread was un-archived),
    False otherwise.

    Caller must have already short-circuited blocked conversations — block
    always wins per SR's spec (task 93328e8039e1). This function is
    block-agnostic; it only handles the deleted-flag transition.
    """
    flags = th.setdefault("flags", {})
    if flags.get("deleted"):
        flags.pop("deleted", None)
        return True
    return False


def _cleanup_stale_data(state, now):
    """Prune threads >30d old (no active hold, no pending relay) and trim processed_hashes.

    Brief 162: defensive guards against the class of bug where an early-return
    code path forgets to set last_activity. A missing or zero last_activity
    is now treated as "don't know, don't archive" rather than "ancient, archive
    immediately". Also never archive a thread with awaiting_relay=True — that
    would destroy the relay token lookup and silently drop the operator's reply.
    """
    cutoff = now - (THREAD_RETENTION_DAYS * 86400)
    threads = state.get("threads", {})
    to_delete = []
    for tk, th in threads.items():
        last_raw = th.get("last_activity") or 0
        flags = th.get("flags", {})
        # Brief 162: skip if any protection flag is set
        if flags.get("hold_created"):
            continue
        if flags.get("awaiting_relay"):
            continue
        # Brief 162: missing or zero last_activity => unknown, don't archive
        if not last_raw:
            continue
        # Brief 231: dashboard write paths (email_append_assistant_message,
        # email_mark_deleted) store last_activity as an ISO 8601 string;
        # the legacy email_poller paths store a numeric epoch. Accept both.
        # Malformed strings fall through to "don't archive" per Brief 162's
        # defensive principle (treat unknown as unknown, not as ancient).
        if isinstance(last_raw, str):
            try:
                last = datetime.fromisoformat(last_raw).timestamp()
            except (ValueError, TypeError):
                continue
        else:
            last = last_raw
        if last < cutoff:
            to_delete.append(tk)
    if to_delete:
        with open(ARCHIVE_PATH, "a", encoding="utf-8") as f:
            for tk in to_delete:
                f.write(json.dumps({"archived_at": now, "thread_key": tk, "data": threads[tk]}, ensure_ascii=False) + "\n")
                del threads[tk]
        log(f"Archived {len(to_delete)} stale threads (>{THREAD_RETENTION_DAYS}d)")
    # Prune processed_hashes by count (keep last 5000)
    try:
        conn = state_registry._get_conn()
        count = conn.execute("SELECT count(*) FROM processed_hashes").fetchone()[0]
        if count > 5000:
            conn.execute("DELETE FROM processed_hashes WHERE rowid NOT IN (SELECT rowid FROM processed_hashes ORDER BY rowid DESC LIMIT 5000)")
            conn.commit()
            log(f"Pruned processed_hashes: {count} -> 5000")
        conn.close()
    except Exception:
        pass
    # Prune sender_rates
    sr = state.get("sender_rates", {})
    for em in list(sr.keys()):
        sr[em] = [t for t in sr[em] if now - t <= SENDER_RATE_WINDOW]
        if not sr[em]:
            del sr[em]


# get_refresh_token, oauth_token, imap_connect, smtp_send,
# extract_text, strip_quotes, resolve_thread_key, _is_new_email
# — moved to email_adapter.py (Brief 189)


_FRESH_THREAD = {
    "fields": {},
    "flags": {},
    "last_customer_hash": "",
    "reply_times": [],
    "messages": [],
}


def _maybe_reset_stale_thread(msg, thread_key: str, th: dict, threads: dict, now: int) -> dict:
    """If msg is a new email hitting a stale (>24h) existing thread, return a fresh thread dict.
    Otherwise return th unchanged."""
    if not _is_new_email(msg):
        return th
    if thread_key not in threads:
        return th
    _last_activity = th.get("last_activity", 0)
    _last_reply = max(th.get("reply_times", [0]) or [0])
    _last_seen = max(_last_activity, _last_reply)
    _age_hours = (now - _last_seen) / 3600 if _last_seen else 999
    if _age_hours > 24:
        log(f"Stale thread reset: {thread_key} (last activity {_age_hours:.0f}h ago)")
        return dict(_FRESH_THREAD, messages=[], reply_times=[])
    return th


def _detect_booking_ref(body: str) -> "str | None":
    """Extract a 6-char alphanumeric booking reference from message body. Returns ref or None."""
    # Brief 161: require at least one digit so all-caps service words like
    # "SUNSET" or "FRIDAY" don't get misread as booking references. Defensive
    # symmetry with social_agent.py — the email path's caller already guards
    # with state_registry.get_booking, but we keep the two regexes aligned.
    match = re.search(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{6}\b', body)
    if match:
        # Verify it's a real booking ref, not a random 6-char string
        candidate = match.group()
        if state_registry.get_booking(candidate):
            return candidate
    return None


def _resolve_booking_ref(th: dict) -> str:
    """Get the best available booking ref from thread flags.
    Priority: booking_ref (active booking) > returning_booking (past ref) > NO-REF.
    """
    return th["flags"].get("booking_ref") or th["flags"].get("returning_booking") or "NO-REF"


# Booking-related flags that get reset between bookings in the same thread
_BOOKING_FLAGS_TO_RESET = {
    "hold_created", "booking_confirmed", "booking_ref", "hold_id",
    "payment_id", "payment_link", "payment_status",
    "event_id", "event_link",
    "slot_checked", "slot_available", "spots_remaining", "trip_capacity",
    "awaiting_booking_confirmation",
    "hold_service_key", "hold_date", "hold_slot_time",
}

# Fields to preserve across bookings (customer identity)
_PERSISTENT_FIELDS = {"customer_name", "phone"}


def _maybe_reset_for_new_booking(th: dict) -> bool:
    """If a booking was just completed (hold_created=True), archive it and reset
    fields/flags for a fresh booking intake. Returns True if reset happened."""
    if not th.get("flags", {}).get("hold_created"):
        return False

    max_bookings = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
    completed = th.get("completed_bookings", [])
    if len(completed) >= max_bookings:
        return False  # at limit — don't reset, Marina will decline

    # Archive current booking
    fields = th.get("fields", {})
    flags = th.get("flags", {})
    archived = {
        "booking_ref": flags.get("booking_ref", ""),
        "service_key": fields.get("service_key", ""),
        "service_name": fields.get("service_name", ""),
        "date": fields.get("date", ""),
        "guests": fields.get("guests", ""),
        "slot_time": fields.get("slot_time", ""),
        "payment_link": flags.get("payment_link", ""),
    }
    completed.append(archived)
    th["completed_bookings"] = completed

    # Reset fields — keep customer identity
    preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
    th["fields"] = preserved

    # Reset booking flags
    for flag_key in _BOOKING_FLAGS_TO_RESET:
        th["flags"].pop(flag_key, None)

    return True


# ========= BOOKING VALIDATION HELPERS =========
def _day_matches(day_name, days_available):
    """Check if day_name matches the service's days_available string."""
    if days_available.lower() == "daily":
        return True
    return day_name.lower() in days_available.lower()


def _should_skip_marina_for_mute(from_email: str) -> bool:
    """Brief 213: testable wrapper around the per-conversation mute check
    used inside the for-uid loop. Returns True when this email's
    conversation has been muted via operator takeover; the loop should
    log + persist + mark seen + continue without calling marina_agent."""
    return state_registry.get_ai_muted(from_email or "")


def _build_action_context(th):
    """Build action_context string for the Claude prompt based on thread state."""
    flags = th.get("flags", {})
    if flags.get("awaiting_booking_confirmation"):
        return (
            "ACTION: A booking summary was sent. The customer is replying. "
            "Determine if they are: (a) confirming — set booking_confirmed: true, "
            "awaiting_booking_confirmation: false, write a warm celebratory reply "
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


def _post_validate(th, result, service):
    """
    Decide whether to advance booking state to awaiting_booking_confirmation.

    Brief 161: returns (None, should_set_awaiting). Always returns None for
    reply_override — Marina generates all booking-flow replies in the
    customer's language via her prompt (see BOOKING VALIDATION block in
    marina_agent._build_system_prompt). This function is now a pure state
    manager.
    """
    fields = th.get("fields", {})
    flags = th.get("flags", {})

    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("service_name", "date", "guests", "service_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    slots = service.get("slots", [])

    # Day-of-week: do not advance state on wrong day.
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

    return None, True


# ========= MAIN LOOP =========
def main():
    # Email-disabled path for clients that don't use email.
    # Exit 0 cleanly; supervisord is configured not to restart on clean exits.
    # Brief 204: also accept EMAIL_PASSWORD as a valid auth signal (Gmail app
    # password mode). Disabled iff EMAIL_ADDRESS empty, OR neither auth method
    # is configured (no refresh_token AND no app password).
    _has_password = bool(os.environ.get("EMAIL_PASSWORD", ""))
    _has_refresh_token = os.path.exists(REFRESH_TOKEN_PATH)
    if not EMAIL_ADDR or (not _has_refresh_token and not _has_password):
        log(f"Email polling disabled for this client "
            f"(EMAIL_ADDRESS={'set' if EMAIL_ADDR else 'empty'}, "
            f"refresh_token={'present' if _has_refresh_token else 'missing'}, "
            f"app_password={'set' if _has_password else 'empty'}). "
            f"Exiting cleanly.")
        return
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")
    demo_support_email = (
        config_loader.get_business().get("support_email")
        or config_loader.get_business().get("demo_support_email")
        or ""
    )

    state = load_json(THREAD_STATE_PATH, {"threads": {}, "message_id_index": {}})
    state.setdefault("message_id_index", {})
    _consecutive_errors = 0
    _error_alert_sent = False
    im = None  # Brief 182: persistent connection, reconnect when None
    _last_connect = 0

    while True:
        try:
            now = time.time()

            # Brief 182: reconnect if needed (first run, error recovery, or token refresh)
            if im is None or (now - _last_connect > _TOKEN_REFRESH_SECONDS):
                if im is not None:
                    try:
                        im.logout()
                    except Exception:
                        pass
                im = imap_connect()
                im.select(MAILBOX)
                _last_connect = now
                log(f"IMAP connected (token refresh in {_TOKEN_REFRESH_SECONDS}s)")
            else:
                # Brief 182: keepalive — cheap NOOP to prevent server timeout
                im.noop()

            _cleanup_stale_data(state, int(time.time()))

            typ, data = im.uid("search", None, "UNSEEN")
            uids = data[0].split() if data and data[0] else []

            for uid in uids:
                now = int(time.time())
                # fetch full message
                typ, msg_data = im.uid("fetch", uid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_name, from_email = parseaddr(msg.get("From", ""))
                subj = _decode_subj(msg.get("Subject", ""))
                body_raw = extract_text(msg)
                body = strip_quotes(body_raw)

                # Skip system/automated emails (noreply, mailer-daemon, etc.)
                if any(from_email.lower().startswith(p) for p in _SYSTEM_EMAIL_PREFIXES):
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Skipped system email from {from_email}")
                    continue

                # Brief 164: skip inbound emails whose sender is a business-owned address
                # (operator forwards, reply-all on escalation alerts, test emails from
                # the operator's own inbox). The existing [ESCALATION] / [RELAY-] subject
                # checks below handle the legitimate operator-reply flow; everything else
                # from a business sender is noise that must not be processed as a customer
                # message — doing so pollutes the bookings DB with fake "returning customer"
                # records (see Lucia SU0AHF 2026-04-08 incident).
                _business_senders = _business_sender_emails()
                if from_email.lower() in _business_senders:
                    _is_relay = "[RELAY-" in subj
                    _is_escalation = "[ESCALATION]" in subj
                    if not (_is_relay or _is_escalation):
                        im.uid("store", uid, "+FLAGS", r"(\Seen)")
                        log(f"Skipped business-sender email from {from_email} (subject: {subj[:60]}) — not a customer message")
                        continue

                # Per-sender rate limit (cross-thread)
                _sr = state.setdefault("sender_rates", {})
                _sr_times = _sr.get(from_email.lower(), [])
                _sr_times = [t for t in _sr_times if now - t <= SENDER_RATE_WINDOW]
                if len(_sr_times) >= SENDER_RATE_LIMIT:
                    log(f"Sender rate limit hit for {from_email}: {len(_sr_times)} emails in window")
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    _sr[from_email.lower()] = _sr_times
                    save_json(THREAD_STATE_PATH, state)
                    continue
                _sr_times.append(now)
                _sr[from_email.lower()] = _sr_times

                # ---- BM-003: Single-shot duplicate prevention (reply only once) ----
                content_fingerprint = f"{from_email.strip().lower()}|{normalize_subject(subj).strip().lower()}|{body.strip()}"
                if state_registry.has_been_processed(content_fingerprint):
                    log("BM-003: Duplicate detected (already handled) -> skip ALL actions, mark Seen.")
                    im.uid("store", uid, "+FLAGS", r"(\\Seen)")
                    continue

                # Mark as processed BEFORE side effects to guarantee idempotency under retries
                state_registry.mark_as_processed(content_fingerprint)
                # ---- end BM-003 ----

                mid_index = state.setdefault("message_id_index", {})
                thread_key = resolve_thread_key(msg, from_email, subj, mid_index)
                msg_id = (msg.get("Message-ID") or "").strip()
                if msg_id:
                    mid_index[msg_id] = thread_key

                log(f"Processed UNSEEN from {from_name} <{from_email}> | {subj}")
                log(f"ThreadKey: {thread_key}")

                now = int(time.time())
                threads = state["threads"]
                th = threads.get(thread_key, {
                    "fields": {},
                    "flags": {},
                    "last_customer_hash": "",
                    "reply_times": [],
                    "messages": []
                })
                th = _maybe_reset_stale_thread(msg, thread_key, th, threads, now)

                # Deduplicate identical customer content
                customer_hash = sha((from_email.lower() + "|" + normalize_subject(subj).lower() + "|" + body.strip()))
                if th.get("last_customer_hash") == customer_hash:
                    log("Duplicate customer content -> skip reply, mark Seen.")
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["last_activity"] = now  # Brief 162: prevent premature archive
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Anti-loop guard
                th["reply_times"] = [t for t in th.get("reply_times", []) if now - t <= REPLY_WINDOW_SECONDS]
                if len(th["reply_times"]) >= MAX_REPLIES_PER_THREAD:
                    log("Anti-loop guard tripped -> SAFE stop reply, mark Seen.")
                    stop_msg = (
                        "Hi,\n\n"
                        "I want to make sure I help correctly. To avoid confusion over email threads, "
                        "please reply with these 3 items in a single message:\n"
                        "1) Experience (Klein Curaçao / Sunset Cruise / West Coast Beach / Snorkeling / Jet Ski)\n"
                        "2) Date\n"
                        "3) Number of guests\n\n"
                        "Warm regards,\nMarina\n"
                    )
                    smtp_send(from_email, "Re: " + subj, stop_msg,
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    th["last_activity"] = now  # Brief 162: prevent premature archive
                    threads[thread_key] = th
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Drop operator replies to [ESCALATION] alerts — escalation is one-way
                if from_email.lower() == demo_support_email.lower() and "[ESCALATION]" in subj:
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    log(f"Dropped escalation reply from {from_email} — one-way flow")
                    continue

                # [RELAY] inbound from human team — reformulate and forward to original customer
                if from_email.lower() == demo_support_email.lower() and "[RELAY-" in subj:
                    token_match = re.search(r'\[RELAY-([a-f0-9]{12})\]', subj)
                    relay_token_in = token_match.group(1) if token_match else None
                    customer_thread_key = None
                    customer_th = None
                    for tk, t in state["threads"].items():
                        stored_token = t.get("flags", {}).get("relay_token")
                        if (t.get("flags", {}).get("awaiting_relay")
                                and relay_token_in
                                and stored_token == relay_token_in):
                            customer_thread_key = tk
                            customer_th = t
                            break
                    if customer_th is None:
                        # Check WhatsApp relay
                        _wa_relay = state_registry.get_relay_by_token(relay_token_in)
                        if _wa_relay and _wa_relay["channel"] == "whatsapp":
                            _wa_phone = _wa_relay["customer_id"]
                            _wa_state = state_registry.wa_get_booking_state(_wa_phone)
                            _wa_fields = _wa_state.get("fields", {})
                            _wa_flags = _wa_state.get("flags", {})
                            _wa_history = state_registry.wa_get_history(_wa_phone, limit=10)
                            _wa_agent_flags = dict(_wa_flags)
                            for _rk in ("relay_token", "reply_times"):
                                _wa_agent_flags.pop(_rk, None)
                            relay_result = marina_agent.process_message(
                                _wa_phone, "", body,
                                _wa_fields, _wa_agent_flags,
                                channel="whatsapp", messages=_wa_history,
                            )
                            relay_reply = relay_result.get("reply", "")
                            if relay_reply:
                                send_whatsapp_message(_wa_phone, relay_reply)
                                state_registry.wa_store_message(
                                    _wa_phone, "assistant", relay_reply)
                                log(f"RELAY: WhatsApp relay sent to {_wa_phone}")
                            _wa_flags.pop("awaiting_relay", None)
                            _wa_flags.pop("relay_token", None)
                            _wa_flags.pop("relay_question", None)
                            state_registry.wa_save_booking_state(
                                _wa_phone, _wa_fields, _wa_flags,
                                _wa_state.get("completed_bookings", []))
                            state_registry.update_notification_status(
                                _wa_relay["id"], "replied")
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            save_json(THREAD_STATE_PATH, state)
                            continue
                        log(f"RELAY: no pending relay for token={relay_token_in} — skipping (may be already replied)")
                        im.uid("store", uid, "+FLAGS", r"(\Seen)")
                        save_json(THREAD_STATE_PATH, state)
                        continue
                    relay_result = marina_agent.process_message(
                        customer_th["flags"].get("relay_customer_email", ""),
                        customer_th["flags"].get("relay_reply_subject", "Re: " + subj),
                        body,
                        customer_th.get("fields", {}),
                        customer_th.get("flags", {}),
                    )
                    relay_reply = relay_result.get("reply", "")
                    relay_dest = customer_th["flags"].get("relay_customer_email", "")
                    if relay_reply and relay_dest:
                        try:
                            smtp_send(
                                relay_dest,
                                customer_th["flags"].get("relay_reply_subject", "Re: " + subj),
                                relay_reply,
                            )
                            customer_th.setdefault("messages", [])
                            customer_th["messages"].append({
                                "role": "marina",
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "body": relay_reply,
                            })
                            log(f"RELAY: reformulated and sent to {relay_dest}")
                        except Exception as _relay_send_err:
                            log(f"RELAY: send to customer failed: {_relay_send_err}")
                    elif not relay_dest:
                        log(f"RELAY: relay_customer_email missing on thread {customer_thread_key} — skipping send")
                    customer_th["flags"]["awaiting_relay"] = False
                    customer_th["flags"].pop("relay_question", None)
                    customer_th["flags"].pop("relay_token", None)
                    customer_th["last_activity"] = now  # Brief 162: prevent premature archive
                    state["threads"][customer_thread_key] = customer_th
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Brief 220: per-conversation runtime block (email path).
                # from_email is the conversation_id for email channel.
                # Drop BEFORE the th["messages"].append so the operator
                # never sees this message in the inbox. Mark IMAP as seen
                # so the poller doesn't loop on it.
                if state_registry.get_blocked(from_email):
                    log(f"email_blocked_conversation from={from_email[:50]}")
                    th["last_activity"] = now
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    continue

                # Brief 232: archive auto-restore. If this thread was
                # archived (flags.deleted=true via dashboard delete button,
                # Brief 218), a fresh inbound message from the customer
                # restores it to active. Block check above has already
                # short-circuited blocked conversations, so this only runs
                # on non-blocked threads — block always wins per SR's spec.
                if _un_archive_thread_if_deleted(th):
                    log(f"email_thread_restored from={from_email[:50]} thread={thread_key[:60]}")

                # Append inbound message to chat log
                th.setdefault("messages", [])
                th["messages"].append({
                    "role": "customer",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                })

                # Brief 213: ai_muted gate. Inbound is now in th["messages"]
                # so the operator sees the message; we skip Marina's reply
                # (skips both fully_escalated and the normal Marina paths).
                if _should_skip_marina_for_mute(from_email):
                    log(f"email_ai_muted from={from_email[:40]} subj={subj[:40]}")
                    th["last_activity"] = now
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    continue

                # Fully escalated guard — still calls marina_agent (one Claude call), skip booking flow
                if th["flags"].get("fully_escalated"):
                    _esc_flags = dict(th.get("flags", {}))
                    for _rk in ("awaiting_relay", "relay_token", "relay_question",
                                "relay_customer_email", "relay_reply_subject"):
                        _esc_flags.pop(_rk, None)
                    result = marina_agent.process_message(
                        from_email, subj, body,
                        th.get("fields", {}), _esc_flags
                    )

                    # Brief 192: even in fully-escalated mode, Marina may flag
                    # a relay question or re-escalation (same fix as Brief 184
                    # for social_agent.py).
                    if result.get("semi_escalation"):
                        _relay_q = result.get("relay_question", "(no question captured)")
                        _relay_token = uuid.uuid4().hex[:12]
                        _cname = th["fields"].get("customer_name") or from_email
                        _ref = _resolve_booking_ref(th)
                        th["flags"]["awaiting_relay"] = True
                        th["flags"]["relay_token"] = _relay_token
                        th["flags"]["relay_question"] = _relay_q
                        th["flags"]["relay_customer_email"] = from_email
                        th["flags"]["relay_reply_subject"] = "Re: " + subj
                        _relay_alert = (
                            f"Customer: {_cname} <{from_email}>\n"
                            f"Their question: {_relay_q}\n\n"
                            f"Booking context:\n"
                            f"  Trip: {th['fields'].get('service_key', '')} | "
                            f"Date: {th['fields'].get('date', '')} | "
                            f"Guests: {th['fields'].get('guests', '')}\n"
                            f"  Ref: {_ref}\n\n"
                            f"INSTRUCTIONS: Reply to this email with your answer.\n"
                            f"Marina will relay it to the customer in her own words."
                        )
                        state_registry.create_pending_notification(
                            'relay', 'email', from_email, _cname,
                            f"[RELAY-{_relay_token}] {_ref} - {_cname}",
                            _relay_alert, relay_token=_relay_token)
                        log(f"Escalated semi-relay: {from_email} re: {_relay_q[:60]}")

                    if result.get("requires_human") and not result.get("semi_escalation"):
                        _cname = th["fields"].get("customer_name") or from_email
                        _ref = _resolve_booking_ref(th)
                        _esc_note = result.get("internal_note", "")
                        _chat_lines = []
                        for _m in th.get("messages", []):
                            _chat_lines.append(f"[{_m.get('role','?').upper()}] {_m.get('body','')}")
                        state_registry.create_pending_notification(
                            'escalation', 'email', from_email, _cname,
                            f"[ESCALATION] {_ref} - {_cname} ({from_email}) - {_esc_note[:200]}",
                            f"=== RE-ESCALATION (fully_escalated email) ===\n"
                            f"Customer: {_cname} <{from_email}>\n"
                            f"New issue: {_esc_note}\n\n"
                            f"=== CHAT LOG ===\n" + "\n".join(_chat_lines))
                        log(f"Escalated re-escalation: {from_email}")

                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    th["last_activity"] = now  # Brief 162: prevent premature archive
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    log(f"Fully escalated: holding reply sent to {from_email}")
                    continue

                # Detect returning customer by booking ref mention
                _detected_ref = _detect_booking_ref(body)
                if _detected_ref and not th["flags"].get("booking_ref"):
                    _past_booking = state_registry.get_booking(_detected_ref)
                    if _past_booking:
                        th["flags"]["returning_booking"] = _detected_ref
                        # Pre-populate fields from past booking if thread has no data yet
                        for _rbk in ("service_key", "date", "guests", "customer_name",
                                     "slot_time"):
                            _rbv = _past_booking.get(_rbk)
                            if _rbv and not th["fields"].get(_rbk):
                                th["fields"][_rbk] = _rbv if not isinstance(_rbv, int) else str(_rbv)
                        log(f"Returning customer: loaded booking {_detected_ref} for {from_email}")
                    else:
                        th["flags"]["unknown_ref"] = _detected_ref
                        log(f"Unknown booking ref {_detected_ref} mentioned by {from_email}")

                # Email-based returning customer lookup (cross-thread memory)
                if not _detected_ref and not th.get("completed_bookings"):
                    _email_bookings = state_registry.get_bookings_by_email(from_email)
                    if _email_bookings:
                        _eb_lines = []
                        for eb in _email_bookings[:3]:
                            _eb_lines.append(
                                f"  - {eb['service_key']} on {eb['date']} for {eb['guests']} guests "
                                f"(ref: {eb['booking_ref']})"
                            )
                        th["flags"]["_past_customer_bookings"] = "\n".join(_eb_lines)
                        log(f"Returning customer by email: {from_email} has {len(_email_bookings)} past booking(s)")

                # Step 1: Build action context + call marina_agent (single Claude call per message)
                agent_flags = dict(th.get("flags", {}))
                for _rk in ("awaiting_relay", "relay_token", "relay_question",
                            "relay_customer_email", "relay_reply_subject"):
                    agent_flags.pop(_rk, None)
                # Inject completed bookings summary for multi-service context
                _completed = th.get("completed_bookings", [])
                if _completed:
                    _cb_lines = []
                    for _cb in _completed:
                        _cb_lines.append(
                            f"  - {_cb.get('service_name', _cb.get('service_key', '?'))} on "
                            f"{_cb.get('date', '?')} for {_cb.get('guests', '?')} guests "
                            f"(ref: {_cb.get('booking_ref', 'N/A')})"
                        )
                    agent_flags["_completed_bookings_summary"] = "\n".join(_cb_lines)
                    # Check max bookings — tells Marina to decline new bookings
                    _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
                    if len(_completed) >= _max_bk and th["flags"].get("hold_created"):
                        agent_flags["_max_bookings_reached"] = True
                action_context = _build_action_context(th)

                # Brief 166: cross-channel customer lookup
                _cust_row = None
                _cust_file = None
                try:
                    _cust_row = state_registry.customer_lookup_or_create(
                        "email", from_email, display_name=from_name or ""
                    )
                    _cust_file = state_registry.customer_get_full(_cust_row["id"])
                except Exception as _e:
                    log(f"customer_lookup_failed email={from_email} err={_e}")

                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), agent_flags, action_context,
                    customer_file=_cust_file,
                )

                # Brief 166: record interaction + merge any new identifiers Marina extracted
                if _cust_row and _cust_row.get("id"):
                    try:
                        state_registry.customer_record_interaction(
                            _cust_row["id"], "email", f"Email thread: {subj[:80]}"
                        )
                        _new_fields_for_merge = result.get("fields", {}) or {}
                        for _ftype, _fkey in (("email", "email"), ("phone", "phone")):
                            _val = _new_fields_for_merge.get(_fkey)
                            if _val and str(_val).strip() and str(_val).strip().lower() != from_email.lower():
                                state_registry.customer_add_identifier(
                                    _cust_row["id"], _ftype, str(_val).strip()
                                )
                    except Exception as _e:
                        log(f"customer_postprocess_failed err={_e}")

                _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)

                # Clear one-shot flags after Claude has seen them
                if th["flags"].get("unknown_ref"):
                    del th["flags"]["unknown_ref"]

                # Multi-service: if booking intent + previous booking completed, archive and reset
                if (any(i in _BOOKING_INTENTS for i in result.get("intents", []))
                        and th["flags"].get("hold_created")):
                    _did_reset = _maybe_reset_for_new_booking(th)
                    if _did_reset:
                        log(f"Multi-service reset for {from_email}: booking #{len(th.get('completed_bookings', []))} archived")

                # Step 2: Merge fields — always overwrite when Claude returns non-empty values
                th.setdefault("fields", {})
                new_fields = result.get("fields", {}) or {}
                new_flags = result.get("flags", {}) or {}
                for k, v in new_fields.items():
                    if v is not None and v != "":
                        th["fields"][k] = v
                    elif v == "" and k in th["fields"]:
                        # Intentional clear — Claude returned empty string for existing field
                        del th["fields"][k]

                # Step 3: Persist flags — Python manages awaiting_booking_confirmation (set only)
                th.setdefault("flags", {})
                _was_awaiting = th["flags"].get("awaiting_booking_confirmation", False)
                if new_flags.get("awaiting_booking_confirmation"):
                    new_flags.pop("awaiting_booking_confirmation")
                th["flags"].update(new_flags)

                # Change detection: cancel soft hold if customer changed booking details
                if _was_awaiting and not th["flags"].get("awaiting_booking_confirmation") \
                        and not th["flags"].get("booking_confirmed"):
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        _h_svc = th["flags"].pop("hold_service_key", "")
                        _h_date = th["flags"].pop("hold_date", "")
                        _h_dep = th["flags"].pop("hold_slot_time", "")
                        th["flags"].pop("hold_id", None)
                        if _h_svc and _h_date and _h_dep:
                            gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                    th["flags"]["slot_checked"] = False
                    th["flags"]["slot_available"] = False
                    log(f"Soft hold cancelled for {from_email}: customer changed booking details")

                log(f"Intents: {result.get('intents')} | Fields: {th['fields']}")

                # Step 3a: Post-validation — Python validates fields and may override reply
                reply_text = result["reply"]
                _pv_service_key = th["fields"].get("service_key", "")
                _pv_service = config_loader.get_service(_pv_service_key) if _pv_service_key else {}
                _run_pv = any(i in _BOOKING_INTENTS for i in result.get("intents", []))
                # Guard: if customer was responding to a booking summary and didn't change
                # any booking fields, skip post-validate to prevent decline loop
                if _run_pv and _was_awaiting and not th["flags"].get("booking_confirmed"):
                    _new_f = result.get("fields", {}) or {}
                    if not any(_new_f.get(k) for k in ("service_name", "date", "guests", "service_key", "slot_time")):
                        _run_pv = False
                if _run_pv:
                    # Brief 161: _post_validate no longer returns reply text — Marina
                    # writes all booking-flow replies in the customer's language via
                    # her prompt. This step only decides whether to advance state.
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_service)
                    if _booking_flow_on and _pv_set_awaiting:
                        th["flags"]["awaiting_booking_confirmation"] = True

                # Step 3b: Availability pre-check + soft hold (SKIP when booking_flow is OFF)
                if (_booking_flow_on
                        and th["flags"].get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
                    fields_for_check = th["fields"]
                    _ck_svc = fields_for_check.get("service_key", "")
                    _ck_deps = config_loader.get_service(_ck_svc).get("slots", []) if _ck_svc else []
                    _ck_start = (fields_for_check.get("slot_time")
                                 or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
                    _ck_guests = int(fields_for_check.get("guests") or 1)
                    avail = gws_calendar.check_availability(
                        _ck_svc, fields_for_check.get("date", ""), _ck_start, _ck_guests)
                    th["flags"]["slot_checked"] = True
                    th["flags"]["slot_available"] = avail.get("available", False)
                    th["flags"]["spots_remaining"] = avail.get("spots_remaining", 0)
                    th["flags"]["trip_capacity"] = avail.get("capacity", 0)
                    if avail.get("available"):
                        hold_id = state_registry.create_soft_hold(
                            _ck_svc,
                            fields_for_check.get("date", ""),
                            _ck_start,
                            _ck_guests,
                            avail.get("capacity", 20),
                            customer_name=th["fields"].get("customer_name", ""),
                            customer_email=from_email,
                        )
                        if hold_id is not None:
                            th["flags"]["hold_id"] = hold_id
                            th["flags"]["hold_service_key"] = _ck_svc
                            th["flags"]["hold_date"] = fields_for_check.get("date", "")
                            th["flags"]["hold_slot_time"] = _ck_start
                            log(f"Soft hold created for {from_email}: hold_id={hold_id}, "
                                f"spots_remaining={avail.get('spots_remaining')}")
                        else:
                            # Race: capacity was grabbed between check and insert
                            th["flags"]["slot_available"] = False
                            th["flags"]["awaiting_booking_confirmation"] = False
                            th["flags"]["slot_checked"] = False
                            _unavail_name = _pv_service.get("display_name", _ck_svc)
                            _unavail_sig = config_loader.get_agent_signature()
                            reply_text = (
                                f"Unfortunately the {_unavail_name} is fully booked on that date. "
                                f"Would you like to try a different date?\n\n"
                                f"Warm regards,\n{_unavail_sig}"
                            )
                            log(f"Soft hold race for {from_email}: slot full at insert time")
                    else:
                        th["flags"]["awaiting_booking_confirmation"] = False
                        th["flags"]["slot_checked"] = False
                        _unavail_name = _pv_service.get("display_name", _ck_svc)
                        _unavail_sig = config_loader.get_agent_signature()
                        reply_text = (
                            f"Unfortunately the {_unavail_name} is fully booked on that date. "
                            f"Would you like to try a different date?\n\n"
                            f"Warm regards,\n{_unavail_sig}"
                        )
                        log(f"Slot unavailable for {from_email}: "
                            f"{avail.get('spots_remaining', 0)}/{avail.get('capacity', 0)} spots remaining")

                # Semi-escalation handler: relay question to human team, holding reply to customer
                if result.get("semi_escalation"):
                    relay_question = result.get("relay_question", "(no question captured)")
                    # Cancel any soft hold created during Step 3b — booking is not confirmed
                    if th["flags"].get("hold_id"):
                        state_registry.cancel_hold(th["flags"]["hold_id"])
                        _h_svc = th["flags"].pop("hold_service_key", "")
                        _h_date = th["flags"].pop("hold_date", "")
                        _h_dep = th["flags"].pop("hold_slot_time", "")
                        th["flags"].pop("hold_id", None)
                        if _h_svc and _h_date and _h_dep:
                            gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                    th["flags"]["slot_checked"] = False
                    th["flags"]["slot_available"] = False
                    relay_token = uuid.uuid4().hex[:12]
                    th["flags"]["awaiting_relay"] = True
                    th["flags"]["relay_token"] = relay_token
                    th["flags"]["relay_question"] = relay_question
                    th["flags"]["relay_customer_email"] = from_email
                    th["flags"]["relay_reply_subject"] = "Re: " + subj
                    _ref = _resolve_booking_ref(th)
                    _cname = th["fields"].get("customer_name", "Unknown")
                    _relay_alert = (
                        f"Customer: {_cname} <{from_email}>\n"
                        f"Their question: {relay_question}\n\n"
                        f"Booking context:\n"
                        f"  Trip: {th['fields'].get('service_key', '')} | "
                        f"Date: {th['fields'].get('date', '')} | "
                        f"Guests: {th['fields'].get('guests', '')}\n"
                        f"  Ref: {_ref}\n\n"
                        f"INSTRUCTIONS: Reply to this email with your answer.\n"
                        f"Marina will relay it to the customer in her own words."
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[RELAY-{relay_token}] {_ref} - {_cname}",
                            _relay_alert,
                            reply_to=EMAIL_ADDR,
                        )
                        log(f"Semi-escalation: relay alert sent to {demo_support_email} for {from_email}")
                    except Exception as _rel_err:
                        log(f"Semi-escalation: alert send failed: {_rel_err}")
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    bm_logger.log("semi_escalation", email=from_email, subject=subj,
                                  relay_question=relay_question)
                    state_registry.create_pending_notification(
                        'relay', 'email', from_email,
                        _cname or "Unknown",
                        f"[RELAY-{relay_token}] {_ref} - {_cname}",
                        _relay_alert, relay_token=relay_token)
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    th["last_activity"] = now  # Brief 162: prevent premature archive
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Step 4: requires_human check
                if result.get("requires_human"):
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    th["flags"]["fully_escalated"] = True
                    bm_logger.log("human_required", email=from_email, subject=subj,
                                  internal_note=result.get("internal_note", ""))
                    # Build and send full escalation alert
                    chat_log_lines = []
                    for m in th.get("messages", []):
                        chat_log_lines.append(
                            f"[{m.get('role', '?').upper()} | {m.get('ts', '')}]"
                        )
                        chat_log_lines.append(m.get("body", ""))
                        chat_log_lines.append("---")
                    chat_log = "\n".join(chat_log_lines) or "(no messages logged)"
                    booking_ref_esc = _resolve_booking_ref(th)
                    customer_name_esc = th["fields"].get("customer_name", "Unknown")
                    intents_str = ", ".join(result.get("intents") or ["unknown"])
                    _esc_note = result.get("internal_note", "").strip()
                    _esc_summary = _esc_note if _esc_note else intents_str
                    _phone_esc = th["fields"].get("phone", "")
                    escalation_alert = (
                        f"=== CUSTOMER ===\n"
                        f"Email: {from_email}\n"
                        f"Name: {customer_name_esc}\n"
                        f"Phone: {_phone_esc or 'not provided'}\n\n"
                        f"=== CHAT LOG ===\n{chat_log}\n\n"
                        f"=== BOOKING FIELDS ===\n"
                        f"{json.dumps(th['fields'], indent=2, ensure_ascii=False)}\n\n"
                        f"=== MARINA'S INTERNAL NOTE ===\n"
                        f"{result.get('internal_note', '')}"
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[ESCALATION] {booking_ref_esc} - {customer_name_esc} ({from_email}) - {_esc_summary}",
                            escalation_alert,
                        )
                        log(f"Escalation alert sent to {demo_support_email} for {from_email}")
                    except Exception as _esc_err:
                        log(f"Escalation alert send failed: {_esc_err}")
                    sheets_writer.log_escalation({
                        "email": from_email,
                        "subject": subj,
                        "customer_name": th["fields"].get("customer_name", ""),
                        "intent": (result.get("intents") or ["unknown"])[0],
                        "fields_collected": th["fields"],
                        "internal_note": result.get("internal_note", ""),
                        "messages_json": json.dumps(th.get("messages", []), ensure_ascii=False),
                    })
                    state_registry.create_pending_notification(
                        'escalation', 'email', from_email,
                        customer_name_esc or "Unknown",
                        f"[ESCALATION] {booking_ref_esc} - {customer_name_esc} ({from_email}) - {_esc_summary}",
                        escalation_alert)
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    th["last_activity"] = now  # Brief 162: prevent premature archive
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Step 4.8: Booking flow toggle — if OFF, escalate booking intents
                if not _booking_flow_on:
                    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                        _fields_now = th["fields"]
                        if _fields_now.get("service_name") or _fields_now.get("date"):
                            _cname = _fields_now.get("customer_name", from_email)
                            _esc_history = th.get("messages", [])[-20:]
                            _esc_chat_lines = []
                            for _em in _esc_history:
                                _role = _em.get("role", "unknown").upper()
                                _esc_chat_lines.append(f"[{_role}]")
                                _esc_chat_lines.append(_em.get("text", _em.get("body", "")))
                                _esc_chat_lines.append("---")
                            _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
                            _esc_note = result.get("internal_note", "")
                            _esc_subject = (
                                f"[BOOKING REQUEST] {_cname} "
                                f"(Email: {from_email}) - {_esc_note or 'wants to book'}")
                            _esc_body = (
                                f"=== BOOKING REQUEST (booking_flow OFF) ===\n\n"
                                f"=== CUSTOMER ===\n"
                                f"Email: {from_email}\n"
                                f"Name: {_cname}\n\n"
                                f"=== COLLECTED FIELDS ===\n"
                                f"{json.dumps(_fields_now, indent=2, ensure_ascii=False)}\n\n"
                                f"=== EMAIL THREAD ===\n{_esc_chat_log}\n\n"
                                f"=== MARINA'S NOTE ===\n{_esc_note}"
                            )
                            state_registry.create_pending_notification(
                                'escalation', 'email', from_email, _cname,
                                _esc_subject, _esc_body)
                            bm_logger.log("booking_flow_off_escalated", email=from_email)
                            # Send Marina's conversational reply, then skip to next email
                            smtp_send(from_email, "Re: " + subj, reply_text,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            th["last_activity"] = now  # Brief 162: prevent premature archive
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue

                # Step 5: Booking flow
                if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                    fields_now = th["fields"]
                    if (fields_now.get("service_name") and fields_now.get("date")
                            and fields_now.get("guests") and fields_now.get("service_key")
                            and th["flags"].get("booking_confirmed")
                            and not th["flags"].get("hold_created")):
                        bm_logger.log(
                            "booking_attempted",
                            email=from_email, subject=subj,
                            service_name=fields_now.get("service_name"),
                            date=fields_now.get("date"),
                            guests=fields_now.get("guests"),
                            customer_name=fields_now.get("customer_name"),
                            phone=fields_now.get("phone"),
                            special_requests=fields_now.get("special_requests"),
                        )
                        sheets_writer.log_event("booking_attempted", {
                            "email": from_email, "subject": subj,
                            "service_name": fields_now.get("service_name"),
                            "date": fields_now.get("date"),
                        })
                        # Generate booking_ref + set on soft hold BEFORE manifest creation
                        _chars = string.ascii_uppercase + string.digits
                        booking_ref = ''.join(random.choices(_chars, k=6))
                        th["flags"]["booking_ref"] = booking_ref
                        if th["flags"].get("hold_id"):
                            state_registry.set_booking_ref(th["flags"]["hold_id"], booking_ref)
                        res = gws_calendar.create_or_update_manifest(fields_now)
                        if not res.get("ok"):
                            _manifest_error = str(res.get("error", ""))
                            _is_api_error = any(s in _manifest_error for s in (
                                '"code": 404', '"code": 500', '"code": 403', '"code": 401',
                                "'code': 404", "'code': 500", "'code': 403", "'code': 401",
                                'Calendar ID not configured'))
                            bm_logger.log(
                                "hold_failed",
                                email=from_email, subject=subj,
                                error=_manifest_error[:200],
                                error_type="api" if _is_api_error else "business",
                                service_name=fields_now.get("service_name"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                            )
                            if th["flags"].get("hold_id"):
                                state_registry.cancel_hold(th["flags"]["hold_id"])
                                _h_svc = th["flags"].pop("hold_service_key", "")
                                _h_date = th["flags"].pop("hold_date", "")
                                _h_dep = th["flags"].pop("hold_slot_time", "")
                                th["flags"].pop("hold_id", None)
                                if _h_svc and _h_date and _h_dep:
                                    gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                            th["flags"]["slot_checked"] = False
                            th["flags"]["slot_available"] = False
                            if _is_api_error:
                                _retry_count = th["flags"].get("manifest_retry_count", 0) + 1
                                th["flags"]["manifest_retry_count"] = _retry_count
                                if _retry_count >= 2:
                                    _cname = fields_now.get("customer_name", from_email)
                                    state_registry.create_pending_notification(
                                        'escalation', 'email', from_email, _cname,
                                        f"[SYSTEM] Manifest failure for {_cname} (Email: {from_email})",
                                        f"Booking failed {_retry_count} times due to API error.\n"
                                        f"Error: {_manifest_error[:300]}\n"
                                        f"Fields: {json.dumps(fields_now, indent=2, ensure_ascii=False)}")
                                    bm_logger.log("email_manifest_escalated", email=from_email,
                                                  retry_count=_retry_count)
                                th["flags"]["booking_confirmed"] = False
                                th["flags"]["awaiting_booking_confirmation"] = True
                            sheets_writer.log_hold_failed({
                                "email": from_email, "subject": subj,
                                "service_name": fields_now.get("service_name"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "error": _manifest_error[:200],
                            })
                            failure_reply = result.get("reply_hold_failed") or result["reply"]
                            smtp_send(from_email, "Re: " + subj, failure_reply,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            log(f"Manifest create FAILED for {from_email}: {_manifest_error[:100]}")
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            th["last_activity"] = now  # Brief 162: prevent premature archive
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue
                        else:
                            th["flags"].pop("manifest_retry_count", None)
                            th["flags"]["hold_created"] = True
                            if th["flags"].get("hold_id"):
                                state_registry.confirm_hold(th["flags"]["hold_id"])
                            th["flags"]["event_id"] = res.get("eventId")
                            th["flags"]["event_link"] = res.get("htmlLink")
                            service_key = fields_now.get("service_key", "")
                            reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)

                            _payment_timing = config_loader.get_raw().get("payment", {}).get("timing", "upfront")
                            if _payment_timing in ("upfront", "deposit"):
                                price_usd = (config_loader.get_service(service_key).get("price", 0)
                                             if service_key else 0)
                                pay = payment_stub.generate_payment_link(booking_ref, price_usd)
                                pay_link = f"https://demo.pay/{pay['payment_id']}"
                                th["flags"]["payment_id"] = pay.get("payment_id")
                                th["flags"]["payment_link"] = pay_link
                                th["flags"]["payment_status"] = pay.get("status")
                                reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                            else:
                                reply_text = reply_text.replace("[PAYMENT_LINK]", "")
                            bm_logger.log(
                                "hold_created",
                                email=from_email, subject=subj,
                                event_id=th["flags"].get("event_id"),
                                html_link=th["flags"].get("event_link"),
                                payment_id=th["flags"].get("payment_id"),
                                payment_link=th["flags"].get("payment_link"),
                                service_name=fields_now.get("service_name"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                                customer_name=fields_now.get("customer_name"),
                                phone=fields_now.get("phone"),
                                special_requests=fields_now.get("special_requests"),
                            )
                            sheets_writer.log_hold_created({
                                "booking_ref": booking_ref,
                                "email": from_email,
                                "subject": subj,
                                "customer_name": fields_now.get("customer_name"),
                                "service_name": fields_now.get("service_name"),
                                "service_key": fields_now.get("service_key"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "slot_time": fields_now.get("slot_time"),
                                "phone": fields_now.get("phone"),
                                "special_requests": fields_now.get("special_requests"),
                                "total_price": int(fields_now.get("guests") or 0) * price_usd,
                                "html_link": th["flags"].get("event_link"),
                                "payment_link": th["flags"].get("payment_link"),
                                "payment_status": pay.get("status"),
                            })
                            # Log manifest summary to Sheets
                            _manifest_service_key = fields_now.get("service_key", "")
                            _manifest_passengers = state_registry.get_slot_passengers(
                                _manifest_service_key,
                                fields_now.get("date", ""),
                                fields_now.get("slot_time", ""),
                            )
                            _manifest_confirmed = sum(1 for p in _manifest_passengers if p["status"] == "confirmed")
                            _manifest_pending = sum(1 for p in _manifest_passengers if p["status"] == "soft_hold")
                            _manifest_total_guests = sum(p["guests"] for p in _manifest_passengers)
                            _manifest_total_revenue = _manifest_total_guests * price_usd
                            _manifest_capacity = config_loader.get_service(_manifest_service_key).get("capacity", 20)
                            sheets_writer.log_manifest_update({
                                "service_key": _manifest_service_key,
                                "date": fields_now.get("date", ""),
                                "slot_time": fields_now.get("slot_time", ""),
                                "total_guests": _manifest_total_guests,
                                "capacity": _manifest_capacity,
                                "confirmed_count": _manifest_confirmed,
                                "pending_count": _manifest_pending,
                                "total_revenue": _manifest_total_revenue,
                                "calendar_link": th["flags"].get("event_link", ""),
                                "booking_ref": booking_ref,
                            })
                            log(f"Manifest CREATED/UPDATED for {from_email}: eventId={res.get('eventId')}")

                            # Save booking for cross-thread memory
                            state_registry.save_booking(
                                booking_ref, fields_now, th["flags"],
                                customer_email=from_email,
                            )

                    # Send Claude's reply for all booking sub-cases
                    reply_text = reply_text.replace("[PAYMENT_LINK]", "")
                    reply_text = reply_text.replace("[BOOKING_REF]", "")
                    smtp_send(from_email, "Re: " + subj, reply_text,
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": reply_text,
                    })

                # Step 6: All other intents
                else:
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["messages"].append({
                        "role": "marina",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "body": result["reply"],
                    })
                    primary_intent = (result.get("intents") or ["inquiry"])[0]
                    bm_logger.log(primary_intent, email=from_email, subject=subj,
                                  internal_note=result.get("internal_note", ""))
                    sheets_writer.log_event(primary_intent, {"email": from_email, "subject": subj})

                # Step 7: Persist state
                im.uid("store", uid, "+FLAGS", r"(\Seen)")
                th["reply_times"].append(now)
                th["last_customer_hash"] = customer_hash
                th["last_activity"] = now
                threads[thread_key] = th
                save_json(THREAD_STATE_PATH, state)
                log(f"Replied + marked Seen: {from_email}")

            # Brief 182: im.logout() REMOVED — connection persists across iterations

            # Process pending operator notifications (from WhatsApp)
            _pending = state_registry.get_pending_notifications()
            for _pn in _pending:
                try:
                    if not demo_support_email:
                        log(f"Skipping notification id={_pn['id']} — no support_email configured")
                        continue
                    smtp_send(demo_support_email, _pn["subject"], _pn["body"],
                              reply_to=EMAIL_ADDR)
                    state_registry.update_notification_status(_pn["id"], "sent")
                    log(f"Sent pending {_pn['notification_type']} "
                        f"notification id={_pn['id']} for {_pn['customer_id']}")
                except Exception as _pn_err:
                    log(f"Failed to send pending notification "
                        f"id={_pn['id']}: {_pn_err}")

            # Heartbeat — write timestamp for external monitoring
            try:
                with open(HEARTBEAT_PATH, "w") as f:
                    f.write(str(int(time.time())))
            except Exception:
                pass

        except Exception as ex:
            _consecutive_errors += 1
            log(f"Error: {ex}")
            # Brief 182: kill broken connection — next iteration will reconnect
            if im is not None:
                try:
                    im.logout()
                except Exception:
                    pass
            im = None
            if _consecutive_errors >= _ERROR_ALERT_THRESHOLD and not _error_alert_sent:
                try:
                    if not demo_support_email:
                        pass
                    else:
                        smtp_send(demo_support_email,
                        f"[ALERT] Marina poller: {_consecutive_errors} consecutive errors",
                        f"Latest error: {ex}\n\nCheck docker logs for this container")
                    _error_alert_sent = True
                except Exception:
                    pass
            # Brief 179: forced exit after sustained failure so supervisord restarts fresh.
            if _consecutive_errors >= _ERROR_EXIT_THRESHOLD:
                log(f"FATAL: {_consecutive_errors} consecutive errors. Exiting for supervisord restart.")
                sys.exit(1)
        else:
            _consecutive_errors = 0
            _error_alert_sent = False
        # Brief 182: NO finally block — connection persists across iterations.
        # Cleanup is in the except block (on error) and reconnect logic (on token refresh).

        # Brief 179: exponential backoff on consecutive errors — 10s, 20s, 40s... cap 300s.
        if _consecutive_errors > 0:
            _backoff = min(POLL_INTERVAL * (2 ** (_consecutive_errors - 1)), 300)
            log(f"Backing off {_backoff}s (consecutive errors: {_consecutive_errors})")
            time.sleep(_backoff)
        else:
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
