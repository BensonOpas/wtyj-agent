#!/usr/bin/env python3
# FILE: tests/live_test_harness.py
# CREATED: Brief 062
# LAST MODIFIED: Brief 062
# PURPOSE: Automated E2E testing via IMAP injection — standalone, no src/ imports
"""BlueMarlin Live Test Harness — automated E2E testing via IMAP injection."""
import imaplib, json, os, re, time, uuid, argparse, subprocess
import urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import format_datetime, make_msgid

# ========= CONFIG (copied from email_poller.py, never imported) =========
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

# ========= COPIED HELPERS (from email_poller.py) =========

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


# ========= DATE HELPERS =========

def next_weekday(target_weekday, year=2027):
    """Return next occurrence of target_weekday (0=Mon..6=Sun) in given year."""
    start = date(year, 4, 1)
    while start.weekday() != target_weekday:
        start += timedelta(days=1)
    return start.strftime("%B %d %Y")


# ========= IMAP INJECTION =========

def inject_email(im, from_addr, from_name, subject, body):
    """APPEND a crafted RFC822 email to Marina's INBOX as UNSEEN."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = f"Marina <{MARINA_ADDR}>"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg_id = make_msgid(domain="livetest.bluemarlin")
    msg["Message-ID"] = msg_id

    rfc822_bytes = msg.as_bytes()
    im.append("INBOX", None, None, rfc822_bytes)
    return msg_id


# ========= THREAD STATE READER =========

def predict_thread_key(from_addr, subject):
    """Predict the thread key the poller will assign."""
    return f"subj:{from_addr.strip().lower()}:{_normalize_subject(subject).strip().lower()}"


def get_thread(thread_key):
    """Read thread state file and return thread dict, or None."""
    try:
        with open(THREAD_STATE_PATH, "r") as f:
            state = json.load(f)
        return state.get("threads", {}).get(thread_key)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def wait_for_reply(thread_key, expected_marina_count=1, timeout=MAX_WAIT):
    """Poll until thread has >= expected_marina_count marina messages."""
    start = time.time()
    while time.time() - start < timeout:
        th = get_thread(thread_key)
        if th:
            marina_msgs = [m for m in th.get("messages", []) if m.get("role") == "marina"]
            if len(marina_msgs) >= expected_marina_count:
                return th
        time.sleep(POLL_INTERVAL)
    elapsed = int(time.time() - start)
    raise TimeoutError(f"No reply after {elapsed}s for thread {thread_key}")


# ========= ASSERTION HELPERS =========

_passed = 0
_failed = 0
_results = []


def check(name, condition, detail=""):
    global _passed, _failed
    if condition:
        print(f"  PASS: {name}")
        _passed += 1
        _results.append({"name": name, "passed": True})
    else:
        msg = f"  FAIL: {name}"
        if detail:
            msg += f" ({detail})"
        print(msg)
        _failed += 1
        _results.append({"name": name, "passed": False, "detail": detail})


def reply_text(th):
    """Get the last marina message body from thread."""
    msgs = [m for m in th.get("messages", []) if m.get("role") == "marina"]
    return msgs[-1]["body"] if msgs else ""


def assert_reply_contains(th, text, label):
    rt = reply_text(th)
    check(label, text.lower() in rt.lower(), f"looking for '{text}' in reply")


def assert_reply_not_contains(th, text, label):
    rt = reply_text(th)
    check(label, text.lower() not in rt.lower(), f"should not contain '{text}'")


def assert_reply_contains_any(th, texts, label):
    rt = reply_text(th).lower()
    found = any(t.lower() in rt for t in texts)
    check(label, found, f"looking for any of {texts}")


def assert_flag(th, flag, expected, label):
    actual = th.get("flags", {}).get(flag)
    check(label, actual == expected, f"{flag}={actual}, expected={expected}")


def assert_flag_absent_or_false(th, flag, label):
    actual = th.get("flags", {}).get(flag)
    check(label, not actual, f"{flag}={actual}")


def assert_field(th, field, expected, label):
    actual = th.get("fields", {}).get(field)
    check(label, actual == expected, f"{field}={actual}, expected={expected}")


def assert_no_emdash(th, label):
    rt = reply_text(th)
    check(label, "\u2014" not in rt and "\u2013" not in rt, "em/en dash found in reply")


# ========= CLEANUP =========

def cleanup_test_threads(test_sender):
    """Remove test threads from state file. Requires poller stopped."""
    result = subprocess.run(["systemctl", "is-active", "bluemarlin"],
                            capture_output=True, text=True)
    if result.stdout.strip() == "active":
        print("WARNING: Poller is running. Stop it first: systemctl stop bluemarlin")
        print("Skipping cleanup to avoid race condition.")
        return

    try:
        with open(THREAD_STATE_PATH, "r") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No thread state file found.")
        return

    threads = state.get("threads", {})
    test_keys = [k for k in threads if test_sender.lower() in k.lower()]
    if not test_keys:
        print("No test threads to clean up.")
        return

    for k in test_keys:
        del threads[k]
        print(f"  Removed thread: {k}")

    tmp = THREAD_STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, THREAD_STATE_PATH)
    print(f"Cleaned up {len(test_keys)} test thread(s).")


# ========= TEST SCENARIOS =========

def test_simple_inquiry(im, dry_run=False):
    """Scenario 1: Simple trip inquiry."""
    run_id = uuid.uuid4().hex[:8]
    subject = "Trip options"
    body = f"[LIVETEST-{run_id}] Hi, what trips do you have available?"

    if dry_run:
        _print_dry_run("simple_inquiry", subject, body)
        return

    print("\n=== Scenario: simple_inquiry ===")
    tk = predict_thread_key(TEST_SENDER, subject)
    inject_email(im, TEST_SENDER, TEST_SENDER_NAME, subject, body)
    print(f"  Injected. Waiting for reply (thread: {tk})...")

    th = wait_for_reply(tk)
    print(f"  Reply: {reply_text(th)[:200]}...")

    assert_reply_contains_any(th, ["Klein", "Sunset", "Snorkeling", "cruise", "trip"], "reply mentions trips")
    assert_flag_absent_or_false(th, "requires_human", "no escalation")
    assert_no_emdash(th, "no em dashes")


def test_booking_summary(im, dry_run=False):
    """Scenario 2: Booking with summary — tone test."""
    run_id = uuid.uuid4().hex[:8]
    valid_day = next_weekday(3)  # Thursday (sunset_cruise runs Tue/Thu/Fri/Sat)
    subject = "Sunset Cruise booking"
    body = (
        f"[LIVETEST-{run_id}] Hi, I'd like to book the Sunset Cruise on {valid_day} "
        f"for 2 guests. Name is Test Runner, phone +1234567890."
    )

    if dry_run:
        _print_dry_run("booking_summary", subject, body)
        return

    print("\n=== Scenario: booking_summary ===")
    tk = predict_thread_key(TEST_SENDER, subject)
    inject_email(im, TEST_SENDER, TEST_SENDER_NAME, subject, body)
    print(f"  Injected. Waiting for reply (thread: {tk})...")

    th = wait_for_reply(tk)
    print(f"  Reply: {reply_text(th)[:200]}...")

    assert_field(th, "trip_key", "sunset_cruise", "trip_key correct")
    assert_field(th, "guests", "2", "guests correct")
    assert_flag(th, "awaiting_booking_confirmation", True, "awaiting confirmation")
    assert_reply_contains(th, "$", "price present")
    assert_reply_contains(th, "158", "total $158")
    assert_reply_not_contains(th, "Here's a quick summary", "no old summary format")
    assert_reply_not_contains(th, "Shall I lock", "no old lock phrase")
    assert_reply_contains_any(th, ["Want me to go ahead and book this", "book"], "booking prompt present")
    assert_no_emdash(th, "no em dashes")


def test_day_of_week(im, dry_run=False):
    """Scenario 3: Day-of-week correction (snorkeling on Wednesday = wrong)."""
    run_id = uuid.uuid4().hex[:8]
    wed = next_weekday(2)  # Wednesday (snorkeling is Fridays only)
    subject = "Snorkeling booking"
    body = f"[LIVETEST-{run_id}] I want to book the snorkeling trip for {wed} for 2 people."

    if dry_run:
        _print_dry_run("day_of_week", subject, body)
        return

    print("\n=== Scenario: day_of_week ===")
    tk = predict_thread_key(TEST_SENDER, subject)
    inject_email(im, TEST_SENDER, TEST_SENDER_NAME, subject, body)
    print(f"  Injected. Waiting for reply (thread: {tk})...")

    th = wait_for_reply(tk)
    print(f"  Reply: {reply_text(th)[:200]}...")

    assert_reply_contains_any(th, ["Friday", "Fridays"], "mentions correct day")
    assert_reply_not_contains(th, "Great choice", "no Great choice")
    assert_no_emdash(th, "no em dashes")


def test_tone_quality(im, dry_run=False):
    """Scenario 4: Tone quality — check for AI-isms."""
    run_id = uuid.uuid4().hex[:8]
    subject = "Quick question"
    body = f"[LIVETEST-{run_id}] Hey, quick question - do you guys do sunset cruises? How much?"

    if dry_run:
        _print_dry_run("tone_quality", subject, body)
        return

    print("\n=== Scenario: tone_quality ===")
    tk = predict_thread_key(TEST_SENDER, subject)
    inject_email(im, TEST_SENDER, TEST_SENDER_NAME, subject, body)
    print(f"  Injected. Waiting for reply (thread: {tk})...")

    th = wait_for_reply(tk)
    print(f"  Reply: {reply_text(th)[:200]}...")

    assert_no_emdash(th, "no em dashes")
    assert_reply_not_contains(th, "I'd be happy to", "no 'I'd be happy to'")
    assert_reply_not_contains(th, "Absolutely", "no 'Absolutely'")
    assert_reply_not_contains(th, "Great question", "no 'Great question'")
    assert_reply_not_contains(th, "Thank you for reaching out", "no stock opener")


def test_unknown_ref(im, dry_run=False):
    """Scenario 5: Unknown booking ref."""
    run_id = uuid.uuid4().hex[:8]
    subject = "My booking"
    body = f"[LIVETEST-{run_id}] Hi, I have booking BF-2027-00000 and I need to check something."

    if dry_run:
        _print_dry_run("unknown_ref", subject, body)
        return

    print("\n=== Scenario: unknown_ref ===")
    tk = predict_thread_key(TEST_SENDER, subject)
    inject_email(im, TEST_SENDER, TEST_SENDER_NAME, subject, body)
    print(f"  Injected. Waiting for reply (thread: {tk})...")

    th = wait_for_reply(tk)
    print(f"  Reply: {reply_text(th)[:200]}...")

    assert_reply_contains_any(
        th,
        ["couldn't find", "not found", "double-check", "check the number", "don't have", "unable to find"],
        "ref not found acknowledged",
    )


def test_escalation(im, dry_run=False):
    """Scenario 6: Escalation (complaint)."""
    run_id = uuid.uuid4().hex[:8]
    subject = "Terrible experience"
    body = (
        f"[LIVETEST-{run_id}] I had a terrible time on your boat yesterday. "
        f"The crew was rude and the food was cold. I want a full refund."
    )

    if dry_run:
        _print_dry_run("escalation", subject, body)
        return

    print("\n=== Scenario: escalation ===")
    tk = predict_thread_key(TEST_SENDER, subject)
    inject_email(im, TEST_SENDER, TEST_SENDER_NAME, subject, body)
    print(f"  Injected. Waiting for reply (thread: {tk})...")

    th = wait_for_reply(tk)
    print(f"  Reply: {reply_text(th)[:200]}...")

    assert_flag(th, "requires_human", True, "requires_human set")
    assert_reply_contains_any(th, ["team", "care"], "escalation acknowledgment")
    assert_no_emdash(th, "no em dashes")


# ========= SCENARIO REGISTRY =========

SCENARIOS = {
    "simple_inquiry": test_simple_inquiry,
    "booking_summary": test_booking_summary,
    "day_of_week": test_day_of_week,
    "tone_quality": test_tone_quality,
    "unknown_ref": test_unknown_ref,
    "escalation": test_escalation,
}


def _print_dry_run(name, subject, body):
    print(f"\n--- {name} ---")
    print(f"  From: {TEST_SENDER_NAME} <{TEST_SENDER}>")
    print(f"  To: Marina <{MARINA_ADDR}>")
    print(f"  Subject: {subject}")
    print(f"  Body: {body}")


# ========= MAIN =========

def main():
    global _passed, _failed, _results
    parser = argparse.ArgumentParser(description="BlueMarlin Live Test Harness")
    parser.add_argument("--scenario", help="Run a single scenario by name", choices=list(SCENARIOS.keys()))
    parser.add_argument("--dry-run", action="store_true", help="Show emails without injecting")
    parser.add_argument("--cleanup", action="store_true", help="Clean up test threads (requires poller stopped)")
    args = parser.parse_args()

    if args.cleanup:
        cleanup_test_threads(TEST_SENDER)
        return

    scenarios = SCENARIOS
    if args.scenario:
        scenarios = {args.scenario: SCENARIOS[args.scenario]}

    if args.dry_run:
        print("=== DRY RUN — previewing test emails ===")
        for name, fn in scenarios.items():
            fn(None, dry_run=True)
        print(f"\n{len(scenarios)} scenario(s) previewed.")
        return

    # Check poller is running
    result = subprocess.run(["systemctl", "is-active", "bluemarlin"],
                            capture_output=True, text=True)
    if result.stdout.strip() != "active":
        print("ERROR: Poller is not running. Start it: systemctl start bluemarlin")
        raise SystemExit(1)

    print("Connecting to IMAP...")
    im = _imap_connect()
    im.select("INBOX")
    print("Connected.\n")

    _passed = 0
    _failed = 0
    _results = []

    for name, fn in scenarios.items():
        try:
            fn(im)
        except TimeoutError as e:
            print(f"  TIMEOUT: {name} — {e}")
            _failed += 1
            _results.append({"name": f"{name} (timeout)", "passed": False})
        except Exception as e:
            print(f"  ERROR: {name} — {e}")
            _failed += 1
            _results.append({"name": f"{name} (error)", "passed": False})

    try:
        im.logout()
    except Exception:
        pass

    print(f"\n{'='*50}")
    print(f"Results: {_passed} passed, {_failed} failed out of {_passed + _failed}")
    if _failed:
        print("\nFailed checks:")
        for r in _results:
            if not r["passed"]:
                detail = r.get("detail", "")
                print(f"  - {r['name']}" + (f" ({detail})" if detail else ""))
        print("\nSOME TESTS FAILED")
        raise SystemExit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    main()
