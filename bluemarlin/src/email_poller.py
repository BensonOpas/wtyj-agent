#!/usr/bin/env python3
# FILE: email_poller.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 020
# DEPENDS ON: claude_client.py (Brief 001)
# DEPENDS ON: state_registry.py (Brief 004)
# DEPENDS ON: payment_stub.py (original)
# DEPENDS ON: bm_logger.py (original)
# DEPENDS ON: marina_extractor.py (Brief 002)
# DEPENDS ON: social_registry.py (original)
# DEPENDS ON: calendar.js (original)
# IMPORTS FROM: claude_client.py (Brief 001)
# IMPORTS FROM: state_registry.py (Brief 004)
# IMPORTS FROM: marina_extractor.py (Brief 002)
# IMPORTS FROM: payment_stub.py (original)
# IMPORTS FROM: bm_logger.py (original)
import state_registry
import payment_stub
import bm_logger
import imaplib, email, urllib.request, urllib.parse, json, subprocess, time, os, re, hashlib
from email.utils import parseaddr
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib, base64
import dateparser
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import claude_client
import sheets_writer

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

# Booking fields we require to proceed
REQUIRED_FIELDS = ["experience", "date", "guests"]

GROUP_BOOKING_THRESHOLD = 15

# ========= HELPERS =========
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

def smtp_send(to_addr: str, subject: str, body: str, in_reply_to=None, references=None):
    token = oauth_token("offline_access https://outlook.office.com/SMTP.Send")
    auth_string = f"user={EMAIL_ADDR}\x01auth=Bearer {token}\x01\x01"
    auth_b64 = base64.b64encode(auth_string.encode("ascii")).decode("ascii")

    msg = MIMEMultipart()
    msg["From"] = "Marina — BlueMarlin Tours Curaçao <{}>".format(EMAIL_ADDR)
    msg["To"] = to_addr
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
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

def stable_thread_key(msg, from_email: str, subject: str) -> str:
    """
    Deterministic thread key to prevent looping.

    We ALWAYS group by: sender + normalized subject.
    This avoids the "first email uses fallback, replies use refroot/irt" split-brain issue.
    """
    return "subj:{}:{}".format(
        from_email.strip().lower(),
        normalize_subject(subject).strip().lower()
    )



def detect_intent_and_fields(text: str) -> tuple[list[str], dict]:
    from marina_extractor import extract_fields

    VALID_INTENTS = {
        "booking", "inquiry", "cancellation",
        "reschedule", "complaint", "social", "off_topic"
    }

    prompt = (
        "You are an intent classifier for BlueMarlin Tours Cura\u00e7ao.\n"
        "Read the customer message below and identify ALL intents present.\n"
        "A message can have more than one intent.\n\n"
        "Available intents:\n"
        "- booking (wants to book or is mid-booking process)\n"
        "- inquiry (asking about price, availability, or what's included)\n"
        "- cancellation (wants to cancel an existing booking)\n"
        "- reschedule (wants to change date or time of existing booking)\n"
        "- complaint (unhappy, wants refund, has a problem)\n"
        "- social (friendly chat, compliment, joke, or banter about BlueMarlin)\n"
        "- off_topic (nothing to do with boat charters at all)\n\n"
        "Reply with ONLY a JSON array of matching intent strings.\n"
        "Examples:\n"
        '  ["booking"]\n'
        '  ["social", "booking"]\n'
        '  ["complaint", "reschedule"]\n'
        '  ["inquiry"]\n'
        '  ["off_topic"]\n'
        "No explanation. No extra text. Only the JSON array.\n\n"
        "Message:\n"
        f"{text}"
    )
    try:
        raw = claude_client.complete(prompt) or "[]"
        raw = raw.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("not a list")
        intents = [i.strip().lower() for i in parsed
                   if isinstance(i, str) and i.strip().lower() in VALID_INTENTS]
        if not intents:
            intents = ["inquiry"]
    except Exception:
        intents = ["inquiry"]

    fields = extract_fields(text) or {}

    # Merge adults + kids into guests
    if "adults" in fields or "kids" in fields:
        adults = int(fields.get("adults", 0) or 0)
        kids = int(fields.get("kids", 0) or 0)
        fields["guests"] = adults + kids

    return (intents, fields)

def ask_marina_llm(from_email, subject, body, mode="general"):
    """
    mode: general | booking_missing | booking_confirm
    """
    prompt = (
        "You are Marina for BlueMarlin Tours Curaçao. You may ONLY discuss boat charters: pricing, packages, timing, rules, "
        "pickup, payment, cancellations, capacity, availability, and next steps. Refuse ALL other topics.\n\n"
        f"MODE: {mode}\n"
        f"From: {from_email}\nSubject: {subject}\n\n"
        f"Customer message:\n{body}\n"
    )

    out = claude_client.complete(prompt)
    if not out:
        # fail-safe response
        out = "Hi — thanks for your email. Could you share your preferred date, number of guests, and which experience you want?"
    return out

def safe_out_of_scope_reply():
    return (
        "Hi there,\n\n"
        "Thanks for reaching out.\n\n"
        "I can only help with BlueMarlin Tours charter information (availability, packages, pricing, and booking details). "
        "If you share your preferred date, number of guests, and which experience you're interested in, I'll help right away.\n\n"
        "Warm regards,\n"
        "Marina\n"
        "BlueMarlin Tours Curaçao\n"
    )


