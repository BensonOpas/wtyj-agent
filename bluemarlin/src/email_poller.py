#!/usr/bin/env python3
# FILE: email_poller.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 048
# DEPENDS ON: state_registry.py (Brief 004)
# DEPENDS ON: payment_stub.py (original)
# DEPENDS ON: bm_logger.py (original)
# DEPENDS ON: marina_agent.py (Brief 023)
# DEPENDS ON: config_loader.py (Brief 022)
# DEPENDS ON: gws_calendar.py (Brief 032)
# IMPORTS FROM: state_registry.py (Brief 004)
# IMPORTS FROM: payment_stub.py (original)
# IMPORTS FROM: bm_logger.py (original)
# IMPORTS FROM: marina_agent.py (Brief 023)
# IMPORTS FROM: config_loader.py (Brief 022)
import state_registry
import payment_stub
import bm_logger
import imaplib, email, urllib.request, urllib.parse, json, time, os, re, hashlib, uuid
from datetime import datetime, timezone
from email.utils import parseaddr
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib, base64
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import marina_agent
import config_loader
import sheets_writer
import gws_calendar

# ========= CONFIG =========
CLIENT_ID = "28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID = "caac06b5-1420-4223-9dcc-ba4a670ec26a"
EMAIL_ADDR = "hello@wetakeyourjob.com"

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.normpath(os.path.join(_SRC_DIR, "..", "config"))
REFRESH_TOKEN_PATH = os.path.join(_CONFIG_DIR, "azure_refresh_token.txt")
SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587

MAILBOX = "INBOX"
POLL_INTERVAL = 30

STATE_DIR = _CONFIG_DIR
THREAD_STATE_PATH = os.path.join(_CONFIG_DIR, "email_thread_state.json")

# Anti-loop: max replies per thread within window
MAX_REPLIES_PER_THREAD = 10
REPLY_WINDOW_SECONDS = 60 * 60

# Intents that activate the Python booking validation and hold-creation flow.
# "reschedule" is included because mid-thread date/time changes are booking
# modifications that need the same validation (day-of-week, departure, summary).
_BOOKING_INTENTS = {"booking", "reschedule"}

# ========= HELPERS =========
def _decode_subj(raw):
    parts = []
    for data, charset in _decode_header(raw or ""):
        if isinstance(data, bytes):
            parts.append(data.decode(charset or "utf-8", errors="ignore"))
        else:
            parts.append(data)
    return "".join(parts)

def log(msg):
    print(msg, flush=True)

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

def sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()

def normalize_subject(subj: str) -> str:
    s = (subj or "").strip()
    # strip repeated Re:/Fwd:
    while True:
        ns = re.sub(r"^(re|fwd|fw)\s*:\s*", "", s, flags=re.IGNORECASE).strip()
        if ns == s:
            break
        s = ns
    return s

def get_refresh_token():
    return open(REFRESH_TOKEN_PATH).read().strip()

def oauth_token(scope: str) -> str:
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "refresh_token": get_refresh_token(),
        "grant_type": "refresh_token",
        "scope": scope
    }).encode()
    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token", data)
    ).read())
    return resp["access_token"]

def imap_connect():
    token = oauth_token("offline_access https://outlook.office.com/IMAP.AccessAsUser.All")
    auth_string = f"user={EMAIL_ADDR}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
    im = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    im.authenticate("XOAUTH2", lambda _: auth_string)
    return im

def smtp_send(to_addr: str, subject: str, body: str, in_reply_to=None, references=None, reply_to=None):
    token = oauth_token("offline_access https://outlook.office.com/SMTP.Send")
    auth_string = f"user={EMAIL_ADDR}\x01auth=Bearer {token}\x01\x01"
    auth_b64 = base64.b64encode(auth_string.encode("ascii")).decode("ascii")

    msg = MIMEMultipart()
    msg["From"] = "Marina <{}>".format(EMAIL_ADDR)
    msg["To"] = to_addr
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body, "plain", "utf-8"))

    s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    s.ehlo(); s.starttls(); s.ehlo()
    code, resp = s.docmd("AUTH", "XOAUTH2 " + auth_b64)
    if code != 235:
        s.quit()
        raise RuntimeError(f"SMTP AUTH failed: {code} {resp!r}")
    s.sendmail(EMAIL_ADDR, [to_addr], msg.as_string())
    s.quit()

