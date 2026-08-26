"""Pure presentation helpers for Ali quote documents and messages."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


CURACAO_TZ = ZoneInfo("America/Curacao")
SUPPORTED_LOCALES = {"en", "nl", "pap", "de"}

MONTHS = {
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
    "nl": (
        "januari", "februari", "maart", "april", "mei", "juni",
        "juli", "augustus", "september", "oktober", "november", "december",
    ),
    "pap": (
        "yanüari", "febrüari", "mart", "aprel", "mei", "yüni",
        "yüli", "ougùstù", "sèptèmber", "òktober", "novèmber", "desèmber",
    ),
    "de": (
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ),
}


def _locale(value: str) -> str:
    return value if value in SUPPORTED_LOCALES else "en"


def _date(value: str) -> date:
    return date.fromisoformat(str(value or ""))


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(CURACAO_TZ)


def format_date(value: str, locale: str = "en") -> str:
    """Render one ISO date naturally in a supported customer language."""
    locale = _locale(locale)
    parsed = _date(value)
    month = MONTHS[locale][parsed.month - 1]
    if locale == "de":
        return f"{parsed.day}. {month} {parsed.year}"
    if locale == "pap":
        return f"{parsed.day} di {month} {parsed.year}"
    return f"{parsed.day} {month} {parsed.year}"


def format_rental_period(start: str, end: str, locale: str = "en") -> str:
    """Render an inclusive-looking date range without altering quote math."""
    return f"{format_date(start, locale)} – {format_date(end, locale)}"


def format_curacao_datetime(value: str, locale: str = "en") -> str:
    """Render an authoritative instant in Curaçao local time."""
    locale = _locale(locale)
    parsed = _datetime(value)
    rendered_date = format_date(parsed.date().isoformat(), locale)
    if locale == "nl":
        return f"{rendered_date} om {parsed:%H:%M} (Curaçaose tijd)"
    if locale == "pap":
        return f"{rendered_date} pa {parsed:%H:%M} (ora di Kòrsou)"
    if locale == "de":
        return f"{rendered_date} um {parsed:%H:%M} (Curaçao-Zeit)"
    return f"{rendered_date} at {parsed:%H:%M} (Curaçao time)"


def usd_cents(value: dict) -> int:
    """Parse one authoritative USD money object without floating point."""
    if not isinstance(value, dict) or value.get("currency") != "USD":
        raise ValueError("Expected an authoritative USD money object")
    amount = str(value.get("amount") or "")
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", amount):
        raise ValueError("Invalid USD money amount")
    dollars, fractional = amount.split(".", 1)
    return int(dollars) * 100 + int(fractional)


def usd_money(cents: int) -> dict[str, str]:
    """Build one canonical USD money object from non-negative integer cents."""
    if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
        raise ValueError("USD cents must be a non-negative integer")
    dollars, fractional = divmod(cents, 100)
    return {"currency": "USD", "amount": f"{dollars}.{fractional:02d}"}


def format_usd_money(value: dict) -> str:
    """Format one validated USD money object for customer presentation."""
    cents = usd_cents(value)
    dollars, fractional = divmod(cents, 100)
    return f"USD {dollars:,}.{fractional:02d}"


def total_quote_amount(pricing: dict) -> dict[str, str]:
    """Return rental charges plus refundable deposit from one quote snapshot."""
    rental_cents = usd_cents(pricing.get("rentalTotal"))
    deposit_cents = usd_cents(pricing.get("refundableSecurityDeposit"))
    return usd_money(rental_cents + deposit_cents)


def _filename_component(value: str, fallback: str, limit: int) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    component = re.sub(r"[^A-Za-z0-9]+", "-", ascii_value).strip("-")
    return (component or fallback)[:limit].strip("-") or fallback


def build_quote_filename(customer_name: str, quote_reference: str, created_at: str) -> str:
    """Build a safe, deterministic, recipient-visible Ali PDF filename."""
    customer = _filename_component(customer_name, "Customer", 48)
    reference = _filename_component(quote_reference, "Quote", 48)
    try:
        issue_date = _datetime(created_at).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        issue_date = "Undated"
    unique = reference.rsplit("-", 1)[-1]
    if unique in {"Quote", "ALI"}:
        unique = f"{int(hashlib.sha256(reference.encode()).hexdigest()[:12], 16) % 1_000_000:06d}"
    return f"Ali-Car-Rental-Quote-{customer}-{issue_date}-{unique}.pdf"
