#!/usr/bin/env python3
import imaplib, email, urllib.request, urllib.parse, json, subprocess, time, os, re, hashlib
from email.utils import parseaddr
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib, base64

# ========= CONFIG =========
CLIENT_ID = "28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID = "caac06b5-1420-4223-9dcc-ba4a670ec26a"
EMAIL_ADDR = "hello@wetakeyourjob.com"

REFRESH_TOKEN_PATH = "/root/.openclaw/azure_refresh_token.txt"
SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587

MAILBOX = "INBOX"
POLL_INTERVAL = 30

STATE_DIR = "/root/.openclaw"
THREAD_STATE_PATH = os.path.join(STATE_DIR, "email_thread_state.json")

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
    # 1) Outlook stable conversation key
    conv = msg.get("Conversation-Index")
    if conv:
        return "conv:" + conv.strip()

    # 2) Root message-id from References (first id)
    refs = msg.get("References", "") or ""
    ref_ids = re.findall(r"<[^>]+>", refs)
    if ref_ids:
        return "refroot:" + ref_ids[0].strip("<>")

    # 3) In-Reply-To
    irt = msg.get("In-Reply-To")
    if irt:
        m = re.search(r"<[^>]+>", irt)
        if m:
            return "irt:" + m.group(0).strip("<>")
        return "irt:" + irt.strip()

    # 4) Fallback: normalized subject + sender
    return "fallback:{}:{}".format(from_email.lower(), normalize_subject(subject).lower())

def detect_intent_and_fields(text: str):
    """
    Very simple deterministic extraction.
    Returns: (intent, fields_dict)
      intent: "booking" | "general" | "out_of_scope"
    """
    t = (text or "").lower()

    # Out-of-scope hard filter (jokes, games, etc.)
    if re.search(r"\bjoke\b|\briddle\b|\bfunny\b|\bmeme\b|\bweather\b|\bcrypto\b|\bpolitics\b", t):
        return ("out_of_scope", {})

    fields = {}

    # Guests
    m = re.search(r"\b(\d{1,2})\s*(guests|people|pax)\b", t)
    if m:
        fields["guests"] = int(m.group(1))

    # Date (minimal demo parsing)
    if "tomorrow" in t:
        fields["date"] = "tomorrow"
    elif "today" in t:
        fields["date"] = "today"

    # Experience keywords
    if "sunset" in t:
        fields["experience"] = "Sunset Signature Cruise"
    elif "half" in t and "day" in t:
        fields["experience"] = "Half-Day Private Charter"
    elif "full" in t and "day" in t:
        fields["experience"] = "Full-Day West Coast Escape"

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

    r = subprocess.run(
        ["openclaw", "agent", "--session-id", SESSION_ID, "--message", prompt, "--local"],
        capture_output=True, text=True, timeout=120
    )
    out = (r.stdout or "").strip()
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
                        # We have all required info -> hand to LLM to generate a booking/hold next step message
                        mode = "booking_confirm"
                        llm_reply = ask_marina_llm(from_email, subj, body, mode=mode)
                        smtp_send(from_email, "Re: " + subj, llm_reply,
                                  in_reply_to=msg.get("Message-ID"), references=msg.get("References"))
                        log(f"Booking intent -> replied with confirmation/next-steps to: {from_email}")

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
