import subprocess
import sys
import json
import social_registry

# Uses the same OpenClaw session as the rest of the demo
SESSION_ID = "c5613944-cb20-4c34-941e-fd0e53f70494"

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

    r = subprocess.run(
        ["openclaw", "agent", "--session-id", SESSION_ID, "--message", prompt, "--local"],
        capture_output=True, text=True, timeout=120
    )

    text = (r.stdout or "").strip()
    if not text:
        text = "BlueMarlin Tours Curaçao — private charters available. DM us or email hello@wetakeyourjob.com"

    rec = social_registry.create_draft(platform=platform, text=text, meta={"context": context})
    return rec

if __name__ == "__main__":
    platform = sys.argv[1] if len(sys.argv) > 1 else "instagram"
    context = sys.argv[2] if len(sys.argv) > 2 else "Draft a post about a sunset cruise hold being created. Keep it general."
    rec = draft_post(platform, context)
    print(json.dumps(rec, indent=2))
