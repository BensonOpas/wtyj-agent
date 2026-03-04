# FILE: marina_extractor.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 011
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
- guests (total number of people)
- adults (if specified separately)
- kids (if specified separately)
- customer_name (their name)
- phone (their phone number)
- special_requests (dietary needs, allergies, accessibility
  requirements, celebrations, drink preferences, or any
  other personal notes — capture verbatim as a single string)

Rules:
- If a field is missing, omit it.
- Do NOT guess.
- Do NOT explain.
- Do NOT write anything except JSON.
- For special_requests: capture any personal context,
  dietary restrictions, accessibility needs, allergies,
  celebrations, or preferences verbatim. If none are
  mentioned, omit the field entirely.

Message:
{text}
"""

    result = claude_client.extract(prompt)
    if not isinstance(result, dict):
        return {}
    clean = {k: v for k, v in result.items() if k in ALLOWED_KEYS}
    return clean
