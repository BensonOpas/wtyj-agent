# wtyj/agents/marina/email_adapter.py
# Brief 189 — Email channel adapter layer.
# Connection (IMAP/OAuth), sending (SMTP), and parsing functions extracted
# from email_poller.py. The orchestrator (main loop, booking flow, thread
# management) stays in email_poller.py and imports from here.

import imaplib
import smtplib
import base64
import hashlib
import json
import os
import re
import urllib.request
import urllib.parse
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid

from shared import agent_identity


# ========= CONSTANTS =========
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID", "28e94343-2f77-444c-ac32-58b7bed33b65")
TENANT_ID = os.environ.get("AZURE_TENANT_ID", "caac06b5-1420-4223-9dcc-ba4a670ec26a")
EMAIL_ADDR = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")  # Brief 204: Gmail app password (presence = Gmail mode)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "..", "config"))
REFRESH_TOKEN_PATH = os.path.join(_CONFIG_DIR, "azure_refresh_token.txt")
SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587

# Brief 204: Gmail hosts — used when EMAIL_PASSWORD is set (Gmail app password mode)
GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_SMTP_HOST = "smtp.gmail.com"


# ========= UTILITIES =========
def log(msg):
    print(msg, flush=True)


def _decode_subj(raw):
    parts = []
    for data, charset in _decode_header(raw or ""):
        if isinstance(data, bytes):
            parts.append(data.decode(charset or "utf-8", errors="ignore"))
        else:
            parts.append(data)
    return "".join(parts)


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


def customer_facing_agent_name() -> str:
    """Return the effective tenant assistant name for outbound email.

    Nr3/Nr2 agent identity is the authority. The ICP bridge helper has its own
    short cache, so this is safe to call during send without turning SMTP into a
    config synchronization problem. If the bridge is unavailable, the helper
    falls back to local client.json and finally the platform default.
    """
    try:
        from shared import icp_overrides

        return agent_identity.effective_agent_name(icp_overrides.fetch_overrides())
    except Exception:
        return agent_identity.local_agent_name()


# ========= CONNECTION =========
def get_refresh_token():
    return open(REFRESH_TOKEN_PATH).read().strip()


def oauth_token(scope: str) -> str:
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "refresh_token": get_refresh_token(),
        "grant_type": "refresh_token",
        "scope": scope
    }).encode()
    try:
        resp = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token", data)
        ).read())
    except Exception as e:
        log(f"OAuth token request failed: {e}")
        raise
    if "refresh_token" in resp:
        try:
            with open(REFRESH_TOKEN_PATH, "w") as f:
                f.write(resp["refresh_token"])
        except Exception as e:
            log(f"Failed to save new refresh token: {e}")
    if "access_token" not in resp:
        log(f"OAuth response missing access_token: {resp.get('error', 'unknown')}")
        raise RuntimeError(f"OAuth failed: {resp.get('error_description', 'no access_token')}")
    return resp["access_token"]


def imap_connect():
    """Brief 204: Gmail app password mode when EMAIL_PASSWORD is set; else
    Microsoft OAuth XOAUTH2 (existing path)."""
    if EMAIL_PASSWORD:
        # Gmail app password — basic LOGIN auth. Strip whitespace because Google
        # formats app passwords as 4 groups of 4 chars separated by spaces.
        password = EMAIL_PASSWORD.replace(" ", "")
        im = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, IMAP_PORT)
        im.login(EMAIL_ADDR, password)
        return im
    # Existing Microsoft OAuth path
    token = oauth_token("offline_access https://outlook.office.com/IMAP.AccessAsUser.All")
    auth_string = f"user={EMAIL_ADDR}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
    im = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    im.authenticate("XOAUTH2", lambda _: auth_string)
    return im


# ========= SENDING =========
def smtp_send(to_addr: str, subject: str, body: str, in_reply_to=None, references=None, reply_to=None,
              html_body: str = None):
    """Brief 204: Gmail app password mode when EMAIL_PASSWORD is set; else
    Microsoft OAuth XOAUTH2 (existing path).

    Brief 243: when html_body is provided, send multipart/alternative
    with both text/plain and text/html parts. Email clients render the
    HTML version; clients that strip HTML (or text-only readers) get the
    plain `body`. When html_body is None (default), current single-part
    plain-text behavior is unchanged."""
    # Brief 243: switch to multipart/alternative when an HTML body is
    # supplied, so the text part is the explicit fallback. Default
    # MIMEMultipart() subtype is 'mixed' which is wrong for this
    # purpose - clients may show both parts as separate attachments.
    if not EMAIL_ADDR or "@" not in EMAIL_ADDR:
        raise RuntimeError("SMTP sender email is not configured")
    if html_body is not None:
        msg = MIMEMultipart('alternative')
    else:
        msg = MIMEMultipart()
    msg["From"] = formataddr((customer_facing_agent_name(), EMAIL_ADDR))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=EMAIL_ADDR.split("@")[1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if reply_to:
        msg["Reply-To"] = reply_to
    # Brief 243: text part FIRST so HTML-stripping clients pick it as
    # the body. Text-only clients ignore the HTML and pick text.
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body is not None:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    if EMAIL_PASSWORD:
        # Gmail app password — basic LOGIN auth via STARTTLS.
        password = EMAIL_PASSWORD.replace(" ", "")
        s = smtplib.SMTP(GMAIL_SMTP_HOST, SMTP_PORT, timeout=30)
        s.ehlo(); s.starttls(); s.ehlo()
        s.login(EMAIL_ADDR, password)
        s.sendmail(EMAIL_ADDR, [to_addr], msg.as_string())
        s.quit()
        return

    # Existing Microsoft OAuth XOAUTH2 path
    token = oauth_token("offline_access https://outlook.office.com/SMTP.Send")
    auth_string = f"user={EMAIL_ADDR}\x01auth=Bearer {token}\x01\x01"
    auth_b64 = base64.b64encode(auth_string.encode("ascii")).decode("ascii")
    s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
    s.ehlo(); s.starttls(); s.ehlo()
    code, resp = s.docmd("AUTH", "XOAUTH2 " + auth_b64)
    if code != 235:
        s.quit()
        raise RuntimeError(f"SMTP AUTH failed: {code} {resp!r}")
    s.sendmail(EMAIL_ADDR, [to_addr], msg.as_string())
    s.quit()


# ========= PARSING =========
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


def _is_new_email(msg) -> bool:
    """Return True if the message has no reply headers (brand-new email)."""
    refs = (msg.get("References") or "").strip()
    irt = (msg.get("In-Reply-To") or "").strip()
    return not refs and not irt
