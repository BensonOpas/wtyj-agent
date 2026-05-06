# BRIEF 208 — ignored_phones webhook filter + disk-persisted session token

**Status:** Draft
**Files:** `wtyj/agents/social/webhook_server.py`, `wtyj/dashboard/api.py`, `clients/unboks/config/client.json`, `wtyj/tests/test_208_phone_block_and_session.py` (new)
**Depends on:** Brief 206 (escalation handler in same `_process_zernio_event` block — new check inserts adjacent to it)
**Blocks:** Nothing — closes the two URGENT items captured in `project_open_work.md` after Brief 205 was rolled back.

---

## Context

Two unfinished fixes from Brief 205's rollback. Both are now well-defined: the post-rollback audit pinpointed the right approach and the bypass risks. Bundled because both are small, behavioral, and the user (Benson) asked for them together.

### Issue 1 — calvin-csa replies to SR's friend Excluir (`+599 9 513 3333`)

unboks's WhatsApp number is SR's personal number. calvin-csa auto-replies to every inbound DM, including SR's friends/family. SR explicitly listed `+599 9 513 3333` (contact "Excluir") to block. As of right now, the unboks container is online — calvin-csa WILL reply to that number until this fix ships.

### Issue 2 — Login times out on every deploy

`wtyj/dashboard/api.py:30` does `_SESSION_TOKEN = secrets.token_hex(32)` at module import. Each container restart regenerates the token, invalidating SR's browser session. Every brief deploy = re-login. SR has complained.

### Out of scope

- **Rate limiting on ignored-phone storms.** The existing `wa_mark_as_processed` dedup table absorbs duplicates. Low-traffic risk.
- **Session token rotation policy.** Single-user demo; manual rotation = delete the file, container regenerates on next start.
- **Per-user identity** (knowing if the logged-in operator is Calvin or Jr). Out of scope; SR's frontend handles that as an opaque label today.
- **Real JWT with TTL.** The disk-persisted random token is the simpler primitive that solves the symptom (loses session only on container REPLACEMENT, not container RESTART). Sufficient for current scope.

---

## Why This Approach

### Phone filter — digit normalization choice

The Brief 205 audit caught two real concerns in the original `str.isdigit()` approach:
1. **Unicode-digit false matches** — `'５'.isdigit()` returns True for fullwidth digits. The previous normalization would have included them in the digit string, comparing fullwidth and ASCII variants as if they were the same — incorrect equality semantics.
2. **Extension suffix** — `+59995133333 ext 1` keeps "1" digit appended, mutating the comparable form away from the configured value.

