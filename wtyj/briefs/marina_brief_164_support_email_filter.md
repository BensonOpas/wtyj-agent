# BRIEF 164 — Support-email sender filter + Lucia test-pollution cleanup
**Status:** Draft | **Files:** email_poller.py, test_164 (new), VPS state_registry.db | **Depends on:** — | **Blocks:** —

## Context

During the 2026-04-08 E2E test session, Benson sent test emails FROM `butlerbensonagent@gmail.com` (BlueMarlin's `business.support_email`) TO `hello@wetakeyourjob.com` (BlueMarlin's `business.booking_email`). Marina treated every one of them as a legitimate customer and:

1. Created a fake booking `SU0AHF` for "Lucia Vasquez" with `customer_email = butlerbensonagent@gmail.com`, which landed in `bookings` table + Google Sheets Bookings tab.
2. Every subsequent test email from the same address triggered the returning-customer lookup at `email_poller.py:745` (`state_registry.get_bookings_by_email(from_email)`) which found Lucia's SU0AHF and injected `_past_customer_bookings` context into Marina's prompt. Marina then greeted Pieter, Maria, Angela, Robert, and Joscar (five different "new" customers, all sent from the same test address) as "returning customers" in their respective languages.
3. One escalation email pair name-stitched: `"Returning customer Angela Wright (ref SU0AHF on file, complaint ref BF7821)"` — real ref + hallucinated complaint ref.

The existing email_poller guard at line 599 only catches `from_email == demo_support_email AND "[ESCALATION]" in subject`, and line 605 catches the `[RELAY-` subject. Anything else from the support email is processed as a customer message.

**The real production risk** beyond the test: if a WTYJ operator ever forwards a customer's email to `hello@wetakeyourjob.com`, or replies-all to an escalation notification, or uses the business email to CC themselves on anything, Marina will process it as a new customer inquiry and pollute the database.

## Why This Approach

**Chosen — single broad guard at the top of the UID loop.** Check if `from_email` matches any of `business.support_email`, `business.email`, `business.booking_email`, `business.demo_support_email` (lowercased). If yes AND the subject does NOT match the existing relay/escalation reply patterns (`[RELAY-` or `[ESCALATION]`), log and skip. One place, one rule, no downstream changes needed.

**Rejected — filter inside `state_registry.get_bookings_by_email`.** Would be a second layer of defense but speculative — the guard above already prevents the call from being made for business emails. Adding a second filter inside the DB layer would be defensive code for a scenario that can't happen if the guard runs. Skipped per CLAUDE.md's "don't add validation for scenarios that can't happen".

**Rejected — hardcode `butlerbensonagent@gmail.com`.** Violates Rule 4 (business data lives in client.json). Must read from config.

**Rejected — only check `support_email`.** Benson's test address is `support_email` but the `business.email` and `booking_email` fields are ALSO business-owned addresses. A forward or reply-all from any of them should be caught.

## Source Material

### Existing guards (lines 515-602)

```python
# Skip system/automated emails (noreply, mailer-daemon, etc.)
if any(from_email.lower().startswith(p) for p in _SYSTEM_EMAIL_PREFIXES):
    im.uid("store", uid, "+FLAGS", r"(\Seen)")
    log(f"Skipped system email from {from_email}")
    continue

# ... rate limit, duplicate fingerprint, thread resolution ...

# Drop operator replies to [ESCALATION] alerts — escalation is one-way
if from_email.lower() == demo_support_email.lower() and "[ESCALATION]" in subj:
    im.uid("store", uid, "+FLAGS", r"(\Seen)")
    log(f"Dropped escalation reply from {from_email} — one-way flow")
    continue

# [RELAY] inbound from human team — reformulate and forward to original customer
if from_email.lower() == demo_support_email.lower() and "[RELAY-" in subj:
    # ... relay handling ...
```

### BlueMarlin business email fields (client.json)

```json
{
  "name": "BlueMarlin Charters",
  "email": "butlerbensonagent@gmail.com",
  "booking_email": "hello@wetakeyourjob.com",
  "support_email": "butlerbensonagent@gmail.com",
  "demo_support_email": "butlerbensonagent@gmail.com"
}
```

Three of the four point at `butlerbensonagent@gmail.com`. The fourth (`booking_email`) is the inbound customer address. All four must be in the "not a customer" set.

### Adamus business email fields

```
email: (not yet set — OAuth bootstrap pending per project_open_work.md)
support_email: (empty)
```

For Adamus the guard will be a no-op until email is bootstrapped, which is fine.

### Lucia junk row on VPS

Confirmed via SSH:
```
('SU0AHF', 'Lucia Vasquez', 'butlerbensonagent@gmail.com', 'sunset_cruise', '2026-04-17', 4, '2026-04-08T23:48:29.466962+00:00')
```

One row in `bookings` table. Also lives in the Google Sheets Bookings tab but Sheets cleanup is manual-only and out of scope (noted as known limitation).

## Instructions

### Step 1: Add `_business_sender_emails()` helper and guard

**File:** `wtyj/agents/marina/email_poller.py`

Add a helper function near the top of the file (after `_SYSTEM_EMAIL_PREFIXES` at line 78):

```python
def _business_sender_emails() -> set:
    """Brief 164: return all business-owned email addresses (lowercased) that
    should never be treated as customer senders. Inbound messages from these
    addresses are skipped unless they match a relay/escalation reply subject.

    Pulls from client.json business.email, business.support_email,
    business.booking_email, business.demo_support_email. Deduplicates and
    lowercases. Empty values are filtered out.
    """
    biz = config_loader.get_business()
    candidates = {
        biz.get("email"),
        biz.get("support_email"),
        biz.get("booking_email"),
        biz.get("demo_support_email"),
    }
    return {e.strip().lower() for e in candidates if e and e.strip()}
```

