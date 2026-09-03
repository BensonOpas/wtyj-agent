"""Project mounted configuration into public business facts, never credentials.

The mounted document is also a credential/provider store. New top-level fields
are therefore private until explicitly reviewed here. Within approved business
sections, credential and operational keys are excluded recursively, including
objects in arrays and name/value credential records. This boundary runs before
serialization to either an LLM or the dashboard; display-only redaction is not
a substitute. Do not put otherwise unlabelled secrets in public prose fields.
"""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit


PUBLIC_BUSINESS_FIELDS = frozenset({
    "name", "business_name", "email", "support_email", "phone", "whatsapp",
    "website", "agent_name", "agent_tone", "business", "agent_persona",
    "payment", "terminology", "booking_rules", "services", "service_aliases",
    "faq", "common_sense_knowledge", "cancellation_policy", "private_charters",
    "social_content", "seasonal_calendar", "resources", "contact_methods",
    "social_profiles", "source_provenance",
})

_PRIVATE_FIELDS = frozenset({
    "auth", "oauth", "oauth2", "authentication", "authorization", "credentials",
    "smtp", "imap", "pop3", "database", "databaseurl", "dsn", "connection",
    "connections", "connectionstring", "connectionurl", "connecturl",
    "connectionstatus", "connectionid", "connectionids", "provider", "providers",
    "providerid", "provideraccountid", "accountid", "accountids", "zernioaccounts",
    "internal", "internalconfig", "runtime", "deployment", "webhook", "webhooks",
    "calendarid", "spreadsheetid", "agentinternalid", "dashboardurl",
    "demosupportemail", "agentsignature", "logopath", "fontpath", "filepath",
    "privatepath", "cookie", "cookies", "sessionid", "sessionkey", "otp", "pin",
    "pwd", "passwd", "passphrase", "privatekey", "signingkey", "encryptionkey",
})
_SECRET_PARTS = (
    "password", "passwd", "passphrase", "secret", "token", "credential",
    "apikey", "accesskey", "privatekey", "signingkey", "encryptionkey",
    "authorization", "connectionstring",
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_OMIT = object()


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", key).casefold())


def _credential_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return normalized in {
        "auth", "oauth", "oauth2", "authentication", "cookie", "cookies",
        "pwd", "otp", "pin", "sessionid", "sessionkey", "dsn", "databaseurl",
    } or any(part in normalized for part in _SECRET_PARTS)


def _private_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return normalized in _PRIVATE_FIELDS or _credential_key(key)


def _credential_record(value: dict) -> bool:
    normalized = {_normalized_key(key): item for key, item in value.items() if isinstance(key, str)}
    return "value" in normalized and any(
        isinstance(normalized.get(label), str) and _private_key(normalized[label])
        for label in ("name", "key", "field", "setting")
    )


def _secret_values(value, *, secret: bool = False) -> set[str]:
    """Also redact known credential strings copied into innocuous prose keys."""
    if isinstance(value, str):
        return {value} if secret and value else set()
    found: set[str] = set()
    if isinstance(value, dict):
        record = _credential_record(value)
        for key, item in value.items():
            if isinstance(key, str):
                found.update(_secret_values(
                    item, secret=secret or _credential_key(key)
                    or (record and _normalized_key(key) == "value"),
                ))
    elif isinstance(value, list):
        for item in value:
            found.update(_secret_values(item, secret=secret))
    return found


def _credential_url(text: str) -> bool:
    for match in _URL_RE.finditer(text):
        try:
            url = urlsplit(match.group())
            if url.username is not None or url.password is not None:
                return True
            pairs = parse_qsl(url.query, keep_blank_values=True) + parse_qsl(url.fragment, keep_blank_values=True)
            if any(_credential_key(key) or _normalized_key(key) in {"key", "sig", "signature"} for key, _ in pairs):
                return True
        except ValueError:
            # A malformed URL cannot be established as public configuration.
            return True
    return False


def redact_config_credentials(text: str, raw: dict) -> str:
    """Final model-boundary guard for credentials repeated in other prompt blocks."""
    if not isinstance(raw, dict):
        return text
    for secret in sorted(_secret_values(raw), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return _URL_RE.sub(
        lambda match: "[REDACTED URL]" if _credential_url(match.group()) else match.group(),
        text,
    )


def public_business_config(raw: dict) -> dict:
    """Return a detached public projection; never modify the mounted source."""
    if not isinstance(raw, dict):
        return {}
    secrets = sorted(_secret_values(raw), key=len, reverse=True)

    def clean(value):
        if isinstance(value, dict):
            if _credential_record(value):
                return _OMIT
            result = {}
            for key, item in value.items():
                if not isinstance(key, str) or _private_key(key) or any(secret in key for secret in secrets):
                    continue
                cleaned = clean(item)
                if cleaned is not _OMIT:
                    result[key] = cleaned
            return result
        if isinstance(value, list):
            result = []
            for item in value:
                cleaned = clean(item)
                if cleaned is not _OMIT:
                    result.append(cleaned)
            return result
        if isinstance(value, str):
            if value.lstrip().startswith("[VERIFY") or _credential_url(value):
                return _OMIT
            for secret in secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if value is None or type(value) in (bool, int, float):
            return value
        return _OMIT

    return {
        key: cleaned
        for key, value in raw.items()
        if key in PUBLIC_BUSINESS_FIELDS
        and (cleaned := clean(value)) is not _OMIT
    }


def render_public_business_context(raw: dict, *, exclude=()) -> str:
    """Keep the established section format, using only the safe projection."""
    sections = []
    for key, value in public_business_config(raw).items():
        if key in exclude:
            continue
        if isinstance(value, (dict, list)):
            if not value:
                continue
            rendered = json.dumps(value, indent=2, ensure_ascii=False)
        elif isinstance(value, str):
            rendered = value
        else:
            continue
        sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{rendered}")
    return "\n\n".join(sections)


def get_public_business_identity() -> dict:
    """Resolve minimal-tenant identity fallbacks through the same projection."""
    from shared import config_loader

    raw = dict(config_loader.get_raw())
    raw["business"] = config_loader.get_business()
    return public_business_config(raw).get("business", {})
