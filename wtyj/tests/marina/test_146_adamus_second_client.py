"""
Brief 146 — Adamus second-client deployment tests.

Verifies:
1. email_poller graceful exit when EMAIL_ADDRESS or refresh token is missing.
2. Adamus client.json is valid and has the expected restaurant config.
3. Adamus docker-compose is set up to run on port 8002 against the pre-built image.
"""
import json
import os

import pytest

# conftest.py adds bluemarlin/ root to sys.path; we only need path constants here.
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_BM_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

ADAMUS_CLIENT_JSON = os.path.join(_REPO_ROOT, "clients", "adamus", "config", "client.json")
ADAMUS_DOCKER_COMPOSE = os.path.join(_REPO_ROOT, "clients", "adamus", "docker-compose.yml")


# ---------------------------------------------------------------------------
# email_poller graceful exit tests
# ---------------------------------------------------------------------------

def test_email_poller_exits_cleanly_when_email_address_empty(monkeypatch, caplog):
    """When EMAIL_ADDR is empty, main() should return immediately with a log."""
    import logging
    from agents.marina import email_poller

    monkeypatch.setattr(email_poller, "EMAIL_ADDR", "")

    # caplog captures stdlib logging, but email_poller uses its own log() which
    # writes to stdout. Capture stdout instead.
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = email_poller.main()

    assert result is None
    assert "Email polling disabled" in buf.getvalue()
    assert "EMAIL_ADDRESS=empty" in buf.getvalue()


def test_email_poller_exits_cleanly_when_refresh_token_missing(monkeypatch, tmp_path):
    """When refresh token file is missing, main() should return immediately."""
    from agents.marina import email_poller

    monkeypatch.setattr(email_poller, "EMAIL_ADDR", "test@example.com")
    monkeypatch.setattr(email_poller, "REFRESH_TOKEN_PATH", str(tmp_path / "does_not_exist.txt"))

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = email_poller.main()

    assert result is None
    assert "Email polling disabled" in buf.getvalue()
    assert "refresh_token=missing" in buf.getvalue()


class _SentinelException(BaseException):
    """Inherits from BaseException (not Exception) so the main loop's
    `except Exception` handler does NOT catch it. This lets us break out
    of the `while True` loop on the first iteration."""
    pass


def test_email_poller_proceeds_past_guard_when_both_present(monkeypatch, tmp_path):
    """When both EMAIL_ADDR and refresh token are present, main() should
    proceed past the guard and hit imap_connect. We monkeypatch imap_connect
    to raise a BaseException subclass (so the except Exception handler in
    the main loop doesn't swallow it) and assert it propagates out."""
    from agents.marina import email_poller

    # Create a temp token file
    token_file = tmp_path / "token.txt"
    token_file.write_text("fake-refresh-token")

    # Also monkeypatch THREAD_STATE_PATH so load_json doesn't touch the dev
    # checkout's bluemarlin/config/email_thread_state.json.
    fake_state_path = tmp_path / "thread_state.json"

    monkeypatch.setattr(email_poller, "EMAIL_ADDR", "test@example.com")
    monkeypatch.setattr(email_poller, "REFRESH_TOKEN_PATH", str(token_file))
    monkeypatch.setattr(email_poller, "THREAD_STATE_PATH", str(fake_state_path))

    def _fail(*_a, **_kw):
        raise _SentinelException("reached imap_connect")

    monkeypatch.setattr(email_poller, "imap_connect", _fail)

    with pytest.raises(_SentinelException, match="reached imap_connect"):
        email_poller.main()
    # The real guard against touching bluemarlin/config/email_thread_state.json
    # is the THREAD_STATE_PATH monkeypatch above. Sentinel propagation here
    # proves we got past the guard without hitting imap_connect's real body.


# ---------------------------------------------------------------------------
# Adamus client.json tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def adamus_config():
    with open(ADAMUS_CLIENT_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def adamus_config_text():
    with open(ADAMUS_CLIENT_JSON, "r", encoding="utf-8") as f:
        return f.read()


def test_adamus_client_json_is_valid_json(adamus_config):
    assert isinstance(adamus_config, dict)
    assert "business" in adamus_config
    assert "services" in adamus_config
    assert "terminology" in adamus_config


def test_adamus_client_json_has_sofia_agent(adamus_config):
    b = adamus_config["business"]
    assert b["agent_name"] == "Sofia"
    assert b["agent_signature"].startswith("Sofia")
    assert b["name"] == "Restaurant Adamus"


def test_adamus_client_json_uses_restaurant_terminology(adamus_config):
    t = adamus_config["terminology"]
    assert t["service_label"] == "reservation"
    assert t["party_size_label"] == "diners"
    assert t["slot_label"] == "seating"


def test_adamus_client_json_has_real_calendar_ids(adamus_config):
    services = adamus_config["services"]
    lunch_cal = services["lunch"]["slots"][0]["calendar_id"]
    dinner_cal = services["dinner"]["slots"][0]["calendar_id"]
    assert lunch_cal.startswith("c3058824908775"), f"lunch calendar id unexpected: {lunch_cal}"
    assert dinner_cal.startswith("5b51d6514c5576"), f"dinner calendar id unexpected: {dinner_cal}"
    assert lunch_cal.endswith("@group.calendar.google.com")
    assert dinner_cal.endswith("@group.calendar.google.com")


def test_adamus_client_json_has_real_spreadsheet_id(adamus_config):
    assert adamus_config["business"]["spreadsheet_id"] == "1OYtPI5Fn7btaPROsJgtpXnoWR025cbjHWudHx2a8ggc"


def test_adamus_payment_timing_is_none(adamus_config):
    p = adamus_config["payment"]
    assert p["timing"] == "none"
    assert p["hold_duration_hours"] == 4


def test_adamus_group_threshold_is_12(adamus_config):
    assert adamus_config["booking_rules"]["group_threshold_requires_human"] == 12


def test_adamus_client_json_no_bluefinn_references(adamus_config_text):
    """Guard against charter vocabulary leaking into Adamus config."""
    forbidden = ["BlueFinn", "bluefinn", "charter", "Charter", "boat", "trip", "Trip"]
    for needle in forbidden:
        assert needle not in adamus_config_text, f"forbidden string '{needle}' found in Adamus client.json"

    # "Marina" is forbidden as a standalone word; allow only the 'marina_persona' key.
    # Strip the permitted occurrences and then check nothing else remains.
    scrubbed = adamus_config_text.replace("marina_persona", "###")
    # Case-sensitive check for capital-M Marina
    assert "Marina" not in scrubbed, "Marina (capitalized) found in Adamus client.json"


# ---------------------------------------------------------------------------
# Adamus docker-compose.yml tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def adamus_compose_text():
    with open(ADAMUS_DOCKER_COMPOSE, "r", encoding="utf-8") as f:
        return f.read()


def test_adamus_docker_compose_uses_prebuilt_image(adamus_compose_text):
    # Brief 152: image renamed from root-bluemarlin to wtyj-agent
    assert "image: wtyj-agent" in adamus_compose_text
    assert "build:" not in adamus_compose_text


def test_adamus_docker_compose_port_8002(adamus_compose_text):
    assert '"8002:8001"' in adamus_compose_text


def test_adamus_docker_compose_container_name(adamus_compose_text):
    # Brief 152: container renamed from bluemarlin-adamus to wtyj-adamus
    assert "wtyj-adamus" in adamus_compose_text