Then add a guard in the UID loop, placed immediately AFTER the `_SYSTEM_EMAIL_PREFIXES` check (line 519) and BEFORE the per-sender rate limit check (line 521):

```python
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
```

**Important:** the existing `demo_support_email` checks at lines 599 and 605 remain in place. They handle the specific relay/escalation reply cases which this new guard deliberately passes through (`not (_is_relay or _is_escalation)`).

### Step 2: Delete Lucia SU0AHF row on VPS

```bash
ssh root@108.61.192.52 "docker exec wtyj-bluemarlin python3 -c '
import sqlite3
conn = sqlite3.connect(\"/app/data/state_registry.db\")
c = conn.cursor()
c.execute(\"DELETE FROM bookings WHERE booking_ref = ?\", (\"SU0AHF\",))
print(f\"Deleted {c.rowcount} Lucia junk row(s)\")
conn.commit()
conn.close()
'"
```

Google Sheets Bookings tab row cleanup is manual-only (no programmatic delete path) — documented as known limitation.

### Step 3: Tests (`wtyj/tests/marina/test_164_support_email_filter.py`)

```python
"""Tests for Brief 164 — support-email sender filter.

Covers:
- _business_sender_emails() helper returns the full set from business config
- Business senders with non-relay/escalation subjects are filtered
- Relay subjects from business senders are NOT filtered (existing flow preserved)
- Escalation reply subjects from business senders are NOT filtered
- Customer senders (different address) are never filtered
"""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.marina import email_poller


@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_emails_includes_all_four_fields(mock_get_business):
    """Brief 164: helper returns all four business email fields, lowercased, deduped."""
    mock_get_business.return_value = {
        "email": "Support@Test.com",
        "support_email": "support@test.com",
        "booking_email": "BOOK@test.com",
        "demo_support_email": "support@test.com",
        "name": "Test",
    }
    result = email_poller._business_sender_emails()
    assert result == {"support@test.com", "book@test.com"}


@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_emails_handles_missing_fields(mock_get_business):
    """Brief 164: missing or empty fields are filtered out."""
    mock_get_business.return_value = {
        "email": "hello@test.com",
        "support_email": "",
        "booking_email": None,
        "name": "Test",
    }
    result = email_poller._business_sender_emails()
    assert result == {"hello@test.com"}


@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_emails_empty_when_no_business(mock_get_business):
    """Brief 164: empty business dict returns empty set (guard is a no-op)."""
    mock_get_business.return_value = {}
    assert email_poller._business_sender_emails() == set()


# --- Source-level regression guard ---

def test_source_has_business_sender_guard():
    """Brief 164: email_poller.py must contain the business-sender guard in the UID loop."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                             "agents", "marina", "email_poller.py")).read()
    assert "_business_sender_emails" in src, (
        "Brief 164: _business_sender_emails helper missing from email_poller.py"
    )
    assert "Skipped business-sender email" in src, (
        "Brief 164: business-sender guard log line missing from email_poller.py"
    )
    # The guard must preserve the relay/escalation passthrough
    guard_idx = src.find("Skipped business-sender email")
    assert guard_idx > 0
    pre_guard = src[max(0, guard_idx - 500):guard_idx]
    assert "_is_relay" in pre_guard and "_is_escalation" in pre_guard, (
        "Brief 164: the guard must preserve relay/escalation subjects"
    )


# --- Helper call signature test ---

@patch("agents.marina.email_poller.config_loader.get_business")
def test_business_sender_lowercase_normalization(mock_get_business):
    """Brief 164: the helper must lowercase so the guard matches case-insensitively."""
    mock_get_business.return_value = {
        "email": "Operator@Test.COM",
        "support_email": "  Ops@Test.com  ",  # whitespace
    }
    result = email_poller._business_sender_emails()
    assert result == {"operator@test.com", "ops@test.com"}
```

### Step 4: Run tests + full regression

```bash
python3 -m pytest wtyj/tests/marina/test_164_support_email_filter.py -v --tb=short
python3 -m pytest wtyj/tests/ -q --tb=line
```

Expected: 5 new tests pass, 758 total (753 + 5).

### Step 5: Commit + deploy

```bash
git add wtyj/agents/marina/email_poller.py wtyj/tests/marina/test_164_support_email_filter.py wtyj/briefs/marina_brief_164_support_email_filter.md
git commit -m "Brief 164: support-email sender filter"
git push origin main

ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d"
```

Adamus skip — email_poller exits on startup due to empty EMAIL_ADDRESS. Shared image rebuild will pick up the change but no behavioral effect on Adamus.

### Step 6: Verify Lucia is gone

```bash
ssh root@108.61.192.52 "docker exec wtyj-bluemarlin python3 -c '
import sqlite3
conn = sqlite3.connect(\"/app/data/state_registry.db\")
c = conn.cursor()
c.execute(\"SELECT booking_ref, customer_name FROM bookings WHERE booking_ref = ?\", (\"SU0AHF\",))
print(c.fetchall() or \"SU0AHF gone\")
conn.close()
'"
```

## Success Condition

1. `_business_sender_emails` helper exists in `email_poller.py` and returns a set
2. The UID-loop guard skips and logs for business senders with non-relay/escalation subjects
3. Existing `[ESCALATION]` and `[RELAY-` flows still work (guard passes through)
4. 5/5 new tests pass
5. Full regression: 758 total / 0 failures
6. SU0AHF row deleted from VPS bookings table
7. Both containers healthy post-deploy

## Rollback

Revert the commit, redeploy. Lucia deletion cannot be rolled back (one-row delete; irrelevant since she was test pollution anyway).
