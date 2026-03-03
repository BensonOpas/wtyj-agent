#!/usr/bin/env python3
# FILE: email_poller.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 006
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
import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import claude_client

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
MAX_REPLIES_PER_THREAD = 3
REPLY_WINDOW_SECONDS = 10 * 60

# Booking fields we require to proceed
REQUIRED_FIELDS = ["experience", "date", "guests"]

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



def detect_intent_and_fields(text: str):
    from marina_extractor import extract_fields

    t = (text or "").lower()

    # Hard out-of-scope filter stays
    if re.search(r"joke|riddle|funny|meme|weather|crypto|politics", t):
        return ("out_of_scope", {})

    fields = extract_fields(text) or {}

    # Merge adults + kids into guests
    if "adults" in fields or "kids" in fields:
        adults = int(fields.get("adults", 0) or 0)
        kids = int(fields.get("kids", 0) or 0)
        fields["guests"] = adults + kids

    # Determine intent
    booking_words = ["book", "booking", "reserve", "reservation", "availability", "charter", "boat", "trip", "cruise"]
    intent = "booking" if any(w in t for w in booking_words) or fields else "general"

    return (intent, fields)

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
        "If you share your preferred date, number of guests, and which experience you’re interested in, I’ll help right away.\n\n"
        "Warm regards,\n"
        "Marina\n"
        "BlueMarlin Tours Curaçao\n"
    )


def package_key_from_experience(exp: str) -> str:
    e = (exp or "").lower()
    if "sunset" in e:
        return "sunset_signature_cruise"
    if "half" in e:
        return "half_day_private_charter"
    if "full" in e:
        return "full_day_west_coast_escape"
    return ""

def normalize_date_to_yyyy_mm_dd(date_val: str) -> str:
    # Minimal demo normalization
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
    return ""

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

                intent, fields = detect_intent_and_fields(body)

                # Merge fields (union only)
                merged = dict(th.get("fields", {}))
                merged.update({k: v for k, v in fields.items() if v is not None and v != ""})
                th["fields"] = merged
                log(f"Merged fields: {merged}")

                if intent == "out_of_scope":
                    reply_body = safe_out_of_scope_reply()
                    smtp_send(from_email, "Re: " + subj, reply_body,
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    log(f"Out-of-scope -> sent SAFE reply to: {from_email}")

                elif intent in ("booking", "general"):
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

                        ask += "\nWarm regards,\nMarina\nBlueMarlin Tours Curaçao\n"

                        smtp_send(from_email, "Re: " + subj, ask,
                                  in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                        log(f"Booking intent -> requested missing fields (all at once): {missing}")

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
                                "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
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
                                ask2 += "\nWarm regards,\nMarina\nBlueMarlin Tours Curaçao\n"

                                smtp_send(from_email, "Re: " + subj, ask2,
                                          in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                                log(f"Booking intent -> requested missing extras: {extras_missing}")

                            else:
                                # Create REAL calendar hold
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
                                        "Reply with ONE of the dates above (YYYY-MM-DD), or send a different date/time and I’ll check it.\n\n"
                                        f"(Internal note: {err})\n\n"
                                        "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
                                    )
                                    smtp_send(from_email, "Re: " + subj, msg_fail,
                                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                                    log(f"Hold create FAILED for {from_email}: {res.get('error')}")
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
                                        event_id=th["flags"].get("event_id"),
                                        payment_id=th["flags"].get("payment_id"),
                                        email=from_email,
                                        subject=subj
                                    )
                                    # ---- end BM-014 ----
                                    # ---- end BM-006 ----

                                    exp = fields_now.get("experience", "—")
                                    guests = fields_now.get("guests", "—")
                                    date = normalize_date_to_yyyy_mm_dd(fields_now.get("date")) or fields_now.get("date","—")
                                    name = fields_now.get("customer_name", "—")

                                    confirm = (
                                        "Hi,\n\n"
                                        "✅ Your provisional hold has been created (valid for 6 hours).\n\n"
                                        f"- **Package:** {exp}\n"
                                        f"- **Guests:** {guests}\n"
                                        f"- **Date:** {date}\n"
                                        f"- **Name:** {name}\n\n"
                                        f"Calendar link (internal): {res.get('htmlLink','')}\n\n"
                                        f"Payment status: {th['flags'].get('payment_status', 'pending')}\n"
                                        f"Payment link: {th['flags'].get('payment_link', '')}\n\n"
                                        "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
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
