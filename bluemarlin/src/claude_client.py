# FILE: claude_client.py
# CREATED: Brief 001
# LAST MODIFIED: Brief 001
# DEPENDS ON: (none)
# IMPORTS FROM: (none)

import json
import os
import re

import anthropic


def complete(prompt: str, system: str = None) -> str:
    """Call Anthropic API and return response text. Returns "" on any failure."""
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        kwargs = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        return response.content[0].text
    except Exception:
        return ""


def extract(prompt: str) -> dict:
    """Call Anthropic API expecting JSON. Returns {} on any failure."""
    try:
        text = complete(prompt)
        if not text:
            return {}
        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text.strip())
        return json.loads(text)
    except Exception:
        return {}
