# FILE: social_drafter.py
# CREATED: Before Brief 001 (original codebase)
# LAST MODIFIED: Brief 003
# DEPENDS ON: claude_client.py (Brief 001)
# DEPENDS ON: social_registry.py (original)
# IMPORTS FROM: claude_client.py (Brief 001)
# IMPORTS FROM: social_registry.py (original)
import sys
import json
import social_registry
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_client

def draft_post(platform: str, context: str) -> dict:
    """
    LLM is allowed to DRAFT text only.
    Deterministic code stores it, assigns content_id, and prevents duplicates.
    """
    prompt = (
        "You are a social content drafter for BlueMarlin Tours Curaçao.\n"
        "Write ONE short social post draft.\n"
        "Rules:\n"
        "- No emojis spam (max 2 emojis)\n"
        "- Clear CTA to DM or email hello@wetakeyourjob.com\n"
        "- Mention Curaçao\n"
        "- Keep it punchy and human\n"
        "- Do NOT claim availability is confirmed\n"
        "- Output ONLY the post text, nothing else\n\n"
        f"Platform: {platform}\n"
        f"Context:\n{context}\n"
    )

    text = claude_client.complete(prompt)
    if not text:
        text = "BlueMarlin Tours Curaçao — private charters available. DM us or email hello@wetakeyourjob.com"

    rec = social_registry.create_draft(platform=platform, text=text, meta={"context": context})
    return rec

if __name__ == "__main__":
    platform = sys.argv[1] if len(sys.argv) > 1 else "instagram"
    context = sys.argv[2] if len(sys.argv) > 2 else "Draft a post about a sunset cruise hold being created. Keep it general."
    rec = draft_post(platform, context)
    print(json.dumps(rec, indent=2))
