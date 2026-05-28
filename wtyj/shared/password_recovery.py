"""Tenant dashboard password recovery.

Nr2 currently uses one tenant dashboard password. This module adds a reset
overlay stored in the tenant data DB: once a reset succeeds, login validates
against the stored PBKDF2 hash instead of the original env/client password.
Raw reset tokens and raw passwords are never stored.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from shared import config_loader, state_registry, bm_logger


GENERIC_RESPONSE = "If this email exists, we sent password reset instructions."
TOKEN_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_TTL_MINUTES", "60"))
MIN_PASSWORD_LENGTH = 12


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def _pbkdf2(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        260_000,
    )
    return "pbkdf2_sha256$260000${}${}".format(
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _verify_pbkdf2(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(rounds),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _connect() -> sqlite3.Connection:
    conn = state_registry._get_conn()
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_password_hash (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            password_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT NOT NULL UNIQUE,
            email_hash TEXT NOT NULL,
            requested_ip_hash TEXT,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_password_reset_email_created ON password_reset_tokens (email_hash, created_at)"
    )
    conn.commit()
    return conn


def password_override_is_configured() -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM dashboard_password_hash WHERE id = 1").fetchone()
    return row is not None


def verify_dashboard_password(candidate: str, fallback_password: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT password_hash FROM dashboard_password_hash WHERE id = 1").fetchone()
    if row:
        return _verify_pbkdf2(candidate, row["password_hash"])
    return hmac.compare_digest(candidate, fallback_password)


def validate_new_password(password: str, confirm: str) -> tuple[bool, str]:
    if password != confirm:
        return False, "Passwords do not match."
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return False, "Password must include letters and numbers."
    return True, ""


def _tenant_contact_emails() -> set[str]:
    raw = config_loader.get_raw()
    business = config_loader.get_business()
    emails: set[str] = set()
    for source in (raw, business):
        if not isinstance(source, dict):
            continue
        for key in ("email", "support_email", "contact_email", "owner_email"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                emails.add(value.strip().lower())
    return emails


def _tenant_slug() -> str:
    business = config_loader.get_business()
    raw = config_loader.get_raw()
    for value in (business.get("slug"), raw.get("slug"), os.environ.get("TENANT_SLUG"), os.environ.get("TENANT_ID")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _reset_base_url() -> str:
    return os.environ.get("DASHBOARD_PUBLIC_URL", "https://dashboard.unboks.org").rstrip("/")


def _build_reset_link(raw_token: str) -> str:
    query = urlencode({"workspace": _tenant_slug(), "token": raw_token})
    return f"{_reset_base_url()}/reset-password?{query}"


def request_reset(email: str, ip_address: str = "") -> dict[str, Any]:
    """Create/send a reset link when the email belongs to this tenant.

    The caller should always return GENERIC_RESPONSE regardless of this result.
    """
    clean_email = (email or "").strip().lower()
    if "@" not in clean_email:
        return {"sent": False, "reason": "invalid_email_shape"}
    email_hash = _hash_email(clean_email)
    ip_hash = _hash_email(ip_address or "")
    now = _now()
    cutoff = _iso(now - timedelta(hours=1))
    with _connect() as conn:
        recent_email = conn.execute(
            "SELECT COUNT(*) AS c FROM password_reset_tokens WHERE email_hash = ? AND created_at >= ?",
            (email_hash, cutoff),
        ).fetchone()["c"]
        recent_ip = conn.execute(
            "SELECT COUNT(*) AS c FROM password_reset_tokens WHERE requested_ip_hash = ? AND created_at >= ?",
            (ip_hash, cutoff),
        ).fetchone()["c"]
        if recent_email >= 3 or recent_ip >= 10:
            bm_logger.log("password_reset_rate_limited", tenant=_tenant_slug())
            return {"sent": False, "reason": "rate_limited"}

    if clean_email not in _tenant_contact_emails():
        bm_logger.log("password_reset_requested_unknown_or_mismatch", tenant=_tenant_slug())
        return {"sent": False, "reason": "email_not_matched"}

    raw_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=TOKEN_TTL_MINUTES)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO password_reset_tokens (
                token_hash, email_hash, requested_ip_hash, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (_hash_token(raw_token), email_hash, ip_hash, _iso(expires_at), _iso(now)),
        )
        conn.commit()

    link = _build_reset_link(raw_token)
    body = f"""Someone requested a password reset for your Unboks dashboard.

Use this secure link to choose a new password:
{link}

This link expires in {TOKEN_TTL_MINUTES} minutes and can only be used once.

If you did not request this, you can ignore this email.
"""
    try:
        from agents.marina.email_adapter import smtp_send

        smtp_send(clean_email, "Reset your Unboks password", body)
        bm_logger.log("password_reset_email_sent", tenant=_tenant_slug())
        return {"sent": True, "reason": "sent"}
    except Exception as exc:
        bm_logger.log("password_reset_email_failed", tenant=_tenant_slug(), error=str(exc)[:160])
        return {"sent": False, "reason": "email_failed"}


def reset_password(raw_token: str, new_password: str, confirm_password: str) -> tuple[bool, str]:
    ok, error = validate_new_password(new_password, confirm_password)
    if not ok:
        return False, error
    token_hash = _hash_token(raw_token or "")
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if not row:
            bm_logger.log("password_reset_failed", tenant=_tenant_slug(), reason="invalid")
            return False, "Reset link is invalid or expired."
        if row["used_at"]:
            bm_logger.log("password_reset_failed", tenant=_tenant_slug(), reason="used")
            return False, "Reset link is invalid or expired."
        try:
            expires_at = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            expires_at = now - timedelta(seconds=1)
        if expires_at < now:
            bm_logger.log("password_reset_failed", tenant=_tenant_slug(), reason="expired")
            return False, "Reset link is invalid or expired."
        conn.execute(
            """
            INSERT INTO dashboard_password_hash (id, password_hash, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                password_hash = excluded.password_hash,
                updated_at = excluded.updated_at
            """,
            (_pbkdf2(new_password), _iso(now)),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
            (_iso(now), row["id"]),
        )
        conn.commit()
    bm_logger.log("password_reset_completed", tenant=_tenant_slug())
    return True, "Password reset."

