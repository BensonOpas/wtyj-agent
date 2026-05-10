"""Brief 238 — Tenant isolation guard tests.

Cover the four guard branches (absent, permissive-allowed, permissive-unknown,
strict-unknown, strict-allowed) plus the integration of the guard at the
inbound webhook handler (DM branch and WhatsApp branch separately) and
outbound sender call sites.
"""
from unittest.mock import patch, MagicMock


def _stub_config(allowlist_block):
    """Return a get_raw() stub returning a config with the given allowlist
    block (or no block at all when allowlist_block is None)."""
    cfg = {}
    if allowlist_block is not None:
        cfg["channel_account_allowlist"] = allowlist_block
    return MagicMock(return_value=cfg)


def test_guard_returns_true_when_block_absent():
    """No allowlist block in client.json → no enforcement, no log entry."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config(None)), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("any_account_id",
                                               direction="inbound") is True
        mock_log.assert_not_called()


def test_guard_strict_blocks_unknown_account_and_logs():
    """Strict mode + account not in list → returns False, logs unknown event."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config({"mode": "strict",
                             "zernio_accounts": ["aaa111"]})), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("bbb222",
                                               direction="inbound") is False
        mock_log.assert_called_once()
        args, kwargs = mock_log.call_args
        assert args[0] == "tenant_guard_account_unknown"
        assert kwargs["mode"] == "strict"
        assert kwargs["direction"] == "inbound"


def test_guard_permissive_allows_unknown_account_but_logs():
    """Permissive mode + account not in list → returns True, still logs."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config({"mode": "permissive",
                             "zernio_accounts": []})), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("ccc333",
                                               direction="outbound") is True
        mock_log.assert_called_once()
        assert mock_log.call_args.kwargs["mode"] == "permissive"


def test_guard_strict_allows_listed_account_with_no_log():
    """Strict mode + account is in list → returns True, no log entry."""
    from shared import tenant_guard
    with patch("shared.tenant_guard.config_loader.get_raw",
               _stub_config({"mode": "strict",
                             "zernio_accounts": ["aaa111", "bbb222"]})), \
         patch("shared.tenant_guard.bm_logger.log") as mock_log:
        assert tenant_guard.is_account_allowed("aaa111",
                                               direction="inbound") is True
        mock_log.assert_not_called()


def test_inbound_dm_handler_skipped_on_strict_mismatch():
    """webhook_server._process_zernio_event with platform=instagram and a
    strict-mismatch account must NOT call handle_incoming_dm.

    Use the DM (non-WhatsApp) branch because that's where downstream handlers
    are directly observable; the WhatsApp branch only buffers, which is
    covered by the next test.

    Both tenant_guard and webhook_server import config_loader as a module
    (`from shared import config_loader`), so both reference the same
    `shared.config_loader.get_raw` callable. A single patch on that path
    serves both call sites — return a dict containing BOTH the allowlist
    block (read by tenant_guard) and the features block (read by
    webhook_server's booking_flow lookup)."""
    from agents.social import webhook_server
    payload = {"event": "message.received", "data": {
        "id": "msgB238a", "conversationId": "convB238a",
        "accountId": "not_allowlisted", "platform": "instagram",
        "text": "hi", "sender": {"name": "Test"}}}
    fake_cfg = {
        "channel_account_allowlist": {
            "mode": "strict", "zernio_accounts": ["only_this_one"]},
        "features": {"booking_flow": False},
    }
    parsed = {"conversation_id": "convB238a", "platform": "instagram",
              "channel": "instagram_dm", "sender_name": "Test", "sender_id": "s1",
              "text": "hi", "message_id": "msgB238a", "account_id": "not_allowlisted"}
    with patch("agents.social.webhook_server.parse_zernio_webhook", return_value=parsed), \
         patch("agents.social.webhook_server.state_registry.wa_has_been_processed",
               return_value=False), \
         patch("agents.social.webhook_server.state_registry.wa_mark_as_processed"), \
         patch("agents.social.webhook_server.send_typing_indicator"), \
         patch("shared.config_loader.get_raw", return_value=fake_cfg), \
         patch("agents.social.webhook_server.handle_incoming_dm") as mock_dm:
        webhook_server._process_zernio_event(payload)
        mock_dm.assert_not_called()


def test_inbound_whatsapp_buffer_skipped_on_strict_mismatch():
    """webhook_server._process_zernio_event with platform=whatsapp and a
    strict-mismatch account must NOT call _buffer_message.

    The WhatsApp-via-Zernio branch routes through _buffer_message (debounce);
    the guard must prevent that call when the account is not allowlisted."""
    from agents.social import webhook_server
    payload = {"event": "message.received", "data": {
        "id": "msgB238b", "conversationId": "convB238b",
        "accountId": "not_allowlisted", "platform": "whatsapp",
        "text": "hi", "sender": {"name": "Test"}}}
    fake_cfg = {"channel_account_allowlist": {
        "mode": "strict", "zernio_accounts": ["only_this_one"]}}
    parsed = {"conversation_id": "convB238b", "platform": "whatsapp",
              "channel": "whatsapp", "sender_name": "Test", "sender_id": "s1",
              "text": "hi", "message_id": "msgB238b", "account_id": "not_allowlisted"}
    with patch("agents.social.webhook_server.parse_zernio_webhook", return_value=parsed), \
         patch("agents.social.webhook_server.state_registry.wa_has_been_processed",
               return_value=False), \
         patch("agents.social.webhook_server.state_registry.wa_mark_as_processed"), \
         patch("agents.social.webhook_server.send_typing_indicator"), \
         patch("shared.config_loader.get_raw", return_value=fake_cfg), \
         patch("agents.social.webhook_server._buffer_message") as mock_buffer:
        webhook_server._process_zernio_event(payload)
        mock_buffer.assert_not_called()


def test_outbound_sender_blocks_strict_mismatch_before_zernio_call():
    """ZernioSender.send with a strict-mismatch account must NOT call
    send_dm_reply (the actual Zernio API wrapper)."""
    from agents.social.senders.zernio import ZernioSender
    fake_cfg = {"channel_account_allowlist": {
        "mode": "strict", "zernio_accounts": ["only_this_one"]}}
    with patch("shared.config_loader.get_raw", return_value=fake_cfg), \
         patch("agents.social.senders.zernio.send_dm_reply") as mock_send:
        result = ZernioSender.send("convX", "wrong_account", "hello")
        assert result is False
        mock_send.assert_not_called()
