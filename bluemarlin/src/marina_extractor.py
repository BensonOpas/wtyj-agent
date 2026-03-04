# FILE: marina_extractor.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 020
# DEPENDS ON: claude_client.py (Brief 001)
# IMPORTS FROM: claude_client.py (Brief 001)
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_client

ALLOWED_KEYS = {
    "experience",
    "date",
    "guests",
    "adults",
    "kids",
    "customer_name",
    "phone",
    "special_requests"
}

def extract_fields(text: str):
    prompt = f"""
You are a structured data extractor for BlueMarlin Tours Curaçao.

Extract booking parameters from the message below.

Return ONLY valid JSON.
Allowed keys:
- experience (which boat tour they want)
- date (when they want to go)
- guests (total number of people — must be an exact integer.
  "Just me" = 1. "Me and my wife" = 2. "A family of 4" = 4.
  "Family of 4 plus a baby/infant/toddler" = 4 — do NOT count
  infants under 2 in the guest total; add them to special_requests
  instead. "Around 10" or "about 10" — do NOT extract guests,
  omit the field so Marina can ask for an exact number.)
- adults (if specified separately as an integer)
- kids (if specified separately as an integer — does not include infants)
- customer_name (their name)
- phone (their phone number)
- special_requests (forward-looking preferences for the
  upcoming trip only: dietary needs, allergies, accessibility
  requirements, celebrations, drink preferences — capture
  verbatim. Exclude complaints about past experiences.)

Rules:
- If a field is missing, omit it.
- Do NOT guess.
- Do NOT explain.
- Do NOT write anything except JSON.
- For guests: extract ONLY a definite integer. If the customer uses
  approximate language ("around", "about", "roughly", "maybe",
  "approximately") do NOT extract guests — omit it entirely so
  Marina asks for an exact count. If an infant/baby is mentioned
  alongside a guest count, do NOT include the infant in the count —
  add "travelling with an infant" to special_requests instead.
- For special_requests: capture ONLY forward-looking personal
  preferences for the upcoming trip — dietary restrictions,
  allergies, accessibility needs, celebrations, drink
  preferences, or specific requests for the day.
  Do NOT capture complaints about past experiences,
  negative feedback, or anything referring to a previous trip.
  Those are complaints, not special requests.
  If no forward-looking preferences are mentioned, omit
  the field entirely.

Message:
{text}
"""

    result = claude_client.extract(prompt)
    if not isinstance(result, dict):
        return {}
    clean = {k: v for k, v in result.items() if k in ALLOWED_KEYS}
    return clean
