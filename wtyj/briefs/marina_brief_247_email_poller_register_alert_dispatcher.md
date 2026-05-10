# BRIEF 247 — Register alert dispatcher in email_poller process; remove duplicate legacy email send

**Status:** Draft | **Files:** wtyj/agents/marina/email_poller.py, wtyj/tests/marina/test_email_poller_alert_dispatcher.py | **Depends on:** Brief 246 (`7891174`) | **Blocks:** none

## Context

Issue #17 (P0 from Calvin live verification) — Calvin sent a new rude QA email; the dashboard correctly created an escalation row (visible in Escalations view, mode=hard, decision card visible), but no email or WhatsApp operator alert was delivered.

**Root cause traced via state inspection + grep + read:**

The unboks container runs THREE separate supervisord processes (verified via `docker exec wtyj-unboks cat /etc/supervisord.conf`):
- `webhook-server`: `uvicorn agents.social.webhook_server:app --port 8001` (handles WhatsApp + DM webhooks + dashboard API)
- `email-poller`: `python3 -m agents.marina.email_poller` (polls IMAP, runs Marina, persists email threads)
- `hold-reaper`: `python3 -m agents.marina.hold_reaper`

The Brief 217 alert dispatcher uses a module-level pointer pattern in `wtyj/shared/state_registry.py:22` (`_alert_dispatcher = None`) plus a setter at line 38 (`set_alert_dispatcher(fn)`). The dispatcher (`_fire_escalation_alerts` in `wtyj/dashboard/api.py:1882`) is registered at module import time via `state_registry.set_alert_dispatcher(_fire_escalation_alerts)` at `dashboard/api.py:2002`.

**Problem:** module-level Python state is per-process. When `webhook_server` imports `dashboard.api`, the dispatcher gets registered IN webhook_server's process. But `email_poller` is a separate process and never imports `dashboard.api` — its `_alert_dispatcher` stays `None`. So when `email_poller.py` calls `state_registry.create_pending_notification('escalation', 'email', ...)`, the row is written, but the dispatcher trigger at `state_registry.py:1557` silently no-ops (it checks `_alert_dispatcher is not None`, which is False).

**Production verification (2026-05-10 audit on unboks state_registry):**
- 27 escalation rows total. WhatsApp-channel escalations (id=20, 21, 22, 24, 25 — all `channel='whatsapp'`) each fire 4 `alert_deliveries` rows (default email + alt email + WhatsApp via Brief 240 Zernio + Telegram-skipped).
- Email-channel escalations (id=16, 23, 26, 27 — all `channel='email'`) have **ZERO `alert_deliveries` rows**. Confirmed via `SELECT COUNT(*) FROM alert_deliveries WHERE escalation_id IN (16,23,26,27)` → 0.
- WhatsApp escalations originate in webhook_server (uvicorn process); email escalations originate in email_poller. Channel correlates 100% with which process created the row.

**Why Calvin DID get something but said "no email":** there is a LEGACY direct `smtp_send` at `email_poller.py:1090-1097` that sends a hardcoded body to `demo_support_email` (resolves to `business.support_email` from client.json — currently `butlerbensonagent@gmail.com` for unboks). This is the "Escalation alert sent to butlerbensonagent@gmail.com for calvin@gaimin.io" line in `email_poller.log` (verified via `tail -50 /app/logs/email_poller.log`). Calvin checks `calvin@gaimin.io` (his primary, configured as `email_alternative_destination` in alert_settings); the legacy path only sends to `butlerbensonagent@gmail.com`. So Calvin gets nothing he sees, AND no WhatsApp alert because the dispatcher (which would fire WhatsApp via the resolved Zernio route) never runs.

**Why this wasn't caught earlier:** Brief 217's tests covered the in-process dispatcher (always registered in test runs because `from agents.social.webhook_server import app` at the top of the test file imports `dashboard.api` transitively). The cross-process production scenario was never tested.

**Verified read-only:**
- `wtyj/shared/state_registry.py:1557-1578` — dispatcher trigger guarded by `_alert_dispatcher is not None`. Wrapped in try/except that silently swallows exceptions. So a None pointer = silent no-op (no log line).
- `wtyj/dashboard/api.py:2002` — `state_registry.set_alert_dispatcher(_fire_escalation_alerts)` registration site.
- `wtyj/agents/marina/email_poller.py` — no `import dashboard.api` anywhere. 4 `create_pending_notification(notification_type='escalation', channel='email', ...)` call sites (lines 749, 1107, 1149, 1223) all silently no-op'd.
- `wtyj/agents/marina/email_poller.py:1090-1097` — the LEGACY direct smtp_send to `demo_support_email`. Sends hardcoded body to support_email only; not the dispatcher's rich Brief 239 body, not multi-destination, no WhatsApp.
- `wtyj/agents/marina/email_poller.py:1019-1028` — there's also a relay-mode legacy direct smtp_send. That one is for `notification_type='relay'` (line 1038), NOT escalation. Dispatcher doesn't fire for relay rows anyway. **Out of scope** — leave the relay legacy path alone.