def extract_text(msg):
    # Prefer text/plain, fallback to stripped HTML.
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp.lower():
                payload = part.get_payload(decode=True) or b""
                return payload.decode("utf-8", errors="ignore").strip()
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                html = payload.decode("utf-8", errors="ignore")
                html = re.sub(r"<[^>]+>", " ", html)
                html = re.sub(r"\s+", " ", html)
                return html.strip()
    payload = msg.get_payload(decode=True) or b""
    return payload.decode("utf-8", errors="ignore").strip()

def strip_quotes(text: str) -> str:
    # remove typical quoted blocks
    t = text or ""
    # remove everything after "On ... wrote:" patterns
    t = re.split(r"\nOn .*wrote:\n", t, flags=re.IGNORECASE)[0]
    # remove lines starting with >
    lines = [ln for ln in t.splitlines() if not ln.strip().startswith(">")]
    t = "\n".join(lines).strip()
    return t

def resolve_thread_key(msg, from_email: str, subject: str, mid_index: dict) -> str:
    """
    Resolve thread key for an inbound message.
    Priority: References first-ID -> In-Reply-To -> sender+subject fallback.
    """
    refs = (msg.get("References") or "").strip()
    if refs:
        first_ref = refs.split()[0].strip()
        if first_ref in mid_index:
            return mid_index[first_ref]

    irt = (msg.get("In-Reply-To") or "").strip()
    if irt and irt in mid_index:
        return mid_index[irt]

    return "subj:{}:{}".format(
        from_email.strip().lower(),
        normalize_subject(subject).strip().lower()
    )


# ========= BOOKING VALIDATION HELPERS =========
def _day_matches(day_name, days_available):
    """Check if day_name matches the trip's days_available string."""
    if days_available.lower() == "daily":
        return True
    return day_name.lower() in days_available.lower()


def _suggest_dates(date_str, days_available):
    """Suggest 2-3 nearby valid dates."""
    from datetime import timedelta as _td
    base = datetime.strptime(date_str, "%Y-%m-%d")
    suggestions = []
    for offset in range(1, 14):
        candidate = base + _td(days=offset)
        if _day_matches(candidate.strftime("%A"), days_available):
            suggestions.append(f"- {candidate.strftime('%A, %d %B %Y')}")
            if len(suggestions) >= 3:
                break
    return "\n".join(suggestions) if suggestions else "Please suggest another date!"


def _build_booking_summary(fields, trip):
    """Build a data-driven booking summary from fields and trip config."""
    trip_name = trip.get("display_name", fields.get("trip_key", ""))
    date_str = fields.get("date", "")
    guests = int(fields.get("guests") or 1)
    departure_time = fields.get("departure_time", "")
    departures = trip.get("departures", [])
    dep_info = next((d for d in departures if d.get("time") == departure_time), None)
    if not dep_info and departures:
        dep_info = departures[0]
        departure_time = dep_info.get("time", "")
    vessel = dep_info.get("vessel", "") if dep_info else ""
    dep_point = dep_info.get("departure_point", "") if dep_info else ""
    price_adult = trip.get("price_adult_usd", 0)
    total = price_adult * guests
    included = ", ".join(trip.get("included", [])) or "see trip details"
    try:
        date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except ValueError:
        date_fmt = date_str
    return (
        f"Here's a quick summary of your booking:\n\n"
        f"  Trip: {trip_name}\n"
        f"  Date: {date_fmt}\n"
        f"  Guests: {guests}\n"
        f"  Departure: {departure_time} from {dep_point} aboard {vessel}\n"
        f"  Total: ${total} USD ({guests} x ${price_adult})\n"
        f"  Included: {included}\n\n"
        f"Shall I lock this in for you?"
    )


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
            "awaiting_booking_confirmation: false; (c) unclear — ask "
            "for clarification. Do NOT generate a new booking summary."
        )
    return ""


