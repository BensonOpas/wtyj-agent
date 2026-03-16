# bluemarlin/agents/social/content_agent.py
# Created: Brief 092
# Last modified: Brief 092
# Purpose: Social media content generation agent. Generates draft posts from client.json + calendar data.

import json
import os
import re
from datetime import datetime, timezone, timedelta

import anthropic
from shared import config_loader, state_registry, bm_logger

_CURACAO_TZ = timezone(timedelta(hours=-4))

_INTERNAL_KEYS = {"spreadsheet_id", "demo_support_email", "agent_signature",
                  "calendar_id"}

_SKIP_TOP_LEVEL = {"trip_aliases"}

_DRAFT_DEFAULTS = {
    "content_class": "A",
    "instagram_caption": "",
    "facebook_caption": "",
    "hashtags": [],
    "visual_suggestion": "",
    "reasoning": "",
}

_VALID_CLASSES = {"A", "B", "C", "D"}


def _strip_verify(obj):
    """Recursively strip [VERIFY...] placeholder values from nested structures."""
    if isinstance(obj, dict):
        return {k: _strip_verify(v) for k, v in obj.items()
                if not (isinstance(v, str) and v.startswith("[VERIFY"))}
    if isinstance(obj, list):
        return [_strip_verify(i) for i in obj
                if not (isinstance(i, str) and i.startswith("[VERIFY"))]
    return obj


def _build_client_context() -> str:
    """Auto-generate labeled sections from all customer-facing data in client.json.
    Filters internal keys and [VERIFY] placeholders. New sections are automatically included."""
    raw = config_loader.get_raw()
    sections = []
    for key, value in raw.items():
        if key in _SKIP_TOP_LEVEL:
            continue
        if isinstance(value, dict):
            clean = {}
            for k, v in value.items():
                if k in _INTERNAL_KEYS:
                    continue
                # Strip calendar_id from trip departures
                if isinstance(v, dict) and "departures" in v:
                    v = dict(v)
                    v["departures"] = [
                        {dk: dv for dk, dv in dep.items() if dk not in _INTERNAL_KEYS}
                        for dep in v.get("departures", [])
                    ]
                clean[k] = v
            clean = _strip_verify(clean)
            if clean:
                sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{json.dumps(clean, indent=2, ensure_ascii=False)}")
        elif isinstance(value, list):
            clean = _strip_verify(value)
            sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{json.dumps(clean, indent=2, ensure_ascii=False)}")
        elif isinstance(value, str) and key not in _INTERNAL_KEYS:
            if not value.startswith("[VERIFY"):
                sections.append(f"=== {key.upper().replace('_', ' ')} ===\n{value}")
    return "\n\n".join(sections)


def _build_system_prompt(count: int) -> str:
    """Build the system prompt: role, brand rules, classification, voice, format."""
    business = config_loader.get_business()
    business_name = business.get("name", "the business")
    raw = config_loader.get_raw()
    sc = raw.get("social_content", {})
    brand_voice = sc.get("brand_voice", "premium, confident, clear")
    boundaries = sc.get("content_boundaries", ["competitors", "politics", "religion"])
    cta = sc.get("cta_default", "Contact us to book")
    emoji_style = sc.get("emoji_style", "minimal, intentional")
    hashtag_style = sc.get("hashtag_style", "selective, curated, few not maximum")

    return f"""You are the social media content strategist for {business_name}.
You generate draft social media posts. You do not publish — a human reviews and approves every post.

BRAND VOICE: {brand_voice}
The brand shows the world what it does and what it has. Premium, polished, aspirational, trustworthy, experience-driven, visually strong.

TONE: Professional without cold. Warm without cheap or sloppy.

PRIORITY STACK (if tradeoffs appear):
1. protect brand quality
2. protect factual correctness
3. protect premium perception
4. support commercial goals
5. maintain content consistency
6. optimize engagement

CONTENT CLASSIFICATION:
Class A — Evergreen brand: experience highlights, testimonials, tips, storytelling, destination facts, marine life, behind the scenes
Class B — Commercial: promotions, low-booking support, reopened spots, demand stimulation
Class C — Operational: weather, changes, cancellations, sold-out status, availability redirects
Class D — Reactive: UGC, local moments, tagged posts, timely external relevance (holidays, events)

Maintain a healthy mix across classes. Do not generate multiple posts of the same class in a row.

VOICE RULES:
- Sound like the company, not a separate persona or named character
- English primary
- Emojis: {emoji_style}
- NEVER use: cheap, spammy, urgency tactics, exaggerated language, "Don't miss out!", "Book NOW!", "Limited spots!!", excessive exclamation marks
- Desired style: premium, aspirational, polished, clear, confident

PLATFORM RULES:
Instagram (primary): shorter captions, punchy, visual-first. Max 150 words.
Facebook (secondary): slightly longer, more informational, same core message. Max 200 words.
Both get the same concept but adapted per platform.

CONTENT BOUNDARIES:
NEVER post about: {', '.join(boundaries)}

HASHTAG RULES:
{hashtag_style}

DEFAULT CALL TO ACTION:
{cta}

DEMAND-STATE RULES:
- Low bookings: propose content to attract interest. Never sound desperate.
- Sold out: don't stop posting. Redirect to next available option. Turn full capacity into social proof.
- Cancellation reopens spots: propose timely content reflecting the opportunity.

RESPONSE FORMAT:
Return ONLY a JSON object. No explanation. No markdown. No code fences.
The "drafts" array must contain exactly {count} items.

{{
  "drafts": [
    {{
      "content_class": "<A|B|C|D>",
      "instagram_caption": "<caption for Instagram — max 150 words>",
      "facebook_caption": "<caption for Facebook — max 200 words, slightly more informational>",
      "hashtags": ["#Tag1", "#Tag2"],
      "visual_suggestion": "<description of ideal accompanying image>",
      "reasoning": "<why this post, why now, what it achieves>"
    }}
  ]
}}"""