def safe_complaint_reply():
    return (
        "Hi there,\n\n"
        "Thank you for reaching out, and I'm sorry to hear you've "
        "had a frustrating experience.\n\n"
        "I've flagged your message and our team will follow up with "
        "you directly as soon as possible.\n\n"
        "If your concern is about an upcoming or recent booking, "
        "please reply with your booking details and we'll prioritize it.\n\n"
        "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
    )


def safe_social_reply():
    return (
        "Hi there!\n\n"
        "Thank you so much — messages like yours make our day! \U0001f30a\n\n"
        "If you'd like to join us on the water, we'd love to have you. "
        "Just let us know which experience interests you, your preferred "
        "date, and how many guests — and we'll get everything set up.\n\n"
        "Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def safe_inquiry_reply():
    return (
        "Hi there!\n\n"
        "Thanks for reaching out to BlueMarlin Tours Cura\u00e7ao!\n\n"
        "Here's a quick overview of our experiences:\n\n"
        "\U0001f305 Sunset Signature Cruise \u2014 2.5 hours, departs 17:00\n"
        "   Perfect for couples and small groups. Drinks and sunset views.\n\n"
        "\u2693 Half Day Private Charter \u2014 4 hours, departs 09:00\n"
        "   Flexible itinerary. Great for families and private groups.\n\n"
        "\U0001f30a Full Day West Coast Escape \u2014 8 hours, departs 08:00\n"
        "   Full day on the water. Snorkeling, beaches, full experience.\n\n"
        "To check availability and hold your spot, just reply with:\n"
        "- Which experience you're interested in\n"
        "- Your preferred date\n"
        "- Number of guests\n\n"
        "Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def safe_change_request_reply(action: str):
    action_word = "cancel" if action == "cancellation" else "reschedule"
    return (
        f"Hi there,\n\n"
        f"Thank you for reaching out. I've received your request to "
        f"{action_word} your booking.\n\n"
        f"Our team will review your request and follow up with you "
        f"directly as soon as possible to confirm the changes.\n\n"
        f"If you have any urgent questions, please reply to this email "
        f"with your booking details and preferred alternative "
        f"(if rescheduling).\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def safe_large_group_reply(guests: int) -> str:
    return (
        f"Hi there!\n\n"
        f"Wow, a group of {guests} \u2014 that sounds like an amazing trip! \U0001f389\n\n"
        f"For groups this size we like to make sure everything is "
        f"set up perfectly for you. One of our team will be in touch "
        f"shortly to discuss the best options and get everything "
        f"arranged.\n\n"
        f"We can't wait to have you all on board!\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def safe_date_confirmation_reply(resolved_date: str, original: str) -> str:
    from datetime import datetime
    try:
        dt = datetime.strptime(resolved_date, "%Y-%m-%d")
        friendly = dt.strftime("%B %d, %Y")
    except Exception:
        friendly = resolved_date
    return (
        f"Hi there!\n\n"
        f"Just making sure \u2014 are you thinking {friendly}? "
        f"Say yes and I'll get your spot held right away, or "
        f"send me a different date if that's not right \U0001f60a\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def safe_date_past_reply(resolved_date: str, original: str) -> str:
    """Fired when date resolved to the past."""
    from datetime import datetime
    try:
        dt = datetime.strptime(resolved_date, "%Y-%m-%d")
        next_year = dt.replace(year=dt.year + 1)
        suggestion = next_year.strftime("%B %d, %Y")
    except Exception:
        suggestion = "a date next year"
    return (
        f"Hi there!\n\n"
        f"It looks like {original} has already passed \u2014 "
        f"did you mean {suggestion}, or did you have a different date in mind?\n\n"
        f"Just let me know and I'll check availability right away! \U0001f30a\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def safe_date_implausible_reply(resolved_date: str, original: str) -> str:
    """Fired when date seems too far in the future."""
    from datetime import datetime
    try:
        dt = datetime.strptime(resolved_date, "%Y-%m-%d")
        friendly = dt.strftime("%B %d, %Y")
    except Exception:
        friendly = resolved_date
    return (
        f"Hi there!\n\n"
        f"Just making sure \u2014 are you planning for {friendly}? "
        f"That's quite a bit ahead, so I want to make sure I have "
        f"the right date before holding your spot!\n\n"
        f"If that's correct just say yes and I'll get it sorted. "
        f"Or if you meant a sooner date, just send it over \U0001f60a\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def safe_date_vague_reply(original: str, resolvable_date: str = "") -> str:
    """Fired when date is too vague to use."""
    if resolvable_date:
        from datetime import datetime
        try:
            dt = datetime.strptime(resolvable_date, "%Y-%m-%d")
            friendly = dt.strftime("%B %d, %Y")
            return (
                f"Hi there!\n\n"
                f"Just to confirm \u2014 are you thinking {friendly}?\n\n"
                f"Say yes and I'll check availability, or send me "
                f"the exact date if you had something else in mind \U0001f60a\n\n"
                f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
            )
        except Exception:
            pass
    return (
        f"Hi there!\n\n"
        f"I'd love to help you book! Could you give me a specific date? "
        f"For example: April 15, or 2026-04-15.\n\n"
        f"Once I have that I can check availability and get your "
        f"spot held right away \U0001f30a\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def is_date_confirmation_yes(text: str) -> bool:
    """
    Returns True if the customer's message is a confirmation of the date.
    Handles: yes, yeah, yep, correct, confirmed, sure, ok, okay,
    si, ja, yep, affirmative — case insensitive.
    """
    t = (text or "").strip().lower()
    confirm_words = {
        "yes", "yeah", "yep", "yup", "correct", "confirmed",
        "sure", "ok", "okay", "si", "ja", "affirmative",
        "that's right", "thats right", "right", "exactly"
    }
    # Short message that is just a confirmation word
    if t in confirm_words:
        return True
    # Message starts with a confirmation word
    for word in confirm_words:
        if t.startswith(word + " ") or t.startswith(word + ","):
            return True
    return False


def package_key_from_experience(exp: str) -> str:
    e = (exp or "").lower()
    if "sunset" in e:
        return "sunset_signature_cruise"
    if "half" in e:
        return "half_day_private_charter"
    if "full" in e:
        return "full_day_west_coast_escape"
    return ""

def experience_is_clear(exp: str) -> bool:
    """Returns True if experience maps to a known package key."""
    return bool(package_key_from_experience(exp))


def safe_experience_unclear_reply(provided: str) -> str:
    return (
        f"Hi there!\n\n"
        f"Thanks for reaching out! I want to make sure I book "
        f"the right experience for you \U0001f60a\n\n"
        f"We have three options:\n\n"
        f"\U0001f305 Sunset Signature Cruise \u2014 2.5 hours, departs 17:00\n"
        f"   Perfect for couples and small groups. Drinks and sunset views.\n\n"
        f"\u2693 Half Day Private Charter \u2014 4 hours, departs 09:00\n"
        f"   Flexible itinerary. Great for families and private groups.\n\n"
        f"\U0001f30a Full Day West Coast Escape \u2014 8 hours, departs 08:00\n"
        f"   Full day on the water. Snorkeling, beaches, full experience.\n\n"
        f"Which one sounds right for you?\n\n"
        f"Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
    )


def normalize_date_to_yyyy_mm_dd(date_val: str) -> str:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/Curacao")
    d = (date_val or "").strip().lower()
    now = datetime.now(tz)
    if d == "today":
        return now.strftime("%Y-%m-%d")
    if d == "tomorrow":
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    # Accept already-normalized YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return d
    try:
        parsed = dateparser.parse(date_val, settings={
            "PREFER_DAY_OF_MONTH": "first",
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": "America/Curacao",
            "RETURN_TIME_AS_PERIOD": False,
        })
        if parsed is not None:
            return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass
    return ""

def classify_date_input(date_val: str) -> str:
    """
    Classifies a date string into one of five categories:
      CLEAR_FUTURE      — resolved to a valid future date, proceed normally
      PAST              — resolved to a past date, ask if they meant next occurrence
      IMPLAUSIBLE       — resolved to a date more than 11 months away with no
                          explicit year — likely dateparser pushed it forward
      VAGUE_RESOLVABLE  — relative date that can be calculated from today
                          (next Friday, in two weeks) — confirm the specific date
      VAGUE_NEEDS_INPUT — too vague to resolve (this weekend, next month,
                          Easter, Christmas, summer) — ask for a specific date
    Returns one of the five string constants above.
    """
    from datetime import date as _date, timedelta
    from zoneinfo import ZoneInfo
    import datetime as _datetime
    if not date_val:
        return "VAGUE_NEEDS_INPUT"
    d = date_val.strip().lower()
    tz = ZoneInfo("America/Curacao")
    today = _datetime.datetime.now(tz).date()
    # today/tomorrow — always clear
    if d in ("today", "tomorrow"):
        return "CLEAR_FUTURE"
    # Vague inputs that need a specific date
    VAGUE_PATTERNS = [
        "this weekend", "next weekend", "next month", "this month",
        "next week", "easter", "christmas", "new year", "thanksgiving",
        "summer", "winter", "spring", "autumn", "fall",
        "holiday", "vacation", "soon", "sometime", "flexible",
        "any day", "anytime", "whenever"
    ]
    for pattern in VAGUE_PATTERNS:
        if pattern in d:
            return "VAGUE_NEEDS_INPUT"
    # Try to resolve the date
    resolved_str = normalize_date_to_yyyy_mm_dd(date_val)
    if not resolved_str:
        return "VAGUE_NEEDS_INPUT"
    try:
        resolved = _date.fromisoformat(resolved_str)
    except Exception:
        return "VAGUE_NEEDS_INPUT"
    # Past date
    if resolved < today:
        return "PAST"
    # Check if year was explicitly provided
    has_explicit_year = bool(re.search(r'\b(20\d{2})\b', date_val))
    # If no explicit year and date is more than 11 months away — implausible
    if not has_explicit_year:
        eleven_months = today + timedelta(days=335)
        if resolved > eleven_months:
            return "IMPLAUSIBLE"
    # Resolvable relative dates — "next Friday", "in two weeks"
    RESOLVABLE_PATTERNS = [
        "next friday", "next monday", "next tuesday", "next wednesday",
        "next thursday", "next saturday", "next sunday",
        "in two weeks", "in a week", "in 2 weeks", "in 3 weeks",
        "next friday", "this friday", "this saturday", "this sunday",
        "this monday", "this tuesday", "this wednesday", "this thursday"
    ]
    for pattern in RESOLVABLE_PATTERNS:
        if pattern in d:
            return "VAGUE_RESOLVABLE"
    return "CLEAR_FUTURE"


def default_start_time_for_package(package_key: str) -> str:
    # Demo defaults
    if package_key == "sunset_signature_cruise":
        return "17:00"
    if package_key == "half_day_private_charter":
        return "09:00"
    if package_key == "full_day_west_coast_escape":
        return "08:00"
    return "09:00"

def price_for_package(package_key: str) -> int:
    # Demo pricing (adjust later if needed)
    if package_key == "sunset_signature_cruise":
        return 750
    if package_key == "half_day_private_charter":
        return 950
    if package_key == "full_day_west_coast_escape":
        return 1500
    return 0

def create_calendar_hold(fields_now: dict) -> dict:
    """
    Calls node calendar.js to create a REAL hold event in Google Calendar.
    Returns dict: {ok: bool, eventId?, htmlLink?, error?}
    """
    pkg = package_key_from_experience(fields_now.get("experience"))
    date_iso = normalize_date_to_yyyy_mm_dd(fields_now.get("date"))
    if not pkg:
        return {"ok": False, "error": "Unknown package (experience mapping failed)."}
    if not date_iso:
        return {"ok": False, "error": "Date not recognized. Use today/tomorrow or YYYY-MM-DD."}

    # Past date guard
    try:
        from datetime import date as _date
        booking_date = _date.fromisoformat(date_iso)
        today = _date.today()
        if booking_date < today:
            return {
                "ok": False,
                "error": f"Requested date {date_iso} is in the past."
            }
    except Exception:
        pass  # If date parsing fails here, let calendar.js handle it

    payload = {
        "package_key": pkg,
        "date": date_iso,
        "start_time": default_start_time_for_package(pkg),
        "guests_pax": int(fields_now.get("guests") or 0),
        "customer_name": fields_now.get("customer_name") or "—",
        "contact": f"{fields_now.get('phone','')}".strip() or "—",
        "price_usd": price_for_package(pkg),
    }

    try:
        r = subprocess.run(
            ["node", os.path.join(_SRC_DIR, "calendar.js"), json.dumps(payload)],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "calendar.js failed").strip()[:500]}
        out = (r.stdout or "").strip()
        data = json.loads(out)
        if not data.get("eventId"):
            return {"ok": False, "error": f"calendar.js returned no eventId: {out[:200]}"}
        return {"ok": True, "eventId": data.get("eventId"), "htmlLink": data.get("htmlLink")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


# ========= MAIN LOOP =========
def main():
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (Stable ThreadKey + Merge + Anti-loop).")

    state = load_json(THREAD_STATE_PATH, {"threads": {}})

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
                subj = msg.get("Subject", "") or ""
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

                thread_key = stable_thread_key(msg, from_email, subj)

                log(f"Processed UNSEEN from {from_name} <{from_email}> | {subj}")
                log(f"ThreadKey: {thread_key}")

                threads = state["threads"]
                th = threads.get(thread_key, {
                    "fields": {},
                    "flags": {},
                    "last_customer_hash": "",
                    "reply_times": []  # epoch seconds
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
                        "1) Experience (Half-Day / Sunset / Full-Day)\n"
                        "2) Date\n"
                        "3) Number of guests\n\n"
                        "Warm regards,\nMarina\n"
                    )
                    # reply in-thread (best-effort)
                    smtp_send(from_email, "Re: " + subj, stop_msg,
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    save_json(THREAD_STATE_PATH, state)
                    continue

                intents, fields = detect_intent_and_fields(body)

                # --- Date confirmation intercept ---
                th.setdefault("flags", {})
                if th["flags"].get("awaiting_date_confirmation"):
                    pending_date = th["flags"].get("pending_date", "")
                    pending_original = th["flags"].get("pending_date_original", "")
                    if is_date_confirmation_yes(body):
                        # Customer confirmed — lock the date and clear the flag
                        th["flags"]["awaiting_date_confirmation"] = False
                        if "fields" not in th:
                            th["fields"] = {}
                        th["fields"]["date"] = pending_date
                        # Also merge any new fields from this message
                        new_fields = fields or {}
                        th["fields"].update(
                            {k: v for k, v in new_fields.items()
                             if v is not None and v != "" and k != "date"}
                        )
                        log(f"Date confirmed: {pending_date}")
                        # Fall through to normal booking flow with confirmed date
                    else:
                        # Customer did not confirm — check if they sent a new date
                        new_date = fields.get("date")
                        if new_date:
                            resolved = normalize_date_to_yyyy_mm_dd(new_date)
                            if resolved:
                                if classify_date_input(new_date) in ("VAGUE_RESOLVABLE", "VAGUE_NEEDS_INPUT"):
                                    # Still ambiguous — ask again with new date
                                    th["flags"]["pending_date"] = resolved
                                    th["flags"]["pending_date_original"] = new_date
                                    reply_body = safe_date_confirmation_reply(
                                        resolved, new_date)
                                    smtp_send(from_email, "Re: " + subj, reply_body,
                                              in_reply_to=msg.get("Message-ID"),
                                              references=msg.get("References"))
                                    log(f"Date re-asked (still ambiguous): {resolved}")
                                    th["last_customer_hash"] = customer_hash
                                    th["reply_times"].append(now)
                                    threads[thread_key] = th
                                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                                    save_json(THREAD_STATE_PATH, state)
                                    continue
                                else:
                                    # Explicit year provided — use it directly
                                    th["flags"]["awaiting_date_confirmation"] = False
                                    th["fields"]["date"] = resolved
                                    log(f"Date updated with explicit year: {resolved}")
                                    # Fall through to normal booking flow
                            else:
                                # Could not parse new date — ask again
                                reply_body = safe_date_confirmation_reply(
                                    pending_date, pending_original)
                                smtp_send(from_email, "Re: " + subj, reply_body,
                                          in_reply_to=msg.get("Message-ID"),
                                          references=msg.get("References"))
                                log(f"Date confirmation re-asked (unparseable): {pending_date}")
                                th["last_customer_hash"] = customer_hash
                                th["reply_times"].append(now)
                                threads[thread_key] = th
                                im.uid("store", uid, "+FLAGS", r"(\Seen)")
                                save_json(THREAD_STATE_PATH, state)
                                continue
                        else:
                            # No date in message — ask again
                            reply_body = safe_date_confirmation_reply(
                                pending_date, pending_original)
                            smtp_send(from_email, "Re: " + subj, reply_body,
                                      in_reply_to=msg.get("Message-ID"),
                                      references=msg.get("References"))
                            log(f"Date confirmation re-asked (no date in reply): {pending_date}")
                            th["last_customer_hash"] = customer_hash
                            th["reply_times"].append(now)
                            threads[thread_key] = th
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            save_json(THREAD_STATE_PATH, state)
                            continue

                # Merge fields (union only)
                merged = dict(th.get("fields", {}))
                merged.update({k: v for k, v in fields.items() if v is not None and v != ""})
                th["fields"] = merged
                log(f"Intents: {intents} | Merged fields: {merged}")

                # --- Multi-label intent dispatch ---
                # off_topic: only fire if SOLE intent is off_topic
                if intents == ["off_topic"]:
                    reply_body = safe_out_of_scope_reply()
                    smtp_send(from_email, "Re: " + subj, reply_body,
                              in_reply_to=msg.get("Message-ID"),
                              references=msg.get("References"))
                    log(f"Off-topic -> sent SAFE reply to: {from_email}")
                    bm_logger.log("off_topic_received", email=from_email,
                                  subject=subj, body_snippet=body[:200])
                    sheets_writer.log_event("off_topic_received",
                                            {"email": from_email, "subject": subj})
                else:
                    # Handle each non-off_topic intent present
                    # social: acknowledge warmly before anything else
                    if "social" in intents and not any(
                            i in intents for i in
                            ("booking", "inquiry", "cancellation",
                             "reschedule", "complaint")):
                        # Pure social — no action needed, just warm reply
                        reply_body = safe_social_reply()
                        smtp_send(from_email, "Re: " + subj, reply_body,
                                  in_reply_to=msg.get("Message-ID"),
                                  references=msg.get("References"))
                        log(f"Social -> sent warm reply to: {from_email}")
                        bm_logger.log("social_received", email=from_email,
                                      subject=subj, body_snippet=body[:200])
                        sheets_writer.log_event("social_received",
                                                {"email": from_email, "subject": subj})
                    # complaint: log and reply (can combine with other intents)
                    if "complaint" in intents:
                        reply_body = safe_complaint_reply()
                        smtp_send(from_email, "Re: " + subj, reply_body,
                                  in_reply_to=msg.get("Message-ID"),
                                  references=msg.get("References"))
                        log(f"Complaint -> sent empathetic reply to: {from_email}")
                        bm_logger.log("complaint_received", email=from_email,
                                      subject=subj, body_snippet=body[:200])
                        sheets_writer.log_complaint({"email": from_email,
                                                     "subject": subj,
                                                     "body_snippet": body[:200]})
                    # cancellation or reschedule: flag for human, send acknowledgement
                    if "cancellation" in intents or "reschedule" in intents:
                        action = "cancellation" if "cancellation" in intents else "reschedule"
                        reply_body = safe_change_request_reply(action)
                        smtp_send(from_email, "Re: " + subj, reply_body,
                                  in_reply_to=msg.get("Message-ID"),
                                  references=msg.get("References"))
                        log(f"{action.title()} request -> sent acknowledgement to: {from_email}")
                        bm_logger.log(f"{action}_requested", email=from_email,
                                      subject=subj, body_snippet=body[:200])
                        sheets_writer.log_event(f"{action}_requested",
                                                {"email": from_email, "subject": subj,
                                                 "body_snippet": body[:200]})
                    # inquiry: answer pre-sales question
                    if "inquiry" in intents and "booking" not in intents:
                        reply_body = safe_inquiry_reply()
                        smtp_send(from_email, "Re: " + subj, reply_body,
                                  in_reply_to=msg.get("Message-ID"),
                                  references=msg.get("References"))
                        log(f"Inquiry -> sent packages reply to: {from_email}")
                        bm_logger.log("inquiry_received", email=from_email,
                                      subject=subj, body_snippet=body[:200])
                        sheets_writer.log_event("inquiry_received",
                                                {"email": from_email, "subject": subj})
                    # booking: run the full booking flow (unchanged logic)
                    if "booking" in intents:
                        # --- Date classification check ---
                        raw_date = fields.get("date") or merged.get("date", "")
                        if raw_date and not th["flags"].get("awaiting_date_confirmation"):
                            date_class = classify_date_input(raw_date)
                            resolved_date = normalize_date_to_yyyy_mm_dd(raw_date)
                            if date_class == "PAST":
                                reply_body = safe_date_past_reply(resolved_date or "", raw_date)
                                smtp_send(from_email, "Re: " + subj, reply_body,
                                          in_reply_to=msg.get("Message-ID"),
                                          references=msg.get("References"))
                                log(f"Past date detected: '{raw_date}' -> asking for correction")
                                bm_logger.log("date_past_detected", email=from_email,
                                              subject=subj, raw_date=raw_date)
                                sheets_writer.log_event("date_past_detected",
                                                        {"email": from_email, "subject": subj,
                                                         "raw_date": raw_date})
                                th["last_customer_hash"] = customer_hash
                                th["reply_times"].append(now)
                                threads[thread_key] = th
                                im.uid("store", uid, "+FLAGS", r"(\Seen)")
                                save_json(THREAD_STATE_PATH, state)
                                continue
                            elif date_class == "IMPLAUSIBLE":
                                th["flags"]["awaiting_date_confirmation"] = True
                                th["flags"]["pending_date"] = resolved_date
                                th["flags"]["pending_date_original"] = raw_date
                                reply_body = safe_date_implausible_reply(resolved_date, raw_date)
                                smtp_send(from_email, "Re: " + subj, reply_body,
                                          in_reply_to=msg.get("Message-ID"),
                                          references=msg.get("References"))
                                log(f"Implausible date: '{raw_date}' -> {resolved_date}")
                                bm_logger.log("date_implausible_detected", email=from_email,
                                              subject=subj, raw_date=raw_date,
                                              resolved_date=resolved_date)
                                sheets_writer.log_event("date_implausible_detected",
                                                        {"email": from_email, "subject": subj,
                                                         "raw_date": raw_date,
                                                         "resolved_date": resolved_date})
                                th["last_customer_hash"] = customer_hash
                                th["reply_times"].append(now)
                                threads[thread_key] = th
                                im.uid("store", uid, "+FLAGS", r"(\Seen)")
                                save_json(THREAD_STATE_PATH, state)
                                continue
                            elif date_class in ("VAGUE_NEEDS_INPUT", "VAGUE_RESOLVABLE"):
                                th["flags"]["awaiting_date_confirmation"] = True
                                th["flags"]["pending_date"] = resolved_date or ""
                                th["flags"]["pending_date_original"] = raw_date
                                reply_body = safe_date_vague_reply(
                                    raw_date,
                                    resolved_date if date_class == "VAGUE_RESOLVABLE" else ""
                                )
                                smtp_send(from_email, "Re: " + subj, reply_body,
                                          in_reply_to=msg.get("Message-ID"),
                                          references=msg.get("References"))
                                log(f"Vague date ({date_class}): '{raw_date}' -> asking for specific date")
                                bm_logger.log("date_vague_detected", email=from_email,
                                              subject=subj, raw_date=raw_date,
                                              classification=date_class)
                                sheets_writer.log_event("date_vague_detected",
                                                        {"email": from_email, "subject": subj,
                                                         "raw_date": raw_date,
                                                         "classification": date_class})
                                th["last_customer_hash"] = customer_hash
                                th["reply_times"].append(now)
                                threads[thread_key] = th
                                im.uid("store", uid, "+FLAGS", r"(\Seen)")
                                save_json(THREAD_STATE_PATH, state)
                                continue
                            # CLEAR_FUTURE — proceed normally, no action needed
                        # --- end date classification check ---
                        # --- Experience clarity check ---
                        provided_experience = merged.get("experience", "")
                        if (provided_experience
                                and not experience_is_clear(provided_experience)
                                and not th["flags"].get("awaiting_experience_clarification")):
                            th["flags"]["awaiting_experience_clarification"] = True
                            reply_body = safe_experience_unclear_reply(provided_experience)
                            smtp_send(from_email, "Re: " + subj, reply_body,
                                      in_reply_to=msg.get("Message-ID"),
                                      references=msg.get("References"))
                            log(f"Experience unclear: '{provided_experience}' -> asking for clarification")
                            bm_logger.log("experience_unclear", email=from_email,
                                          subject=subj, provided=provided_experience)
                            sheets_writer.log_event("experience_unclear",
                                                    {"email": from_email, "subject": subj,
                                                     "provided": provided_experience})
                            th["last_customer_hash"] = customer_hash
                            th["reply_times"].append(now)
                            threads[thread_key] = th
                            im.uid("store", uid, "+FLAGS", r"(\Seen)")
                            save_json(THREAD_STATE_PATH, state)
                            continue
                        # --- end experience clarity check ---
                        # --- Large group check ---
                        guest_count = merged.get("guests")
                        if guest_count is not None:
                            try:
                                guest_count = int(guest_count)
                                if guest_count >= GROUP_BOOKING_THRESHOLD:
                                    reply_body = safe_large_group_reply(guest_count)
                                    smtp_send(from_email, "Re: " + subj, reply_body,
                                              in_reply_to=msg.get("Message-ID"),
                                              references=msg.get("References"))
                                    log(f"Large group detected: {guest_count} guests -> flagging human")
                                    bm_logger.log("large_group_detected", email=from_email,
                                                  subject=subj, guests=guest_count)
                                    sheets_writer.log_complaint({
                                        "email": from_email,
                                        "subject": subj,
                                        "body_snippet": f"Large group booking request: {guest_count} guests"
                                    })
                                    th["last_customer_hash"] = customer_hash
                                    th["reply_times"].append(now)
                                    threads[thread_key] = th
                                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                                    save_json(THREAD_STATE_PATH, state)
                                    continue
                            except (ValueError, TypeError):
                                pass
                        # --- end large group check ---
                        missing = [f for f in REQUIRED_FIELDS if f not in merged]

                        if missing:
                            # Ask for ALL missing fields at once, with what we already have
                            have_summary = []
                            if "experience" in merged: have_summary.append(f"Experience: {merged['experience']}")
                            if "date" in merged: have_summary.append(f"Date: {merged['date']}")
                            if "guests" in merged: have_summary.append(f"Guests: {merged['guests']}")
                            have_txt = ("\n".join(have_summary) + "\n\n") if have_summary else ""

                            ask = (
                                "Hi,\n\n"
                                "Thanks — I can help you book this.\n\n"
                                + have_txt +
                                "To proceed, please reply with:\n"
                            )
                            if "experience" in missing:
                                ask += "- Which experience you want (Half-Day / Sunset / Full-Day)\n"
                            if "date" in missing:
                                ask += "- Your preferred date\n"
                            if "guests" in missing:
                                ask += "- Number of guests\n"

                            ask += "\nWarm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"

                            smtp_send(from_email, "Re: " + subj, ask,
                                      in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                            log(f"Booking intent -> requested missing fields (all at once): {missing}")
                            bm_logger.log(
                                "missing_fields_requested",
                                email=from_email,
                                subject=subj,
                                missing=missing,
                                fields_so_far=list(merged.keys())
                            )
                            sheets_writer.log_event("missing_fields_requested", {
                                "email": from_email,
                                "subject": subj,
                                "missing": missing,
                            })

                        else:
                            # We have all required booking info.
                            # Deterministic reply: NEVER re-ask known fields. Only ask for missing extras.
                            th.setdefault("flags", {})
                            fields_now = th.get("fields", {}) or {}

                            # If we already created a hold for this thread, do not create/re-confirm repeatedly.
                            if th["flags"].get("hold_created"):
                                msg2 = (
                                    "Hi\n\n"
                                    "Your provisional hold is already in place. If you need to change anything (date/time/guests), "
                                    "please reply with the updated value(s) in a single message.\n\n"
                                    "Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
                                )
                                smtp_send(from_email, "Re: " + subj, msg2,
                                          in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                                log(f"Hold already created -> sent no-loop acknowledgement to: {from_email}")
                            else:
                                extras_missing = []
                                if not fields_now.get("customer_name"):
                                    extras_missing.append("customer_name")
                                if not fields_now.get("phone"):
                                    extras_missing.append("phone")

                                # If extras missing, ask ONLY for extras. Do NOT claim a hold exists.
                                if extras_missing:
                                    ask2 = (
                                        "Hi,\n\n"
                                        "Perfect — I can create your provisional hold as soon as I have:\n"
                                    )
                                    if "customer_name" in extras_missing:
                                        ask2 += "- Guest name for the booking\n"
                                    if "phone" in extras_missing:
                                        ask2 += "- Contact phone number (e.g. +599...)\n"
                                    ask2 += "\nWarm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"

                                    smtp_send(from_email, "Re: " + subj, ask2,
                                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                                    log(f"Booking intent -> requested missing extras: {extras_missing}")

                                else:
                                    # Create REAL calendar hold
                                    bm_logger.log(
                                        "booking_attempted",
                                        email=from_email,
                                        subject=subj,
                                        experience=fields_now.get("experience"),
                                        date=fields_now.get("date"),
                                        guests=fields_now.get("guests"),
                                        customer_name=fields_now.get("customer_name"),
                                        phone=fields_now.get("phone"),
                                        special_requests=fields_now.get("special_requests")
                                    )
                                    sheets_writer.log_event("booking_attempted", {
                                        "email": from_email,
                                        "subject": subj,
                                        "experience": fields_now.get("experience"),
                                        "date": fields_now.get("date"),
                                    })
                                    res = create_calendar_hold(fields_now)
                                    if not res.get("ok"):
                                        err = (res.get("error","unknown") or "unknown")

                                        # ---- BM-008: Deterministic alternatives on UNAVAILABLE ----
                                        alt_txt = ""
                                        if "UNAVAILABLE:" in err:
                                            try:
                                                from datetime import datetime, timedelta
                                                from zoneinfo import ZoneInfo
                                                tz = ZoneInfo("America/Curacao")
                                                base_iso = normalize_date_to_yyyy_mm_dd(fields_now.get("date"))
                                                if base_iso:
                                                    base_dt = datetime.strptime(base_iso, "%Y-%m-%d").replace(tzinfo=tz)
                                                else:
                                                    base_dt = datetime.now(tz)
                                                opts = [(base_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in (1,2,3)]
                                                alt_txt = "Here are 3 alternatives at the same start time:\n" + "\n".join([f"- {d}" for d in opts]) + "\n\n"
                                            except Exception:
                                                alt_txt = "Here are 3 alternatives for the next days at the same start time:\n- +1 day\n- +2 days\n- +3 days\n\n"
                                        # ---- end BM-008 ----

                                        msg_fail = (
                                            "Hi,\n\n"
                                            "That time slot is not available.\n\n"
                                            + alt_txt +
                                            "Reply with ONE of the dates above (YYYY-MM-DD), or send a different date/time and I'll check it.\n\n"
                                            "Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
                                        )
                                        smtp_send(from_email, "Re: " + subj, msg_fail,
                                                  in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                                        log(f"Hold create FAILED for {from_email}: {res.get('error')}")
                                        bm_logger.log(
                                            "hold_failed",
                                            email=from_email,
                                            subject=subj,
                                            error=res.get("error"),
                                            experience=fields_now.get("experience"),
                                            date=fields_now.get("date"),
                                            guests=fields_now.get("guests")
                                        )
                                        sheets_writer.log_hold_failed({
                                            "email": from_email,
                                            "subject": subj,
                                            "experience": fields_now.get("experience"),
                                            "date": fields_now.get("date"),
                                            "guests": fields_now.get("guests"),
                                            "error": res.get("error"),
                                        })
                                    else:
                                        th["flags"]["hold_created"] = True
                                        th["flags"]["event_id"] = res.get("eventId")
                                        th["flags"]["event_link"] = res.get("htmlLink")

                                        # ---- BM-006: Deterministic payment stub (one link per event_id) ----
                                        event_id = th["flags"]["event_id"]
                                        pkg_key = package_key_from_experience(fields_now.get("experience"))
                                        amount_usd = price_for_package(pkg_key)
                                        pay = payment_stub.generate_payment_link(event_id, amount_usd)
                                        pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                                        th["flags"]["payment_id"] = pay.get("payment_id")
                                        th["flags"]["payment_link"] = pay_link
                                        th["flags"]["payment_status"] = pay.get("status")

                                        # ---- BM-014: Structured logging ----
                                        bm_logger.log(
                                            "hold_created",
                                            email=from_email,
                                            subject=subj,
                                            event_id=th["flags"].get("event_id"),
                                            html_link=th["flags"].get("event_link"),
                                            payment_id=th["flags"].get("payment_id"),
                                            payment_link=th["flags"].get("payment_link"),
                                            experience=fields_now.get("experience"),
                                            date=fields_now.get("date"),
                                            guests=fields_now.get("guests"),
                                            customer_name=fields_now.get("customer_name"),
                                            phone=fields_now.get("phone"),
                                            special_requests=fields_now.get("special_requests")
                                        )
                                        sheets_writer.log_hold_created({
                                            "email": from_email,
                                            "subject": subj,
                                            "customer_name": fields_now.get("customer_name"),
                                            "experience": fields_now.get("experience"),
                                            "date": fields_now.get("date"),
                                            "guests": fields_now.get("guests"),
                                            "phone": fields_now.get("phone"),
                                            "special_requests": fields_now.get("special_requests"),
                                            "html_link": th["flags"].get("event_link"),
                                            "payment_link": th["flags"].get("payment_link"),
                                        })
                                        # ---- end BM-014 ----
                                        # ---- end BM-006 ----

                                        exp = fields_now.get("experience", "—")
                                        guests = fields_now.get("guests", "—")
                                        date = normalize_date_to_yyyy_mm_dd(fields_now.get("date")) or fields_now.get("date","—")
                                        name = fields_now.get("customer_name", "—")

                                        social_opener = (
                                            "That means so much to us \u2014 thank you! "
                                            "We can't wait to have you on board. \U0001f30a\n\n"
                                        ) if "social" in intents else ""
                                        special_note = (
                                            f"\U0001f4dd We've noted your special request: {fields_now.get('special_requests')}\n\n"
                                        ) if fields_now.get("special_requests") else ""
                                        confirm = (
                                            f"Hi {name},\n\n"
                                            + social_opener +
                                            "\u2705 Your provisional hold has been created \u2014 "
                                            "you're one step closer to an unforgettable day on the water!\n\n"
                                            f"- **Package:** {exp}\n"
                                            f"- **Date:** {date}\n"
                                            f"- **Guests:** {guests}\n\n"
                                            + special_note +
                                            "Your hold is valid for 6 hours. To confirm your booking, "
                                            "please complete the payment using the link below:\n\n"
                                            f"\U0001f4b3 Payment link: {th['flags'].get('payment_link', '')}\n\n"
                                            f"Calendar link: {res.get('htmlLink','')}\n\n"
                                            "If you have any questions at all, just reply to this email "
                                            "and we'll take care of you.\n\n"
                                            "See you on the water! \U0001f41f\n\n"
                                            "Warm regards,\nMarina\nBlueMarlin Tours Cura\u00e7ao\n"
                                        )

                                        smtp_send(from_email, "Re: " + subj, confirm,
                                                  in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                                        log(f"Hold CREATED for {from_email}: eventId={res.get('eventId')}")

                # mark seen + persist thread state
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
