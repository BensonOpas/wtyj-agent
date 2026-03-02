import json
import subprocess
import re

SESSION_ID = "marina_extract_session"

ALLOWED_KEYS = {
    "experience",
    "date",
    "guests",
    "adults",
    "kids",
    "customer_name",
    "phone"
}

def extract_fields(text: str):
    prompt = f"""
You are a structured data extractor for BlueMarlin Tours Curaçao.

Extract booking parameters from the message below.

Return ONLY valid JSON.
Allowed keys:
- experience
- date
- guests
- adults
- kids
- customer_name
- phone

Rules:
- If a field is missing, omit it.
- Do NOT guess.
- Do NOT explain.
- Do NOT write anything except JSON.

Message:
{text}
"""

    try:
        r = subprocess.run(
            ["openclaw", "agent", "--session-id", SESSION_ID, "--message", prompt, "--local"],
            capture_output=True,
            text=True,
            timeout=120
        )

        raw = (r.stdout or "").strip()

        # Extract first JSON object found
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}

        data = json.loads(match.group(0))

        # Keep only allowed keys
        clean = {k: v for k, v in data.items() if k in ALLOWED_KEYS}

        return clean

    except Exception:
        return {}