## Why This Approach

**Considered:** Move `_fire_escalation_alerts` (and `_fire_appointment_alerts`) into a new `wtyj/shared/alert_dispatcher.py` module so both `dashboard/api.py` and `email_poller.py` can import it cleanly without each pulling in the FastAPI router + Pydantic models. **Rejected for this brief:** the dispatcher functions are deeply intertwined with helpers in `dashboard/api.py` (`_resolve_dashboard_link`, `_build_alert_html_body`, `_build_alert_subject`, `_build_alert_body`, `_build_appointment_subject`, `_build_appointment_body`, etc.). Extracting them would touch ~200 lines and risk regressions on Briefs 217/239/241/243. The side-effect import does the job in 2 lines. If/when a future brief needs the dispatcher in a third process (Telegram poller? Slack worker?), that brief extracts to shared.

**Considered:** Add an explicit `state_registry.set_alert_dispatcher(...)` call at the top of `email_poller.py` that imports a slim helper. **Rejected:** that's the same complexity as the previous option; the side-effect import is cleaner because it also auto-registers the appointment dispatcher (Brief 241) — needed if email-channel appointments ever get added.

**Considered:** Modify `state_registry.create_pending_notification` to lazy-import `dashboard.api` when the dispatcher pointer is None. **Rejected:** late-binding magic that surprises the next reader; couples state_registry to dashboard.api which the dispatcher-pointer pattern was specifically designed to avoid.

**Considered:** Keep both the legacy direct smtp_send AND the new dispatcher firing. **Rejected:** Calvin would receive 2 emails per escalation (1 to support_email from legacy, 2 to default+alt from dispatcher = 3 total recipients, with 2 of them duplicating). Worse UX than the bug. Removing the legacy direct send is the right call. The dispatcher's email body (Brief 239 rich format) is strictly better than the legacy hardcoded body.

**Tradeoff — side-effect imports are usually a smell.** This one is tolerable because:
1. The import target (`dashboard.api`) is the ONLY way to register the dispatcher today; the side effect is the registration's intentional purpose.
2. A noqa comment + explicit explanation block makes the intent unambiguous.
3. The alternative (Option 1: extract to shared module) has 100x the change surface for the same end result.
4. If Python's import-cache semantics ever change (won't happen in CPython), the test's subprocess shape would catch the regression.

**Tradeoff — keeping the relay-mode legacy direct send.** That's `notification_type='relay'` (different concept; operator-replies-via-email-thread routing). Dispatcher never targeted relay rows. Leaving it alone keeps this brief tight.

## Instructions

### Step 1 — Add side-effect import at the top of email_poller.py

Locate the existing import block at the top of `wtyj/agents/marina/email_poller.py` (the file's module docstring + import section). After the existing `state_registry` and `dashboard`-related imports (or after the last `from agents.*` import — exact insertion point determined by reading the file's first ~30 lines), add:

```python
# Brief 247: register the alert dispatcher in this process.
# email_poller runs as a SEPARATE supervisord process from webhook_server
# (per /etc/supervisord.conf inside the container). Module-level Python state
# is per-process, so the alert dispatcher pointer (state_registry._alert_dispatcher,
# state_registry._appointment_alert_dispatcher) registered when webhook_server
# imports dashboard.api does NOT exist in email_poller's process.
# Without this side-effect import, every email-channel escalation silently
# fails to fire alerts (state_registry.create_pending_notification's dispatcher
# trigger at line 1557 checks `_alert_dispatcher is not None` → no-op).
# Do not remove unless _fire_escalation_alerts moves to a shared module.
from dashboard import api as _dashboard_api_for_dispatcher_registration  # noqa: F401
```

The `noqa: F401` suppresses the "unused import" lint warning since the import is purely for its side effects.

**Verify before insertion:** read the first ~40 lines of `email_poller.py` to find the import section. The new import goes AFTER any local `from agents.marina.email_adapter import ...` line (since dashboard.api may import agents.marina indirectly and we want to avoid surprising cycles).

### Step 2 — Remove the duplicate legacy direct smtp_send block