def _post_validate(th, result, trip):
    """
    Validate extracted fields after Claude call.
    Returns (reply_override, should_set_awaiting).
    """
    fields = th.get("fields", {})
    flags = th.get("flags", {})

    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("experience", "date", "guests", "trip_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    departures = trip.get("departures", [])

    # 1. Day-of-week check
    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = trip.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            return (
                f"Great choice! Unfortunately, the {trip.get('display_name', fields['trip_key'])} "
                f"doesn't run on {day_name}s — it runs {days_avail}. "
                f"Would any of these dates work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}"
            ), False
    except ValueError:
        pass

    # 2. Departure time check (multi-departure trips only)
    if len(departures) > 1 and not fields.get("departure_time"):
        dep_lines = "\n".join(
            f"- {d['time']} aboard {d.get('vessel', '?')} from {d.get('departure_point', '?')}"
            for d in departures
        )
        return (
            f"Almost there! The {trip.get('display_name', fields['trip_key'])} has "
            f"a couple of departure options:\n\n{dep_lines}\n\n"
            f"Which one works best for you?"
        ), False

    # 3. Child pricing — Claude sets needs_child_ages flag
    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    # 4. All checks pass — build data-driven summary
    summary = _build_booking_summary(fields, trip)
    return summary, True


# ========= MAIN LOOP =========
def main():
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")
    demo_support_email = config_loader.get_business().get("demo_support_email", "butlerbensonagent@gmail.com")

    state = load_json(THREAD_STATE_PATH, {"threads": {}, "message_id_index": {}})
    state.setdefault("message_id_index", {})

    while True:
        try:
            im = imap_connect()
            im.select(MAILBOX)

            typ, data = im.uid("search", None, "UNSEEN")
            uids = data[0].split() if data and data[0] else []

            for uid in uids:
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

                threads = state["threads"]
                th = threads.get(thread_key, {
                    "fields": {},
                    "flags": {},
                    "last_customer_hash": "",
                    "reply_times": [],
                    "messages": []
                })

                # Deduplicate identical customer content
                customer_hash = sha((from_email.lower() + "|" + normalize_subject(subj).lower() + "|" + body.strip()))
                if th.get("last_customer_hash") == customer_hash:
                    log("Duplicate customer content -> skip reply, mark Seen.")
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Anti-loop guard
                now = int(time.time())
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
                        log(f"RELAY: no matching customer thread for token={relay_token_in} — skipping")
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
                    state["threads"][customer_thread_key] = customer_th
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Append inbound message to chat log
                th.setdefault("messages", [])
                th["messages"].append({
                    "role": "customer",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                })

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
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    log(f"Fully escalated: holding reply sent to {from_email}")
                    continue

                # Step 1: Build action context + call marina_agent (single Claude call per message)
                agent_flags = dict(th.get("flags", {}))
                for _rk in ("awaiting_relay", "relay_token", "relay_question",
                            "relay_customer_email", "relay_reply_subject"):
                    agent_flags.pop(_rk, None)
                action_context = _build_action_context(th)
                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), agent_flags, action_context,
                )

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
                        th["flags"].pop("hold_id", None)
                    th["flags"]["slot_checked"] = False
                    th["flags"]["slot_available"] = False
                    log(f"Soft hold cancelled for {from_email}: customer changed booking details")

                log(f"Intents: {result.get('intents')} | Fields: {th['fields']}")

                # Step 3a: Post-validation — Python validates fields and may override reply
                reply_text = result["reply"]
                _pv_trip_key = th["fields"].get("trip_key", "")
                _pv_trip = config_loader.get_trip(_pv_trip_key) if _pv_trip_key else {}
                if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                    _pv_override, _pv_set_awaiting = _post_validate(th, result, _pv_trip)
                    if _pv_override:
                        _intents = result.get("intents", [])
                        _has_side_topics = any(i not in _BOOKING_INTENTS for i in _intents)
                        if _has_side_topics:
                            # Preserve Claude's answers to non-booking questions
                            reply_text = result["reply"].rstrip() + "\n\n" + _pv_override
                        else:
                            # Booking-only: use override with signature
                            _sig = config_loader.get_agent_signature()
                            reply_text = _pv_override + f"\n\nWarm regards,\n{_sig}"
                        if _pv_set_awaiting:
                            th["flags"]["awaiting_booking_confirmation"] = True

                # Step 3b: Availability pre-check + soft hold when booking summary is being sent
                if (th["flags"].get("awaiting_booking_confirmation")
                        and not th["flags"].get("slot_checked")):
                    fields_for_check = th["fields"]
                    _ck_trip = fields_for_check.get("trip_key", "")
                    _ck_deps = config_loader.get_trip(_ck_trip).get("departures", []) if _ck_trip else []
                    _ck_start = (fields_for_check.get("departure_time")
                                 or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
                    _ck_guests = int(fields_for_check.get("guests") or 1)
                    avail = gws_calendar.check_availability(
                        _ck_trip, fields_for_check.get("date", ""), _ck_start, _ck_guests)
                    th["flags"]["slot_checked"] = True
                    th["flags"]["slot_available"] = avail.get("available", False)
                    th["flags"]["spots_remaining"] = avail.get("spots_remaining", 0)
                    th["flags"]["trip_capacity"] = avail.get("capacity", 0)
                    if avail.get("available"):
                        hold_id = state_registry.create_soft_hold(
                            _ck_trip,
                            fields_for_check.get("date", ""),
                            _ck_start,
                            _ck_guests,
                            avail.get("capacity", 20)
                        )
                        if hold_id is not None:
                            th["flags"]["hold_id"] = hold_id
                            log(f"Soft hold created for {from_email}: hold_id={hold_id}, "
                                f"spots_remaining={avail.get('spots_remaining')}")
                        else:
                            # Race: capacity was grabbed between check and insert
                            th["flags"]["slot_available"] = False
                            th["flags"]["awaiting_booking_confirmation"] = False
                            th["flags"]["slot_checked"] = False
                            _unavail_name = _pv_trip.get("display_name", _ck_trip)
                            _unavail_sig = config_loader.get_agent_signature()
                            reply_text = (
                                f"Oh no — it looks like the {_unavail_name} on that date "
                                f"is fully booked! Would you like to try a different date?\n\n"
                                f"Warm regards,\n{_unavail_sig}"
                            )
                            log(f"Soft hold race for {from_email}: slot full at insert time")
                    else:
                        th["flags"]["awaiting_booking_confirmation"] = False
                        th["flags"]["slot_checked"] = False
                        _unavail_name = _pv_trip.get("display_name", _ck_trip)
                        _unavail_sig = config_loader.get_agent_signature()
                        reply_text = (
                            f"Oh no — it looks like the {_unavail_name} on that date "
                            f"is fully booked! Would you like to try a different date?\n\n"
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
                        th["flags"].pop("hold_id", None)
                    th["flags"]["slot_checked"] = False
                    th["flags"]["slot_available"] = False
                    relay_token = uuid.uuid4().hex[:12]
                    th["flags"]["awaiting_relay"] = True
                    th["flags"]["relay_token"] = relay_token
                    th["flags"]["relay_question"] = relay_question
                    th["flags"]["relay_customer_email"] = from_email
                    th["flags"]["relay_reply_subject"] = "Re: " + subj
                    _ref = th["flags"].get("booking_ref", "NO-REF")
                    _cname = th["fields"].get("customer_name", "Unknown")
                    _relay_alert = (
                        f"Customer: {_cname} <{from_email}>\n"
                        f"Their question: {relay_question}\n\n"
                        f"Booking context:\n"
                        f"  Trip: {th['fields'].get('trip_key', '')} | "
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
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
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
                    booking_ref_esc = th["flags"].get("booking_ref", "NO-REF")
                    customer_name_esc = th["fields"].get("customer_name", "Unknown")
                    intents_str = ", ".join(result.get("intents") or ["unknown"])
                    escalation_alert = (
                        f"=== CHAT LOG ===\n{chat_log}\n\n"
                        f"=== BOOKING FIELDS ===\n"
                        f"{json.dumps(th['fields'], indent=2, ensure_ascii=False)}\n\n"
                        f"=== MARINA'S INTERNAL NOTE ===\n"
                        f"{result.get('internal_note', '')}"
                    )
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[ESCALATION] {booking_ref_esc} - {customer_name_esc} - {intents_str}",
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
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Step 5: Booking flow
                if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
                    fields_now = th["fields"]
                    if (fields_now.get("experience") and fields_now.get("date")
                            and fields_now.get("guests") and fields_now.get("trip_key")
                            and th["flags"].get("booking_confirmed")
                            and not th["flags"].get("hold_created")):
                        bm_logger.log(
                            "booking_attempted",
                            email=from_email, subject=subj,
                            experience=fields_now.get("experience"),
                            date=fields_now.get("date"),
                            guests=fields_now.get("guests"),
                            customer_name=fields_now.get("customer_name"),
                            phone=fields_now.get("phone"),
                            special_requests=fields_now.get("special_requests"),
                        )
                        sheets_writer.log_event("booking_attempted", {
                            "email": from_email, "subject": subj,
                            "experience": fields_now.get("experience"),
                            "date": fields_now.get("date"),
                        })
                        res = gws_calendar.create_hold(fields_now)
                        if not res.get("ok"):
                            bm_logger.log(
                                "hold_failed",
                                email=from_email, subject=subj,
                                error=res.get("error"),
                                experience=fields_now.get("experience"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                            )
                            if th["flags"].get("hold_id"):
                                state_registry.cancel_hold(th["flags"]["hold_id"])
                            sheets_writer.log_hold_failed({
                                "email": from_email, "subject": subj,
                                "experience": fields_now.get("experience"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "error": res.get("error"),
                            })
                            failure_reply = result.get("reply_hold_failed") or result["reply"]
                            smtp_send(from_email, "Re: " + subj, failure_reply,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            log(f"Hold create FAILED for {from_email}: {res.get('error')}")
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            th["reply_times"].append(now)
                            th["last_customer_hash"] = customer_hash
                            threads[thread_key] = th
                            save_json(THREAD_STATE_PATH, state)
                            continue
                        else:
                            th["flags"]["hold_created"] = True
                            if th["flags"].get("hold_id"):
                                state_registry.confirm_hold(th["flags"]["hold_id"])
                            th["flags"]["event_id"] = res.get("eventId")
                            th["flags"]["event_link"] = res.get("htmlLink")
                            event_id = th["flags"]["event_id"]
                            trip_key = fields_now.get("trip_key", "")
                            price_usd = (config_loader.get_trip(trip_key).get("price_adult_usd", 0)
                                         if trip_key else 0)
                            pay = payment_stub.generate_payment_link(event_id, price_usd)
                            pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                            th["flags"]["payment_id"] = pay.get("payment_id")
                            th["flags"]["payment_link"] = pay_link
                            th["flags"]["payment_status"] = pay.get("status")
                            reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                            booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
                            th["flags"]["booking_ref"] = booking_ref
                            bm_logger.log(
                                "hold_created",
                                email=from_email, subject=subj,
                                event_id=th["flags"].get("event_id"),
                                html_link=th["flags"].get("event_link"),
                                payment_id=th["flags"].get("payment_id"),
                                payment_link=th["flags"].get("payment_link"),
                                experience=fields_now.get("experience"),
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
                                "experience": fields_now.get("experience"),
                                "trip_key": fields_now.get("trip_key"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "departure_time": fields_now.get("departure_time"),
                                "phone": fields_now.get("phone"),
                                "special_requests": fields_now.get("special_requests"),
                                "total_price": int(fields_now.get("guests") or 0) * price_usd,
                                "html_link": th["flags"].get("event_link"),
                                "payment_link": th["flags"].get("payment_link"),
                                "payment_status": pay.get("status"),
                            })
                            log(f"Hold CREATED for {from_email}: eventId={res.get('eventId')}")

                    # Send Claude's reply for all booking sub-cases
                    reply_text = reply_text.replace("[PAYMENT_LINK]", "")
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
                threads[thread_key] = th
                save_json(THREAD_STATE_PATH, state)
                log(f"Replied + marked Seen: {from_email}")

            im.logout()

        except Exception as ex:
            log(f"Error: {ex}")

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
