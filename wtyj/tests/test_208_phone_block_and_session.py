"""Brief 208: ignored_phones webhook filter + disk-persisted session token."""

import os

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from unittest.mock import MagicMock, patch


# ── Part 2: ignored_phones filter ──────────────────────────────────────────

@patch("agents.social.webhook_server.state_registry")
@patch("agents.social.webhook_server.config_loader")
@patch("agents.social.webhook_server.parse_zernio_webhook")
@patch("agents.social.webhook_server.send_typing_indicator")
def test_ignored_phone_dropped_at_webhook(
    mock_typing, mock_parse, mock_config, mock_state
):
    """When sender's digits-normalized id matches configured ignored_phones,
    _process_zernio_event returns early (no typing indicator, no dm_agent call)."""
    from agents.social.webhook_server import _process_zernio_event

    mock_parse.return_value = {
        "message_id": "msg-208-blocked",
        "conversation_id": "conv-208",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "account_id": "acct-1",
        "sender_id": "+599 9 513 3333",
        "sender_name": "Excluir",
        "text": "yo",
    }
    mock_state.wa_has_been_processed.return_value = False
    mock_config.get_raw.return_value = {"features": {"ignored_phones": ["+59995133333"]}}

    _process_zernio_event({"event": "message.received", "data": {}})

    mock_state.wa_mark_as_processed.assert_called_once()
    mock_typing.assert_not_called()


@patch("agents.social.webhook_server.state_registry")
@patch("agents.social.webhook_server.config_loader")
@patch("agents.social.webhook_server.parse_zernio_webhook")
@patch("agents.social.webhook_server.send_typing_indicator")
def test_non_ignored_phone_proceeds(mock_typing, mock_parse, mock_config, mock_state):
    """A non-ignored phone proceeds past the new filter (typing indicator
    sent, normal flow continues). Regression guard."""
    from agents.social.webhook_server import _process_zernio_event

    mock_parse.return_value = {
        "message_id": "msg-208-allowed",
        "conversation_id": "conv-208-ok",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "account_id": "acct-1",
        "sender_id": "+59912345678",
        "sender_name": "RealCustomer",
        "text": "hello",
    }
    mock_state.wa_has_been_processed.return_value = False
    mock_config.get_raw.return_value = {"features": {"ignored_phones": ["+59995133333"]}}

    _process_zernio_event({"event": "message.received", "data": {}})

    mock_typing.assert_called_once()


def test_normalize_phone_digits_strips_unicode_and_extension():
    """The helper normalizes only ASCII digits — Unicode digits and
    extension suffixes are stripped or excluded."""
    from agents.social.webhook_server import _normalize_phone_digits

    # ASCII E.164 with separators → digits only
    assert _normalize_phone_digits("+599 9 513 3333") == "59995133333"
    assert _normalize_phone_digits("+59995133333") == "59995133333"
    assert _normalize_phone_digits("599-9-513-3333") == "59995133333"

    # Extension suffix stripped
    assert _normalize_phone_digits("+59995133333 ext 1") == "59995133333"
    assert _normalize_phone_digits("+59995133333 x 99") == "59995133333"
    assert _normalize_phone_digits("+59995133333#101") == "59995133333"

    # Fullwidth Unicode digits → empty (regex [0-9] is ASCII-only)
    assert _normalize_phone_digits("+５９９９５１３３３３３") == ""

    # Empty / None → empty
    assert _normalize_phone_digits("") == ""
    assert _normalize_phone_digits(None) == ""


# ── Part 3: disk-persisted session token ───────────────────────────────────

def test_session_token_persists_across_init(tmp_path, monkeypatch):
    """A session-token-init helper that uses a deterministic disk path
    returns the SAME token on second invocation (persistence across
    simulated container restart). Mirrors the real _init_session_token's
    pattern using a tmp path."""
    import secrets

    fake_token_dir = tmp_path / "data"
    fake_token_dir.mkdir()
    fake_token_path = str(fake_token_dir / "session_token")

    def helper():
        if os.path.exists(fake_token_path):
            try:
                with open(fake_token_path, "r") as f:
                    v = f.read().strip()
                if v:
                    return v
            except OSError:
                pass
        new = secrets.token_hex(32)
        try:
            with open(fake_token_path, "w") as f:
                f.write(new)
            os.chmod(fake_token_path, 0o600)
        except OSError:
            pass
        return new

    first = helper()
    second = helper()
    assert first == second
    assert len(first) == 64

    # File exists with correct perms
    assert os.path.exists(fake_token_path)
    perms = oct(os.stat(fake_token_path).st_mode)[-3:]
    assert perms == "600", f"Expected 0600 perms, got {perms}"


def test_session_token_real_init_returns_persistent_value(monkeypatch, tmp_path):
    """Exercise the real dashboard.api._init_session_token by monkeypatching
    its path computation to use tmp_path. Confirms the production helper
    actually persists, not just our fake_helper."""
    import dashboard.api as api_module

    fake_token_dir = tmp_path / "data"
    fake_token_dir.mkdir()
    fake_token_path = str(fake_token_dir / "session_token")

    # Patch the path math: replace os.path.normpath/join with a stub returning
    # our fake path. We do this by monkeypatching os.path.join + normpath
    # specifically inside the module's namespace.
    real_join = os.path.join
    real_normpath = os.path.normpath
    real_dirname = os.path.dirname
    real_abspath = os.path.abspath

    def fake_join(*args):
        # Detect the session_token path build pattern and substitute
        if args and args[-1] == "session_token":
            return fake_token_path
        return real_join(*args)

    with monkeypatch.context() as m:
        m.setattr(os.path, "join", fake_join)
        first = api_module._init_session_token()
        second = api_module._init_session_token()

    assert first == second
    assert len(first) == 64
    assert os.path.exists(fake_token_path)
