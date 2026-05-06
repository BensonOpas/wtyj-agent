"""Brief 204: Gmail app-password auth path in email_adapter.py."""

import os

# Match established test pattern
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from unittest.mock import MagicMock, patch


@patch("agents.marina.email_adapter.imaplib.IMAP4_SSL")
def test_imap_connect_uses_gmail_login_when_password_set(mock_imap_class):
    """When EMAIL_PASSWORD is set, imap_connect connects to imap.gmail.com
    and uses LOGIN auth (no OAuth call)."""
    import agents.marina.email_adapter as adapter

    mock_im = MagicMock()
    mock_imap_class.return_value = mock_im

    with patch.object(adapter, "EMAIL_PASSWORD", "abcdwxyz12345678"), \
         patch.object(adapter, "EMAIL_ADDR", "hello@unboks.org"):
        result = adapter.imap_connect()

    # Connected to Gmail
    mock_imap_class.assert_called_once_with("imap.gmail.com", 993)
    # LOGIN auth (not XOAUTH2)
    mock_im.login.assert_called_once_with("hello@unboks.org", "abcdwxyz12345678")
    # XOAUTH2 path NOT taken
    mock_im.authenticate.assert_not_called()
    assert result is mock_im


@patch("agents.marina.email_adapter.imaplib.IMAP4_SSL")
@patch("agents.marina.email_adapter.oauth_token")
def test_imap_connect_uses_microsoft_oauth_when_no_password(mock_oauth, mock_imap_class):
    """When EMAIL_PASSWORD is empty (BlueMarlin's case), imap_connect uses the
    existing Microsoft OAuth XOAUTH2 path."""
    import agents.marina.email_adapter as adapter

    mock_oauth.return_value = "fake-access-token"
    mock_im = MagicMock()
    mock_imap_class.return_value = mock_im

    with patch.object(adapter, "EMAIL_PASSWORD", ""), \
         patch.object(adapter, "EMAIL_ADDR", "hello@wetakeyourjob.com"):
        result = adapter.imap_connect()

    # Connected to Outlook (NOT Gmail)
    mock_imap_class.assert_called_once_with("outlook.office365.com", 993)
    # OAuth was called
    mock_oauth.assert_called_once()
    # XOAUTH2 auth (not LOGIN)
    mock_im.authenticate.assert_called_once()
    args, _ = mock_im.authenticate.call_args
    assert args[0] == "XOAUTH2"
    # LOGIN path NOT taken
    mock_im.login.assert_not_called()
    assert result is mock_im


@patch("agents.marina.email_adapter.smtplib.SMTP")
def test_smtp_send_uses_gmail_login_when_password_set(mock_smtp_class):
    """When EMAIL_PASSWORD is set, smtp_send connects to smtp.gmail.com and
    uses LOGIN auth (no OAuth XOAUTH2 dance)."""
    import agents.marina.email_adapter as adapter

    mock_s = MagicMock()
    mock_smtp_class.return_value = mock_s

    with patch.object(adapter, "EMAIL_PASSWORD", "abcdwxyz12345678"), \
         patch.object(adapter, "EMAIL_ADDR", "hello@unboks.org"):
        adapter.smtp_send("recipient@example.com", "Test subject", "Test body")

    # Connected to Gmail SMTP (positional args + timeout kwarg matches existing pattern)
    mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
    # LOGIN auth used (not docmd("AUTH", "XOAUTH2 ...") path)
    mock_s.login.assert_called_once_with("hello@unboks.org", "abcdwxyz12345678")
    mock_s.docmd.assert_not_called()
    # STARTTLS dance still runs
    mock_s.starttls.assert_called_once()
    # Mail was sent + connection closed
    mock_s.sendmail.assert_called_once()
    mock_s.quit.assert_called_once()