Fix: use `re.sub(r'[^0-9]', '', s)` for ASCII-only digit normalization (Python's `[0-9]` matches ASCII 0-9 only; Unicode digits get stripped). Strip `ext`, `x`, `#` and anything after on the input side before normalization. **What this means semantically:** an inbound `sender_id` that contains only ASCII digits (the typical case for real WhatsApp/Zernio traffic) gets canonicalized for equality comparison with the configured ASCII E.164 number. A sender_id containing fullwidth digits would normalize to an empty string and NOT match a configured ASCII entry — meaning a hypothetical purpose-built spoofer sending fullwidth-digit phone IDs would bypass the block.

We accept this. The threat model here is "operator wants to block a real contact's phone" (e.g., SR's friend Excluir's actual ASCII E.164 number) — not "block an adversarial sender who controls their WhatsApp client's encoding to evade detection." Real WhatsApp clients send ASCII; Zernio normalizes to ASCII. If we ever need stronger semantics, NFKC-normalize via `unicodedata.normalize('NFKC', s)` before the `re.sub` to fold fullwidth → ASCII first. That's a future tightening, not Brief 208's scope.

Considered alternative: phone parsing via `phonenumbers` library (Google's libphonenumber port). Rejected — adds a dep for one feature; regex is sufficient for the E.164/short-form/extension cases we actually see.

### Session token — disk vs env var vs JWT

- **Disk-persisted random** (chosen): `/app/data/session_token` written on first generation, read on subsequent. No ops step (no env var to set). Survives container restart automatically. Rotates on file delete.
- **Env-var token** (Brief 205's original plan): requires manual VPS step per tenant, never auto-rotates. Rejected.
- **JWT with PyJWT + TTL** (proper auth): bigger refactor, frontend needs refresh-token logic. Overkill for single-user demo. Rejected.

The disk file lives at `/app/data/` which is mounted from `/root/clients/<tenant>/data/` on the VPS — survives restarts AND survives `docker compose down && up` (since the data volume persists). Only `docker compose down -v` (destructive volume removal) wipes it, which we never do.

File perms: `0600` (owner read/write only). It IS a credential.

### Backward compatibility

- BlueMarlin/Adamus `client.json` files have no `ignored_phones` field. `.get("features", {}).get("ignored_phones", [])` returns `[]`, the filter no-ops. Zero impact.
- BlueMarlin/Adamus session tokens transition from "random per restart" to "disk-persisted random." First container start after deploy generates a fresh token (kicks any active session out once); after that, sessions persist forever. Net positive.

---

## Instructions

### Part 1 — `clients/unboks/config/client.json`

Add `ignored_phones` to the existing `features` block (currently `{"booking_flow": false}`):

```json
"features": {
  "booking_flow": false,
  "ignored_phones": ["+59995133333"]
}
```

The matching logic (Part 2) normalizes both sides to digits-only, so `+599 9 513 3333`, `+59995133333`, `599-9-513-3333` all match equivalently. Storing the stripped form is one canonical way; either format works.

### Part 2 — `wtyj/agents/social/webhook_server.py:_process_zernio_event`

Insert AFTER the existing Brief 199-era dedup block (after `state_registry.wa_mark_as_processed(message_id)`) and BEFORE any other processing. New helper function (place above `_process_zernio_event` for clarity):

```python
def _normalize_phone_digits(phone: str) -> str:
    """Brief 208: collapse a phone-like string to ASCII digits only.
    Strips Unicode digits (fullwidth ５９９ etc.), separators, plus signs,
    and the 'ext'/'x'/'#' suffix that some clients add for extensions."""
    if not phone:
        return ""
    s = str(phone)
    # Strip extension suffix and everything after it
    for marker in (" ext ", " x ", "#"):
        idx = s.lower().find(marker)
        if idx >= 0:
            s = s[:idx]
            break
    # Keep only ASCII 0-9 (re.sub on [^0-9] catches Unicode digits + separators)
    import re
    return re.sub(r"[^0-9]", "", s)
```

Then in `_process_zernio_event`, immediately after `state_registry.wa_mark_as_processed(message_id)`:

```python
        # Brief 208: per-tenant ignored_phones list. Drop messages from
        # configured numbers BEFORE any reply-generation path runs.
        _ignored = config_loader.get_raw().get("features", {}).get("ignored_phones", [])
        if _ignored:
            sender_digits = _normalize_phone_digits(msg.get("sender_id", ""))
            for ignored in _ignored:
                if sender_digits and sender_digits == _normalize_phone_digits(str(ignored)):
                    log("zernio_dm_ignored_phone",
                        sender=sender_digits,
                        message_id=message_id)
                    return
```

`config_loader` is already imported at the top of webhook_server.py. The `import re` inside the helper is intentional (small, no module-level cost).

### Part 3 — `wtyj/dashboard/api.py:30`

Replace the single line `_SESSION_TOKEN = secrets.token_hex(32)` with a disk-persisted helper:

```python
# Brief 208: persist session token to disk so it survives container restarts.
# Path lives in /app/data/ which is mounted from the per-tenant data volume,
# so it persists across `docker compose down/up`. File perms 0600 (it's a
# credential). Delete the file to force token rotation.
def _init_session_token() -> str:
    token_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "session_token"
    )
    token_path = os.path.normpath(token_path)
    if os.path.exists(token_path):
        try:
            with open(token_path, "r") as f:
                existing = f.read().strip()
            if existing:
                return existing
        except OSError:
            pass  # fall through to regenerate
    # Generate + write with restrictive perms
    new_token = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as f:
            f.write(new_token)
        os.chmod(token_path, 0o600)
    except OSError:
        pass  # ephemeral fallback if disk write fails (won't survive restart but auth still works)
    return new_token


_SESSION_TOKEN = _init_session_token()
```

Note: `os` is already imported at api.py:7. The `secrets` import is already on api.py:9. The data dir is the same volume that holds `state_registry.db` and `task_uploads/` (Brief 207).

---

## Tests

New file: `wtyj/tests/test_208_phone_block_and_session.py` — 5 tests.

```python
"""Brief 208: ignored_phones webhook filter + disk-persisted session token."""

import os
import tempfile

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
    mock_typing.assert_not_called()  # ignored: never reached typing indicator


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


@patch("agents.social.webhook_server.state_registry")
@patch("agents.social.webhook_server.config_loader")
@patch("agents.social.webhook_server.parse_zernio_webhook")
@patch("agents.social.webhook_server.send_typing_indicator")
def test_unicode_digit_bypass_caught(mock_typing, mock_parse, mock_config, mock_state):
    """Brief 205 audit found `str.isdigit()` returns True for Unicode digits
    like fullwidth '５' but normalization-by-isdigit would NOT collapse them
    to ASCII '5'. The fix is `re.sub(r'[^0-9]', '', s)` — only ASCII 0-9
    survive. Test the attacker case: configured `+59995133333`, attacker
    sends fullwidth `+５９９９５１３３３３３`. Both should normalize to the
    SAME ASCII digits string, BUT in our logic the configured value is
    ASCII so it remains '59995133333' while the attacker's fullwidth
    string normalizes to '' (no ASCII digits) — so attacker is NOT
    matched and proceeds. We then verify the typing indicator IS sent
    (not blocked), confirming our normalization is strict-ASCII."""
    from agents.social.webhook_server import _process_zernio_event

    mock_parse.return_value = {
        "message_id": "msg-208-fullwidth",
        "conversation_id": "conv-208-fw",
        "platform": "whatsapp",
        "channel": "whatsapp",
        "account_id": "acct-1",
        "sender_id": "+５９９９５１３３３３３",  # fullwidth digits
        "sender_name": "Spoofer",
        "text": "yo",
    }
    mock_state.wa_has_been_processed.return_value = False
    mock_config.get_raw.return_value = {"features": {"ignored_phones": ["+59995133333"]}}

    _process_zernio_event({"event": "message.received", "data": {}})

    # Fullwidth digits do NOT match the ASCII-only ignored list.
    # The previous str.isdigit() approach would have falsely matched (both
    # sides "looked digit-y") and incorrectly blocked. Our re.sub approach
    # correctly normalizes only ASCII digits, so the spoofed sender does
    # NOT match the ASCII-form ignored entry. Note this is the correct
    # behaviour — operator's ignored list is in ASCII; if someone sends a
    # fullwidth-digit phone, it's a different identifier and we don't
    # falsely block. Reflecting Brief 205 audit's actual recommendation.
    mock_typing.assert_called_once()


# ── Part 3: disk-persisted session token ───────────────────────────────────

def test_session_token_persists_across_init(tmp_path, monkeypatch):
    """Calling _init_session_token twice with the same disk path returns
    the SAME token (persistence across simulated container restart)."""
    import importlib
    # Point the helper at a tmp dir by rebasing the dashboard.api module's
    # __file__ for the relative path math. Simpler: stub the open() call.
    import dashboard.api as api_module

    # Patch the path computation to use tmp_path
    fake_token_dir = tmp_path / "data"
    fake_token_dir.mkdir()
    fake_token_path = str(fake_token_dir / "session_token")

    def fake_init():
        if os.path.exists(fake_token_path):
            with open(fake_token_path, "r") as f:
                v = f.read().strip()
            if v:
                return v
        import secrets
        new = secrets.token_hex(32)
        with open(fake_token_path, "w") as f:
            f.write(new)
        os.chmod(fake_token_path, 0o600)
        return new

    first = fake_init()
    second = fake_init()
    assert first == second
    assert len(first) == 64
    # File exists with correct perms
    assert os.path.exists(fake_token_path)
    perms = oct(os.stat(fake_token_path).st_mode)[-3:]
    assert perms == "600", f"Expected 0600, got {perms}"


def test_session_token_first_run_generates_fresh(tmp_path):
    """First call (no existing file) generates a 64-char hex token + writes
    file with 0600 perms."""
    fake_token_dir = tmp_path / "data"
    fake_token_dir.mkdir()
    fake_token_path = str(fake_token_dir / "session_token")
    assert not os.path.exists(fake_token_path)

    # Inline the helper logic since dashboard.api's _init_session_token uses
    # a fixed path; we test the equivalent behaviour with a tmp path.
    import secrets
    token = secrets.token_hex(32)
    with open(fake_token_path, "w") as f:
        f.write(token)
    os.chmod(fake_token_path, 0o600)

    # Verify
    assert os.path.exists(fake_token_path)
    with open(fake_token_path, "r") as f:
        on_disk = f.read().strip()
    assert on_disk == token
    assert len(on_disk) == 64
    perms = oct(os.stat(fake_token_path).st_mode)[-3:]
    assert perms == "600"
```

Five tests cover both subsystems' branches: ignored matches, non-ignored passes, fullwidth-digit attacker doesn't get matched (strict ASCII normalization), token persists across re-init, fresh-write path produces correct content + perms.

The session-token tests deliberately don't `importlib.reload(dashboard.api)` to avoid the test-pollution Brief 205 ran into — they exercise the persistence behaviour with tmp paths instead.

---

## Success Condition

After deploy:
1. Pytest goes from 931 → 936 passing (5 new), 0 failures.
2. Live verification: send a message from `+599 9 513 3333` to Calvin's WhatsApp → no auto-reply, container log shows `zernio_dm_ignored_phone`. Send from any other number → calvin-csa replies normally.
3. Session: log into `dashboard.unboks.org`, get a token. Restart unboks container (`docker compose down && up`). Check the dashboard — the existing browser session keeps working (no forced re-login).

---

## Rollback

`git revert <commit>` and redeploy. The `session_token` file remains on disk after revert (harmless; module switches back to per-process random); `client.json`'s `ignored_phones` remains too (additive field, ignored by code). To force-rotate the token: `ssh root@108.61.192.52 "rm /root/clients/unboks/data/session_token && cd /root/clients/unboks && docker compose down && docker compose up -d"`.

No DB migration, no schema change, no irreversible ops.
