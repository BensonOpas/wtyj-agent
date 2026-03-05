#!/usr/bin/env python3
# FILE: email_poller.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 025
# DEPENDS ON: state_registry.py (Brief 004)
# DEPENDS ON: payment_stub.py (original)
# DEPENDS ON: bm_logger.py (original)
# DEPENDS ON: marina_agent.py (Brief 023)
# DEPENDS ON: config_loader.py (Brief 022)
# DEPENDS ON: calendar.js (original)
# IMPORTS FROM: state_registry.py (Brief 004)
# IMPORTS FROM: payment_stub.py (original)
# IMPORTS FROM: bm_logger.py (original)
# IMPORTS FROM: marina_agent.py (Brief 023)
# IMPORTS FROM: config_loader.py (Brief 022)
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
import marina_agent
import config_loader
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
    msg["From"] = "Marina — BlueFinn Charters Curaçao <{}>".format(EMAIL_ADDR)
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


def create_calendar_hold(fields_now: dict) -> dict:
    """
    Calls node calendar.js to create a hold event in Google Calendar.
    Returns dict: {ok: bool, eventId?, htmlLink?, error?}
    """
    trip_key = fields_now.get("trip_key", "")
    if not trip_key:
        return {"ok": False, "error": "No trip_key in fields — cannot create hold."}

    trip = config_loader.get_trip(trip_key)
    departures = trip.get("departures", [])
    start_time = departures[0].get("time", "09:00") if departures else "09:00"
    price_usd = trip.get("price_adult_usd", 0)

    payload = {
        "package_key": trip_key,
        "date": fields_now.get("date", ""),
        "start_time": start_time,
        "guests_pax": int(fields_now.get("guests") or 0),
        "customer_name": fields_now.get("customer_name") or "\u2014",
        "contact": f"{fields_now.get('phone', '')}".strip() or "\u2014",
        "price_usd": price_usd,
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
    log("Email poller started. UNSEEN-based AUTO-REPLY mode (marina_agent unified call).")

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
                    "reply_times": []
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

                # Step 1: Call marina_agent (single Claude call per message)
                result = marina_agent.process_message(
                    from_email, subj, body,
                    th.get("fields", {}), th.get("flags", {})
                )

                # Step 2: Merge fields (existing non-empty values are not overwritten)
                th.setdefault("fields", {})
                new_fields = result.get("fields", {}) or {}
                for k, v in new_fields.items():
                    if v is not None and v != "":
                        if not th["fields"].get(k):
                            th["fields"][k] = v

                # Step 3: Persist flags
                th.setdefault("flags", {})
                new_flags = result.get("flags", {}) or {}
                th["flags"].update(new_flags)

                log(f"Intents: {result.get('intents')} | Fields: {th['fields']}")

                # Step 4: requires_human check
                if result.get("requires_human"):
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                    bm_logger.log("human_required", email=from_email, subject=subj,
                                  internal_note=result.get("internal_note", ""))
                    sheets_writer.log_event("human_required", {"email": from_email, "subject": subj})
                    im.uid("store", uid, "+FLAGS", r"(\Seen)")
                    th["reply_times"].append(now)
                    th["last_customer_hash"] = customer_hash
                    threads[thread_key] = th
                    save_json(THREAD_STATE_PATH, state)
                    continue

                # Step 5: Booking flow
                if "booking" in result.get("intents", []):
                    fields_now = th["fields"]
                    if (fields_now.get("experience") and fields_now.get("date")
                            and fields_now.get("guests") and fields_now.get("trip_key")
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
                        res = create_calendar_hold(fields_now)
                        if not res.get("ok"):
                            bm_logger.log(
                                "hold_failed",
                                email=from_email, subject=subj,
                                error=res.get("error"),
                                experience=fields_now.get("experience"),
                                date=fields_now.get("date"),
                                guests=fields_now.get("guests"),
                            )
                            sheets_writer.log_hold_failed({
                                "email": from_email, "subject": subj,
                                "experience": fields_now.get("experience"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "error": res.get("error"),
                            })
                            smtp_send(from_email, "Re: " + subj, result["reply"],
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
                                "email": from_email, "subject": subj,
                                "customer_name": fields_now.get("customer_name"),
                                "experience": fields_now.get("experience"),
                                "date": fields_now.get("date"),
                                "guests": fields_now.get("guests"),
                                "phone": fields_now.get("phone"),
                                "special_requests": fields_now.get("special_requests"),
                                "html_link": th["flags"].get("event_link"),
                                "payment_link": th["flags"].get("payment_link"),
                            })
                            log(f"Hold CREATED for {from_email}: eventId={res.get('eventId')}")

                    # Send Claude's reply for all booking sub-cases
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))

                # Step 6: All other intents
                else:
                    smtp_send(from_email, "Re: " + subj, result["reply"],
                              in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
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