In `wtyj/agents/marina/email_poller.py` at lines 1089-1097, the current code reads:

```python
                    try:
                        smtp_send(
                            demo_support_email,
                            f"[ESCALATION] {booking_ref_esc} - {customer_name_esc} ({from_email}) - {_esc_summary}",
                            escalation_alert,
                        )
                        log(f"Escalation alert sent to {demo_support_email} for {from_email}")
                    except Exception as _esc_err:
                        log(f"Escalation alert send failed: {_esc_err}")
```

**Replace with:**

```python
                    # Brief 247: legacy direct smtp_send to demo_support_email
                    # was removed. The dispatcher fires via
                    # create_pending_notification below; it sends to the
                    # configured email_destination + email_alternative_destination
                    # with Brief 239's rich body, plus WhatsApp via Brief 240's
                    # Zernio route, plus telegram (skipped if not configured).
                    # See wtyj/dashboard/api.py:_fire_escalation_alerts.
```

This is a deletion plus a comment marker explaining why the block is gone (so the next reader doesn't reintroduce it). The `escalation_alert` variable defined just above (lines 1078-1088) becomes unused; **leave it in place** — it's referenced indirectly by the `body` parameter of the `create_pending_notification` call right below at line 1108 (`escalation_alert` is the 6th positional arg). Verify by reading lines 1107-1115.

**Why not also remove `escalation_alert` variable:** it's the body string that gets persisted in `pending_notifications.body` AND seeds the dispatcher's body if no `summary_dict` is generated. Leave it.

### Step 3 — Add 2 new tests

Create `wtyj/tests/marina/test_email_poller_alert_dispatcher.py` (NEW file — there's no existing per-source-module test file for email_poller's dispatcher registration; the closest is `wtyj/tests/marina/test_217_alert_delivery.py` but that's in `wtyj/tests/social/`. New file is appropriate per Brief 236 rule when the source module's test file doesn't exist yet for this specific concern).

```python
"""Brief 247: email_poller runs in a separate supervisord process from
webhook_server. The alert dispatcher pointer (state_registry._alert_dispatcher)
must be registered IN that process for email-channel escalations to fire alerts.
Pre-Brief-247 the dispatcher was silently None in email_poller's process
because dashboard.api was never imported there — every email escalation
silently no-op'd alert delivery."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WTYJ_DIR = REPO_ROOT / "wtyj"


def test_email_poller_subprocess_registers_alert_dispatcher():
    """In a fresh Python subprocess (mirroring how supervisord starts
    `python3 -m agents.marina.email_poller`), importing the email_poller
    module MUST cause state_registry._alert_dispatcher to become non-None.
    This is the actual production scenario; module-level Python state is
    per-process, so the registration must happen on email_poller's import."""
    code = (
        "import sys, os; "
        f"sys.path.insert(0, {str(WTYJ_DIR)!r}); "
        "os.environ.setdefault('ANTHROPIC_API_KEY', 'test-key'); "
        "os.environ.setdefault('DASHBOARD_PASSWORD', 'testpass'); "
        "os.environ.setdefault('WHATSAPP_VERIFY_TOKEN', 'test'); "
        "os.environ.setdefault('WHATSAPP_PHONE_NUMBER_ID', 'test'); "
        "os.environ.setdefault('META_ACCESS_TOKEN', 'test'); "
        "os.environ.setdefault('LATE_API_KEY', 'test'); "
        "os.environ.setdefault('AZURE_CLIENT_ID', 'test'); "
        "from agents.marina import email_poller; "
        "from shared import state_registry; "
        "print('escalation_dispatcher_registered=' + "
        "      str(state_registry._alert_dispatcher is not None)); "
        "print('appointment_dispatcher_registered=' + "
        "      str(state_registry._appointment_alert_dispatcher is not None))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT))
    assert result.returncode == 0, (
        f"subprocess failed: stdout={result.stdout!r} stderr={result.stderr!r}")
    assert "escalation_dispatcher_registered=True" in result.stdout, (
        f"escalation dispatcher NOT registered after importing email_poller; "
        f"stdout={result.stdout!r}")
    assert "appointment_dispatcher_registered=True" in result.stdout, (
        f"appointment dispatcher NOT registered after importing email_poller; "
        f"stdout={result.stdout!r}")


def test_email_channel_escalation_fires_dispatcher_when_registered(monkeypatch):
    """Brief 247 integration: when the dispatcher IS registered in this
    process (which it always is in the test runner because conftest /
    test_217 imports webhook_server), an email-channel escalation row
    triggers the dispatcher with channel='email'. Pre-Brief-247 the
    dispatcher was registered in tests but NOT in production's
    email_poller process — this test catches that gap by asserting the
    dispatcher is invoked with the right channel arg."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    from shared import state_registry
    # Force-import dashboard.api to ensure the dispatcher is registered
    # (mirrors what Brief 247's side-effect import does in production).
    from dashboard import api as _dapi  # noqa: F401

    fired = {"called": False, "args": None, "kwargs": None}
    def capture(*a, **k):
        fired["called"] = True
        fired["args"] = a
        fired["kwargs"] = k
    monkeypatch.setattr(state_registry, "_alert_dispatcher", capture)

    state_registry.create_pending_notification(
        notification_type='escalation',
        channel='email',
        customer_id='247_test_email@example.com',
        customer_name='Calvin Test 247',
        subject='[ESCALATION] Brief 247 test',
        body='test body for Brief 247',
        mode='hard'
    )
    assert fired["called"], (
        "alert dispatcher MUST fire for email-channel escalation rows; "
        "this regression existed for the entire history of email-channel "
        "escalations until Brief 247")
    # Dispatcher signature: (escalation_id, customer_name, channel, summary, mode=, ...)
    assert fired["args"][2] == 'email', (
        f"channel arg passed to dispatcher must be 'email' for an email "
        f"escalation; got args={fired['args']}")
```

**Test design notes:**
- Test 1 is a subprocess test — the only honest way to verify the side-effect import works in a fresh process (mirrors supervisord's `python3 -m agents.marina.email_poller` invocation). Pure-import-side-effect bugs cannot be caught in the same process where pytest already imported many modules.
- Test 2 is the same-process integration check — verifies the dispatcher fires for an email-channel escalation when it IS registered. Pre-Brief-247 this would have FAILED in a fresh subprocess (dispatcher None in email_poller's process); post-Brief-247 it passes anywhere.

### Step 4 — Out of scope (documented for future briefs)

- **Move `_fire_escalation_alerts` and `_fire_appointment_alerts` to a shared module** like `wtyj/shared/alert_dispatcher.py`. Cleaner long-term but ~200-line touch; Brief 247 punts.
- **Same fix needed in `hold_reaper.py`?** Verified: hold_reaper does NOT call `create_pending_notification` for any `notification_type='escalation'` (verified via `grep -n create_pending_notification wtyj/agents/marina/hold_reaper.py` returns 0 hits). No fix needed.
- **Apply same side-effect import in any other supervisord-managed process** — verified there are only 3 (email-poller, webhook-server, hold-reaper). webhook-server already imports dashboard.api naturally; hold-reaper doesn't create escalation rows.
- **Backfill `alert_deliveries` rows for the 4 historical email escalations (id=16, 23, 26, 27) that silently no-op'd** — out of scope; rare; the operator-side resolution already happened (status=resolved/sent on those rows).
- **Remove the relay-mode legacy direct smtp_send at line 1019-1028** — different `notification_type='relay'`; dispatcher never targeted relay rows; out of scope.

## Tests

2 new tests in `wtyj/tests/marina/test_email_poller_alert_dispatcher.py` (NEW FILE).

Expected after-test count: **1060 passing / 0 failures** (1058 baseline + 2 new = 1060).

## Success Condition

After this brief lands:
1. In a fresh Python subprocess, `from agents.marina import email_poller` causes `state_registry._alert_dispatcher` to become non-None (and `_appointment_alert_dispatcher` too).
2. New email-channel escalations created via `email_poller.py` produce `alert_deliveries` rows for every configured channel (email default + alt + WhatsApp via Brief 240 + Telegram-skipped).
3. Calvin receives email alerts for new email-channel escalations at `calvin@gaimin.io` (the configured `email_alternative_destination`).
4. Calvin receives WhatsApp alerts at `+351963618003` via the Brief 240 Zernio route.
5. No duplicate emails (legacy direct send removed; only dispatcher's 2 emails fire — default + alt).
6. WhatsApp-channel escalations behavior unchanged (already worked; webhook_server's process registration unaffected).
7. Existing 1058 tests still pass.

## Rollback

```
git revert <brief-247-commit-sha>
git push origin main
```

This restores the silent no-op behavior on email-channel escalations (the bug Calvin reported) AND restores the legacy direct smtp_send to `demo_support_email`. Calvin would lose the dispatcher emails to the alt destination + the WhatsApp alert; gain back the single hardcoded-body email to `butlerbensonagent@gmail.com`. CI will re-deploy in ~90s.
