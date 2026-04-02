# BRIEF 062 — Live Test Harness: Automated E2E Testing
**Status:** Draft | **Files:** `tests/live_test_harness.py` (NEW) | **Depends on:** Briefs 060, 061 | **Blocks:** —

## Context

Live testing requires manually sending emails to Marina and eyeballing responses. This is slow, error-prone, and unrepeatable. We need an automated script that injects test emails into Marina's inbox, waits for the poller to process them, and verifies responses programmatically.

The script is **completely standalone** — zero modifications to any `src/` file. It lives in `tests/` and runs on the VPS.

## Why This Approach

IMAP APPEND lets us place crafted emails directly into Marina's inbox using existing OAuth credentials. No second email account needed for sending. The poller picks them up identically to real emails. We read `email_thread_state.json` (read-only) to verify responses. Test sender is `ops.bluemarlindemo@gmail.com` — a real deliverable Gmail not referenced anywhere in the codebase, so Marina's SMTP reply succeeds and thread state gets saved.

Alternative considered: mocking the poller pipeline. Rejected because it wouldn't test the full end-to-end flow (IMAP pickup, dedup, thread resolution, SMTP delivery).

## Source Material

### IMAP connection (email_poller.py lines 120-125)
```python
def imap_connect():
    token = oauth_token("offline_access https://outlook.office.com/IMAP.AccessAsUser.All")
    auth_string = f"user={EMAIL_ADDR}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
    im = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    im.authenticate("XOAUTH2", lambda _: auth_string)
    return im
```

### OAuth token (email_poller.py lines 108-118)
```python
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
```

### Config constants (email_poller.py lines 36-54)
```python
CLIENT_ID = "28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID = "caac06b5-1420-4223-9dcc-ba4a670ec26a"
EMAIL_ADDR = "hello@wetakeyourjob.com"
IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993
THREAD_STATE_PATH = os.path.join(_CONFIG_DIR, "email_thread_state.json")
```

### Thread key resolution (email_poller.py lines 183-201)
For new emails without References/In-Reply-To, the thread key is:
```python
"subj:{}:{}".format(from_email.strip().lower(), normalize_subject(subject).strip().lower())
```

### Dedup fingerprint (email_poller.py line 454)
```python
content_fingerprint = f"{from_email.strip().lower()}|{normalize_subject(subj).strip().lower()}|{body.strip()}"
```

### Thread state messages format (email_poller.py lines 1037-1051)
```python
th["messages"].append({
    "role": "marina",
    "ts": datetime.now(timezone.utc).isoformat(),
    "body": reply_text,
})
```

### Trip data needed for test scenarios (from config/client.json)
- `klein_curacao`: daily, departures 08:00 + 08:30
- `snorkeling_3in1`: Fridays only, departure 10:00
- `sunset_cruise`: Tue/Thu/Fri/Sat, departure 17:30, $79/adult
- `west_coast_beach`: Wednesdays and Sundays, departure 09:00
- `jet_ski`: daily, 12 departure slots (08:00 through 19:00)

## Instructions

### Step 1: Create `tests/live_test_harness.py`

Create a single self-contained script using **only stdlib imports**. Do NOT import from `email_poller` or any other `src/` module — importing `email_poller` triggers transitive imports of `marina_agent`, `config_loader`, `sheets_writer`, `gws_calendar`, and `state_registry` (which opens a SQLite DB on import). Instead, copy the three small functions we need (`oauth_token`, `imap_connect`, `normalize_subject`) directly into the script, along with the config constants.

The script has these sections:

#### 1a. Constants, config, and copied helpers

```python
#!/usr/bin/env python3
"""BlueMarlin Live Test Harness — automated E2E testing via IMAP injection."""
import imaplib, json, os, re, time, uuid, argparse, subprocess
import urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import format_datetime, make_msgid

# --- Config (copied from email_poller.py, never imported) ---
CLIENT_ID = "28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID = "caac06b5-1420-4223-9dcc-ba4a670ec26a"
EMAIL_ADDR = "hello@wetakeyourjob.com"
IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "config"))
REFRESH_TOKEN_PATH = os.path.join(_CONFIG_DIR, "azure_refresh_token.txt")
THREAD_STATE_PATH = os.path.join(_CONFIG_DIR, "email_thread_state.json")

TEST_SENDER = "ops.bluemarlindemo@gmail.com"
TEST_SENDER_NAME = "Live Test"
POLL_INTERVAL = 3
MAX_WAIT = 90
MARINA_ADDR = EMAIL_ADDR

# --- Copied helpers (from email_poller.py — no imports from src/) ---
def _get_refresh_token():
    return open(REFRESH_TOKEN_PATH).read().strip()

def _oauth_token(scope):
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "refresh_token": _get_refresh_token(),
        "grant_type": "refresh_token",
        "scope": scope,
    }).encode()
    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token", data
        )
    ).read())
    return resp["access_token"]

def _imap_connect():
    token = _oauth_token("offline_access https://outlook.office.com/IMAP.AccessAsUser.All")
    auth_string = f"user={EMAIL_ADDR}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
    im = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    im.authenticate("XOAUTH2", lambda _: auth_string)
    return im

def _normalize_subject(subj):
    s = (subj or "").strip()
    while True:
        ns = re.sub(r"^(re|fwd|fw)\s*:\s*", "", s, flags=re.IGNORECASE).strip()
        if ns == s:
            break
        s = ns
    return s
```

