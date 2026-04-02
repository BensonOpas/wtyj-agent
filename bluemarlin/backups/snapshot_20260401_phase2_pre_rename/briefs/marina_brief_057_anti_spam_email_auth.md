# BRIEF 057 — Anti Email-Spam Paper Trail
**Status:** Draft
**Files:** `src/email_poller.py`, `briefs/INFRA.md`
**Depends on:** —
**Blocks:** —

## Context

Marina's outbound emails from hello@wetakeyourjob.com were landing in spam during
Gmail testing. Root causes: missing email authentication records (SPF, DKIM, DMARC)
on the sending domain, and outbound emails missing a Message-ID header (RFC 5322
violation). The domain is registered on GoDaddy (DNS managed there) and connected
to Microsoft 365.

## Why This Approach

Email authentication (SPF + DKIM + DMARC) is the standard deliverability fix for
domains sending via Microsoft 365. SPF tells receivers that M365 is authorised to
send for wetakeyourjob.com. DKIM adds a cryptographic signature to each outbound
email that Gmail verifies. DMARC ties both together and provides a reporting channel.
These are DNS-only changes — already completed by operator. No source code required
for authentication.

The Message-ID header is a one-line code addition that improves RFC 5322 compliance.
The domain used in make_msgid() is derived from EMAIL_ADDR (the module-level constant
already set to "hello@wetakeyourjob.com") so no new hardcoded value is introduced —
if the sending domain ever changes, only EMAIL_ADDR needs updating.

The domain name itself (wetakeyourjob.com) is inherently suspicious-sounding and
may still cause occasional false positives — accepted for demo. Production will use
bluefinncharters.com where this is not an issue.

## Source Material

### DNS changes already applied (completed by operator on 2026-03-10)

**SPF — TXT record on wetakeyourjob.com (@)**
```
v=spf1 include:spf.protection.outlook.com -all
```

**DKIM — CNAME records on wetakeyourjob.com**
```
selector1._domainkey → selector1-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft
selector2._domainkey → selector2-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft
```
DKIM enabled in Microsoft 365 Defender → Email authentication → DKIM.

**DMARC — TXT record on wetakeyourjob.com (_dmarc)**
```
v=DMARC1; p=none; rua=mailto:hello@wetakeyourjob.com; fo=1; adkim=s; aspf=s; pct=100
```

### smtp_send() current state (email_poller.py lines 126–150)
```python
def smtp_send(to_addr, subject, body, in_reply_to=None, references=None, reply_to=None):
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
    ...
```
No Message-ID header is set. EMAIL_ADDR is defined at module level (line 37):
`EMAIL_ADDR = os.environ.get("EMAIL_ADDR", "hello@wetakeyourjob.com")`

### email.utils.make_msgid
```python
from email.utils import make_msgid
make_msgid(domain="wetakeyourjob.com")
# Returns e.g. "<164984123.12345.1234567890@wetakeyourjob.com>"
```
stdlib — no new dependency.

## Instructions

### Step 1 — email_poller.py: Add make_msgid import

Find the existing email imports near the top of the file (after the stdlib imports).
Find the line:
```python
from email.mime.text import MIMEText
```
Add immediately after:
```python
from email.utils import make_msgid
```

### Step 2 — email_poller.py: Set Message-ID header in smtp_send()

In `smtp_send()`, after `msg["Subject"] = subject`, add:
```python
msg["Message-ID"] = make_msgid(domain=EMAIL_ADDR.split("@")[1])
```

The `domain` argument is derived from `EMAIL_ADDR` (e.g. "wetakeyourjob.com") — not
hardcoded. No separate constant needed.

Final smtp_send() header block should read:
```python
msg = MIMEMultipart()
msg["From"] = "Marina <{}>".format(EMAIL_ADDR)
msg["To"] = to_addr
msg["Subject"] = subject
msg["Message-ID"] = make_msgid(domain=EMAIL_ADDR.split("@")[1])
if in_reply_to:
    msg["In-Reply-To"] = in_reply_to
if references:
    msg["References"] = references
if reply_to:
    msg["Reply-To"] = reply_to
msg.attach(MIMEText(body, "plain", "utf-8"))
```

### Step 3 — email_poller.py: Leave file header unchanged
The file header already reads `# LAST MODIFIED: Brief 058`. Do not change it.
Brief 057 was planned before 058 but executed after. Chronological header would
misrepresent actual modification order. No header change needed.

### Step 4 — INFRA.md: Document email authentication status

Append a new section after the existing `## Email` section:

```markdown
## Email Authentication

| Record | Type | Value |
|--------|------|-------|
| SPF | TXT @ | `v=spf1 include:spf.protection.outlook.com -all` |
| DKIM selector1 | CNAME | `selector1-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DKIM selector2 | CNAME | `selector2-wetakeyourjob-com._domainkey.NETORGFT20395980.p-v1.dkim.mail.microsoft` |
| DMARC | TXT _dmarc | `v=DMARC1; p=none; rua=mailto:hello@wetakeyourjob.com; fo=1; adkim=s; aspf=s; pct=100` |

DKIM enabled in Microsoft 365 Defender → Email authentication → DKIM.
Configured: 2026-03-10.

Next steps (operator, not code):
- After 24–48h propagation: verify headers show SPF pass / DKIM pass / DMARC pass
- Consider moving DMARC reports to a dedicated mailbox (not hello@wetakeyourjob.com)
- After monitoring period: tighten DMARC from p=none → p=quarantine → p=reject
```

## Tests

Write `bluemarlin/tests/test_smtp_message_id.py`.

All tests mock `oauth_token` and `smtplib.SMTP` so no real connection is made.
They call `smtp_send()` directly and capture the message passed to `sendmail`.

```python
# tests/test_smtp_message_id.py
# Brief 057 — Anti Email-Spam: Message-ID header in smtp_send()

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import email
from unittest.mock import patch, MagicMock
import email_poller


def _call_smtp_send_capture_msg():
    """Call smtp_send() with mocked SMTP and return the captured raw message string."""
    captured = {}
    mock_smtp_instance = MagicMock()

    def fake_sendmail(from_addr, to_addrs, msg_string):
        captured["msg"] = msg_string

    mock_smtp_instance.ehlo = MagicMock()
    mock_smtp_instance.starttls = MagicMock()
    mock_smtp_instance.docmd = MagicMock(return_value=(235, b"OK"))
    mock_smtp_instance.sendmail = fake_sendmail
    mock_smtp_instance.quit = MagicMock()

    with patch("email_poller.oauth_token", return_value="fake-token"), \
         patch("email_poller.smtplib.SMTP", return_value=mock_smtp_instance):
        email_poller.smtp_send("test@example.com", "Test Subject", "Test body")

    return captured["msg"]


def test_smtp_send_sets_message_id():
    """smtp_send() sets a Message-ID header on every outbound email."""
    raw = _call_smtp_send_capture_msg()
    parsed = email.message_from_string(raw)
    assert parsed["Message-ID"] is not None, "FAIL: Message-ID header missing"


def test_message_id_uses_sending_domain():
    """Message-ID domain matches EMAIL_ADDR domain."""
    raw = _call_smtp_send_capture_msg()
    parsed = email.message_from_string(raw)
    expected_domain = email_poller.EMAIL_ADDR.split("@")[1]
    assert expected_domain in parsed["Message-ID"], \
        f"FAIL: Message-ID does not contain domain {expected_domain}"


def test_message_id_format_valid():
    """Message-ID is properly formatted: starts with < ends with >."""
    raw = _call_smtp_send_capture_msg()
    parsed = email.message_from_string(raw)
    mid = parsed["Message-ID"]
    assert mid.startswith("<") and mid.endswith(">"), \
        f"FAIL: Message-ID format invalid: {mid}"


def test_message_id_unique_per_send():
    """Each smtp_send() call produces a unique Message-ID."""
    raw1 = _call_smtp_send_capture_msg()
    raw2 = _call_smtp_send_capture_msg()
    mid1 = email.message_from_string(raw1)["Message-ID"]
    mid2 = email.message_from_string(raw2)["Message-ID"]
    assert mid1 != mid2, "FAIL: Message-IDs are identical across two sends"


if __name__ == "__main__":
    tests = [
        test_smtp_send_sets_message_id,
        test_message_id_uses_sending_domain,
        test_message_id_format_valid,
        test_message_id_unique_per_send,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
    print(f"\n{passed}/{len(tests)} tests passed.")
```

## Success Condition

Send a test email from Marina and inspect raw headers in Gmail (three-dot menu →
Show original). Headers must show: `Message-ID: <...@wetakeyourjob.com>`,
and `Authentication-Results:` must include `spf=pass`, `dkim=pass`, `dmarc=pass`.

## Rollback

Remove the `make_msgid` import and the `msg["Message-ID"]` line from email_poller.py.
Revert the INFRA.md addition. DNS changes are live and cannot be rolled back without
GoDaddy access — but they are additive and cause no harm if left in place.