def _build_user_prompt(count: int, days_ahead: int = 7) -> str:
    """Build the user prompt: business data, availability, recent drafts, rejections."""
    today = datetime.now(_CURACAO_TZ)
    today_str = today.strftime("%Y-%m-%d")
    day_of_week = today.strftime("%A")
    client_context = _build_client_context()

    # Availability
    availability = state_registry.get_availability_summary(days_ahead)
    if availability:
        trips = config_loader.get_trips()
        avail_lines = []
        for slot in availability:
            display = trips.get(slot["trip_key"], {}).get("display_name", slot["trip_key"])
            avail_lines.append(
                f"  {display} | {slot['date']} {slot['departure_time']} | "
                f"{slot['spots_remaining']}/{slot['capacity']} spots"
            )
        avail_section = "\n".join(avail_lines)
    else:
        avail_section = "No booking data available. Focus on Class A (evergreen) and Class D (reactive) content."

    # Recent drafts (last 14 days)
    all_drafts = state_registry.get_content_drafts(limit=20)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    recent = [d for d in all_drafts if d.get("created_at", "") > cutoff]
    if recent:
        recent_lines = []
        for d in recent:
            cap = (d.get("instagram_caption") or "")[:80]
            recent_lines.append(f"  [{d['content_class']}] {cap}...")
        recent_section = "\n".join(recent_lines)
    else:
        recent_section = "No recent drafts."

    # Rejection history
    rejected = state_registry.get_content_drafts(status="rejected", limit=10)
    if rejected:
        rej_lines = []
        for d in rejected:
            if d.get("rejection_reason"):
                cap = (d.get("instagram_caption") or "")[:60]
                rej_lines.append(f'  REJECTED: "{cap}..." — Reason: {d["rejection_reason"]}')
        rejection_section = "\n".join(rej_lines) if rej_lines else "No rejections yet."
    else:
        rejection_section = "No rejections yet."

    return f"""TODAY (Curaçao time): {today_str}
DAY OF WEEK: {day_of_week}

=== CLIENT DATA ===
{client_context}

=== AVAILABILITY (next {days_ahead} days) ===
{avail_section}

=== RECENT DRAFTS (last 14 days) ===
{recent_section}

=== REJECTION HISTORY ===
{rejection_section}

Generate {count} draft posts for the coming week."""


def generate_drafts(count: int = 3, days_ahead: int = 7) -> list:
    """Generate content drafts via a single Claude call. Stores in SQLite. Returns list of draft dicts."""
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = _build_system_prompt(count)
        user_prompt = _build_user_prompt(count, days_ahead)

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()

        # Log API token usage
        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("api_usage",
                          input_tokens=_usage.input_tokens,
                          output_tokens=_usage.output_tokens,
                          model="claude-sonnet-4-6",
                          channel="content")

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.strip())

        result = json.loads(raw)

        if not isinstance(result, dict) or "drafts" not in result:
            bm_logger.log("content_response_invalid", reason="missing_drafts_key",
                          raw_preview=raw[:300])
            return []

        drafts_list = result["drafts"]
        if not isinstance(drafts_list, list):
            bm_logger.log("content_response_invalid", reason="drafts_not_list",
                          raw_preview=raw[:300])
            return []

        stored = []
        for draft in drafts_list:
            if not isinstance(draft, dict):
                continue

            # Apply defaults for missing fields
            for field, default in _DRAFT_DEFAULTS.items():
                if field not in draft:
                    draft[field] = default

            # Validate content_class
            if draft["content_class"] not in _VALID_CLASSES:
                draft["content_class"] = "A"

            # Skip empty drafts
            if not draft.get("instagram_caption") and not draft.get("facebook_caption"):
                continue

            draft_id = state_registry.save_content_draft(
                content_class=draft["content_class"],
                instagram_caption=draft.get("instagram_caption", ""),
                facebook_caption=draft.get("facebook_caption", ""),
                hashtags=draft.get("hashtags", []),
                visual_suggestion=draft.get("visual_suggestion", ""),
                reasoning=draft.get("reasoning", ""),
            )

            # Fetch the stored draft to return with id
            all_drafts = state_registry.get_content_drafts(limit=1)
            if all_drafts:
                stored.append(all_drafts[0])

        bm_logger.log("content_drafts_generated", count=len(stored))
        return stored

    except json.JSONDecodeError:
        bm_logger.log("content_response_invalid", reason="json_parse_error",
                      raw_preview=raw[:300] if 'raw' in dir() else "")
        return []
    except Exception as exc:
        bm_logger.log("content_api_error", error=str(exc)[:200])
        return []