#### 1b. IMAP injection function

```python
def inject_email(im, from_addr, from_name, subject, body):
    """APPEND a crafted RFC822 email to Marina's INBOX as UNSEEN."""
```

Build a valid RFC822 message with:
- `From: {from_name} <{from_addr}>`
- `To: Marina <{MARINA_ADDR}>`
- `Subject: {subject}`
- `Date:` current RFC2822 timestamp
- `Message-ID: <{uuid}@livetest.bluemarlin>`
- `MIME-Version: 1.0`
- `Content-Type: text/plain; charset=utf-8`
- Body as UTF-8 plain text

Use `im.append("INBOX", None, None, rfc822_bytes)` — `None` for flags means no flags set (not `\Seen`), so the poller finds it as UNSEEN.

Return the Message-ID string.

#### 1c. Thread state reader

```python
def predict_thread_key(from_addr, subject):
    """Predict the thread key the poller will assign."""
    return f"subj:{from_addr.strip().lower()}:{_normalize_subject(subject).strip().lower()}"

def get_thread(thread_key):
    """Read thread state file and return thread dict, or None."""
    # Read THREAD_STATE_PATH, parse JSON, return state["threads"].get(thread_key)

def wait_for_reply(thread_key, expected_marina_count, timeout=MAX_WAIT):
    """Poll until thread has >= expected_marina_count marina messages. Return thread dict or raise TimeoutError."""
    # Count messages where role == "marina"
    # Poll every POLL_INTERVAL seconds
    # Raise TimeoutError with descriptive message if exceeded
```

#### 1d. Assertion helpers

```python
def check(name, condition, detail=""):
    """Print PASS/FAIL, track results."""

def reply_text(th):
    """Get the last marina message body from thread."""

def assert_reply_contains(th, text, label):
    check(label, text.lower() in reply_text(th).lower(), f"looking for '{text}'")

def assert_reply_not_contains(th, text, label):
    check(label, text.lower() not in reply_text(th).lower(), f"should not contain '{text}'")

def assert_flag(th, flag, expected, label):
    check(label, th["flags"].get(flag) == expected, f"{flag}={th['flags'].get(flag)}")

def assert_field(th, field, expected, label):
    check(label, th["fields"].get(field) == expected, f"{field}={th['fields'].get(field)}")

def assert_no_emdash(th, label):
    check(label, "\u2014" not in reply_text(th) and "\u2013" not in reply_text(th), "em/en dash found")
```

#### 1e. Cleanup (opt-in only, requires poller stopped)

```python
def cleanup_test_threads(state_path, test_sender):
    """Remove all threads with keys containing the test sender email.
    SAFETY: Only call when poller is stopped to avoid race conditions."""
    # Check poller is stopped first
    result = subprocess.run(["systemctl", "is-active", "bluemarlin"], capture_output=True, text=True)
    if result.stdout.strip() == "active":
        print("WARNING: Poller is running. Stop it first: systemctl stop bluemarlin")
        print("Skipping cleanup to avoid race condition.")
        return
    # Load state, delete matching threads, save with atomic write
```

