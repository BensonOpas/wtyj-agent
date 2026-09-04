"""Validate customer-supplied international contact numbers, never sender IDs."""
import re


def normalize_contact_phone(value: object) -> str | None:
    """Normalize display punctuation; this verifies format, not reachability."""
    if not isinstance(value, str) or len(value) > 80:
        return None
    value = value.strip()
    if not re.fullmatch(r"[+0-9() .-]+", value):
        return None
    compact = re.sub(r"[() .-]", "", value)
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", compact):
        return None
    return compact
