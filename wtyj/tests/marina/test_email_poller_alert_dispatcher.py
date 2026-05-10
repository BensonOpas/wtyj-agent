"""Brief 247: email_poller runs in a separate supervisord process from
webhook_server. The alert dispatcher pointer (state_registry._alert_dispatcher)
must be registered IN that process for email-channel escalations to fire alerts.
Pre-Brief-247 the dispatcher was silently None in email_poller's process
because dashboard.api was never imported there - every email escalation
silently no-op'd alert delivery (production audit on issue #17 verified zero
alert_deliveries rows for any email-channel escalation in unboks)."""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WTYJ_DIR = REPO_ROOT / "wtyj"


def _wipe_escalations_for(customer_id: str):
    """Mirror of the _wipe_escalations_for helper used in test_217_alert_delivery
    (Brief 240+). Brief 227's dedup logic in create_pending_notification
    UPDATEs an existing pending row instead of inserting a new one when a
    matching customer_id+notification_type row already exists; without this
    pre-test wipe, re-runs of the test against a shared dev DB would
    exercise the update path instead of the insert path."""
    from shared import state_registry
    conn = state_registry._get_conn()
    conn.execute(
        "DELETE FROM pending_notifications WHERE customer_id = ? "
        "AND (notification_type LIKE '%escalat%' "
        "     OR notification_type IN ('soft_escalation','hard_escalation'))",
        (customer_id,))
    conn.execute(
        "DELETE FROM alert_deliveries WHERE escalation_id IN ("
        " SELECT id FROM pending_notifications WHERE customer_id = ?)",
        (customer_id,))
    conn.commit()
    conn.close()


def test_email_poller_subprocess_registers_alert_dispatcher():
    """In a fresh Python subprocess (mirroring how supervisord starts
    `python3 -m agents.marina.email_poller`), importing the email_poller
    module MUST cause state_registry._alert_dispatcher to become non-None.
    This is the actual production scenario; module-level Python state is
    per-process, so the registration must happen on email_poller's import.

    Pre-Brief-247 this test would have asserted False for both dispatchers
    in the fresh process, matching the production bug Calvin observed in
    issue #17 (email escalations silently no-op'd alert delivery)."""
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
    process, an email-channel escalation row triggers the dispatcher with
    channel='email'. Pre-Brief-247 the dispatcher was registered in tests
    but NOT in production's email_poller process -- this test catches the
    integration shape by asserting the dispatcher is invoked with
    channel='email' so a future regression that filters by channel would
    fail visibly."""
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    from shared import state_registry
    # Force-import dashboard.api to ensure the dispatcher is registered
    # (mirrors what Brief 247's side-effect import does in production).
    from dashboard import api as _dapi  # noqa: F401

    customer_id = "247_test_email@example.com"
    _wipe_escalations_for(customer_id)

    fired = {"called": False, "args": None, "kwargs": None}
    def capture(*a, **k):
        fired["called"] = True
        fired["args"] = a
        fired["kwargs"] = k
    monkeypatch.setattr(state_registry, "_alert_dispatcher", capture)

    state_registry.create_pending_notification(
        notification_type='escalation',
        channel='email',
        customer_id=customer_id,
        customer_name='Calvin Test 247',
        subject='[ESCALATION] Brief 247 test',
        body='test body for Brief 247',
        mode='hard',
    )
    assert fired["called"], (
        "alert dispatcher MUST fire for email-channel escalation rows; "
        "this regression existed for the entire history of email-channel "
        "escalations until Brief 247")
    # Dispatcher signature: (escalation_id, customer_name, channel, summary, ...)
    assert fired["args"][2] == 'email', (
        f"channel arg passed to dispatcher must be 'email' for an email "
        f"escalation; got args={fired['args']}")

    # Cleanup so the dev DB doesn't accumulate test rows across runs.
    _wipe_escalations_for(customer_id)
