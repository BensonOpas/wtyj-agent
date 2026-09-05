"""Stop repeated automatic greetings without muting a person or tenant."""
import re
from datetime import datetime, timedelta, timezone


def repeated_automatic_reply(text, history, *, now=None):
    normalized = " ".join(str(text or "").casefold().split())
    if len(normalized) < 60:
        return False
    markers = (
        r"(?:this is an?|an?) automated (?:message|response|reply)",
        r"thank you for (?:contacting|reaching out to)",
        r"bedankt (?:voor (?:uw|je) bericht|dat u contact)",
        r"gracias por (?:contactar|comunicarse)",
        r"obrigad[oa] (?:pelo contacto|por entrar em contato)",
        r"danki pa (?:bo mensahe|tuma kontakto)",
        r"vielen dank für (?:ihre nachricht|ihre kontaktaufnahme)",
    )
    if not any(re.search(marker, normalized) for marker in markers):
        return False
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=10)
    matches = replies = 0
    for item in history:
        try:
            timestamp = datetime.fromisoformat(item.get("created_at", ""))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if timestamp < cutoff:
            continue
        if item.get("role") == "operator":
            # A person joining resets the evidence of an automated exchange.
            matches = replies = 0
        elif item.get("role") == "assistant":
            replies += 1
        elif item.get("role") == "user" and " ".join(str(item.get("text") or "").casefold().split()) == normalized:
            matches += 1
    return matches >= 2 and replies >= 2