Cleanup is NOT run by default. It requires explicit `--cleanup` flag AND the poller must be stopped. The main runner defaults to `--no-cleanup` behavior — test threads persist harmlessly (they use unique subjects and won't interfere with real customers).

#### 1f. Test scenarios

Each scenario is a function that:
1. Generates a unique run ID (`uuid.uuid4().hex[:8]`)
2. Embeds it in the body: `[LIVETEST-{run_id}]`
3. Injects email(s)
4. Waits for reply
5. Runs assertions
6. Returns pass/fail

Scenario CLI names (used with `--scenario`):
- `simple_inquiry` → Scenario 1
- `booking_summary` → Scenario 2
- `day_of_week` → Scenario 3
- `tone_quality` → Scenario 4
- `unknown_ref` → Scenario 5
- `escalation` → Scenario 6

Register all scenarios in a dict: `SCENARIOS = {"simple_inquiry": test_simple_inquiry, ...}`

**Scenario 1: Simple inquiry** (`simple_inquiry`)
```
Subject: Trip options
Body: [LIVETEST-{id}] Hi, what trips do you have available?
Assertions:
  - reply contains some trip name (e.g. "Klein" or "Sunset" or "Snorkeling")
  - flag requires_human is not set (or absent)
  - no em dashes in reply
```

**Scenario 2: Booking with summary (tone test)**
```
Subject: Sunset Cruise booking
Body: [LIVETEST-{id}] Hi, I'd like to book the Sunset Cruise on {next_valid_day} for 2 guests. Name is Test Runner, phone +1234567890.
  (next_valid_day = compute next Tuesday/Thursday/Friday/Saturday from today, format as "April 15 2027")
Assertions:
  - field trip_key == "sunset_cruise"
  - field guests == "2"
  - flag awaiting_booking_confirmation is True
  - reply contains "$" (price present)
  - reply contains "158" (2 x $79)
  - reply NOT contains "Here's a quick summary" (old format)
  - reply NOT contains "Shall I lock" (old phrase)
  - reply contains "Want me to go ahead and book this" OR reply contains "book" (flexible — Claude may rephrase)
  - no em dashes in reply
```

**Scenario 3: Day-of-week correction**
```
Subject: Snorkeling booking
Body: [LIVETEST-{id}] I want to book the snorkeling trip for {next_wednesday} for 2 people.
  (next_wednesday = compute next Wednesday, format as "April 16 2027" — snorkeling is Fridays only)
Assertions:
  - reply contains "Friday" or "Fridays"
  - reply NOT contains "Great choice"
  - reply NOT contains em dashes
```

**Scenario 4: Tone quality check**
```
Subject: Quick question
Body: [LIVETEST-{id}] Hey, quick question — do you guys do sunset cruises? How much?
Assertions:
  - no em dashes
  - reply NOT contains "I'd be happy to"
  - reply NOT contains "Absolutely"
  - reply NOT contains "Great question"
  - reply NOT contains "Thank you for reaching out"
```

**Scenario 5: Unknown booking ref**
```
Subject: My booking
Body: [LIVETEST-{id}] Hi, I have booking BF-2027-00000 and I need to check something.
Assertions:
  - reply mentions ref not found, or asks to double-check (flexible: "couldn't find" OR "not found" OR "double-check" OR "check the number")
```

**Scenario 6: Escalation (complaint)**
```
Subject: Terrible experience
Body: [LIVETEST-{id}] I had a terrible time on your boat yesterday. The crew was rude and the food was cold. I want a full refund.
Assertions:
  - flag requires_human is True
  - reply contains "team" or "care" (escalation acknowledgment)
  - reply NOT contains em dashes
```

#### 1g. Main runner

```python
def main():
    parser = argparse.ArgumentParser(description="BlueMarlin Live Test Harness")
    parser.add_argument("--scenario", help="Run a single scenario by name")
    parser.add_argument("--dry-run", action="store_true", help="Show emails without injecting")
    parser.add_argument("--cleanup", action="store_true", help="Clean up test threads (requires poller stopped)")
    args = parser.parse_args()

    # Check poller is running (required for test injection, skip for dry-run)
    # Connect IMAP (skip for dry-run)
    # Run scenarios (all or single)
    # Print summary
    # Cleanup only if --cleanup flag set (checks poller is stopped)
    # Exit with code 0 (all pass) or 1 (any fail)
```

Use far-future dates (2027+) for all booking scenarios to avoid conflicts with real bookings.

### Step 2: Date helper

Add a helper to compute valid future dates for specific days-of-week:

```python
def next_weekday(target_weekday, year=2027):
    """Return the next occurrence of target_weekday (0=Mon..6=Sun) in the given year, as 'Month DD YYYY'."""
    from datetime import date, timedelta
    start = date(year, 4, 1)  # Start from April 2027
    while start.weekday() != target_weekday:
        start += timedelta(days=1)
    return start.strftime("%B %d %Y")  # e.g. "April 01 2027"
```

### Step 3: Dry-run mode

When `--dry-run` is set, print each scenario's injected email content (From, Subject, Body) without connecting to IMAP or injecting. This lets the user preview what would be sent.

## Tests

This brief creates a test tool, not production code. Verification is running the harness itself on VPS:

### T1: Dry run succeeds on VPS
```bash
ssh root@108.61.192.52 "cd /root/bluemarlin && python3 tests/live_test_harness.py --dry-run"
```
Should print 6 scenario previews with From/Subject/Body, exit 0, no IMAP connection. (Runs on VPS because the script references config paths, but dry-run does NOT connect to IMAP or read the refresh token.)

### T2: Full run on VPS
```bash
ssh root@108.61.192.52 "cd /root/bluemarlin && python3 tests/live_test_harness.py"
```
Should inject 6 emails, wait for replies, report PASS/FAIL per assertion, exit 0 if all pass. Test threads persist harmlessly (cleanup is separate, opt-in).

### T3: Single scenario
```bash
ssh root@108.61.192.52 "cd /root/bluemarlin && python3 tests/live_test_harness.py --scenario tone_quality"
```
Should run only that scenario.

## Success Condition

`--dry-run` on VPS prints 6 scenario previews and exits 0. Full run on VPS injects emails, verifies Marina's responses, and reports results.

## Rollback

Delete `tests/live_test_harness.py`. No other files are touched.
