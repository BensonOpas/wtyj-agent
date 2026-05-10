"""Brief 227: generate the structured 'decision-first' escalation summary
that SR's EscalationReasonPanel renders. One Claude call, one return —
no retries, no fallbacks. Caller persists whatever we hand back (or null
on failure).

Frontend contract (from EscalationReasonPanel + escalation-summary.ts):
{
    "reason": str,                  # one-paragraph operator briefing
    "customerWants": str,           # what the customer is asking for
    "operatorNeedsToDecide": str,   # the choice the operator faces
    "recommendedOptions": [str],    # 3-5 concrete actionable chips
    "extractedDetails": {
        "intent": str,              # "scheduling" | "complaint" | ...
        "proposedTimes": [str],     # every time slot the customer mentioned
        "topic": str,               # short topic label
    }
}
"""
import os
from typing import Optional

import anthropic
from shared import bm_logger


SUMMARY_TOOL = {
    "name": "escalation_summary",
    "description": (
        "Emit a structured operator briefing for this escalation. The "
        "operator will read this BEFORE the conversation trail, so it must "
        "tell them WHY they're being pulled in, WHAT the customer wants, "
        "and WHICH choice they need to make. Extract every proposed time/"
        "slot/option from the customer's messages — do not summarize "
        "vaguely as 'suggested a time' when exact times exist."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "One-paragraph operator briefing. Names the customer, "
                    "states the topic, and ends with what the operator needs "
                    "to do. Example: 'Calvin wants to schedule an activation "
                    "call. He suggested Thursday at 09:00 or 12:00. Marina "
                    "needs a human to choose one of the proposed slots or "
                    "suggest another time.'"
                ),
            },
            "customerWants": {
                "type": "string",
                "description": "One sentence: what the customer is asking for.",
            },
            "operatorNeedsToDecide": {
                "type": "string",
                "description": (
                    "One sentence: the choice the operator must make. List the "
                    "concrete options inline. Example: 'Choose Thursday at "
                    "09:00, choose Thursday at 12:00, suggest another time, "
                    "or ask for more availability.'"
                ),
            },
            "recommendedOptions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "3-5 concrete actionable options. Each option must be a "
                    "specific action, not a category. EVERY proposed time "
                    "from the customer becomes its own 'Confirm <time>' "
                    "option. Always include 'Suggest another time' and "
                    "'Switch to human takeover' as fallback options when "
                    "the intent is scheduling. For non-scheduling intents, "
                    "tailor accordingly."
                ),
            },
            "extractedDetails": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": (
                            "Short label: scheduling | complaint | refund | "
                            "pricing | activation | technical | other"
                        ),
                    },
                    "proposedTimes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "EVERY time slot the customer mentioned, in "
                            "their original wording. Example: ['Thursday at "
                            "09:00', 'Thursday at 12:00']. Empty list if "
                            "no times mentioned."
                        ),
                    },
                    "previousProposedTimes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Time slots the customer proposed earlier in "
                            "the conversation but explicitly retracted or "
                            "changed. Use this when the customer says they "
                            "'changed their mind' or proposes a different "
                            "time after an earlier proposal. Empty list "
                            "when there is no retraction. Do not include "
                            "times that are still on the table — those go "
                            "in proposedTimes."
                        ),
                    },
                    "topic": {
                        "type": "string",
                        "description": "2-5 word topic label.",
                    },
                },
                "required": ["intent", "proposedTimes", "topic"],
            },
        },
        "required": [
            "reason", "customerWants", "operatorNeedsToDecide",
            "recommendedOptions", "extractedDetails",
        ],
    },
}


def _format_history(messages: list) -> str:
    """Render the conversation as plain text for the Claude prompt."""
    lines = []
    for m in messages or []:
        role = m.get("role", "")
        if role in ("user", "customer", "incoming"):
            speaker = "CUSTOMER"
        else:
            speaker = "AGENT"
        text = m.get("text") or m.get("content") or m.get("body") or ""
        if not text:
            continue
        lines.append(f"{speaker}: {text.strip()}")
    return "\n".join(lines) if lines else "(no message history available)"


def generate_summary(channel: str, customer_id: str, customer_name: str,
                     mode: Optional[str], history: list) -> Optional[dict]:
    """Brief 227: build the structured escalation briefing. Returns the
    dict on success, None on any failure (caller persists null and the
    frontend falls back to its generic-text parser)."""
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        client = anthropic.Anthropic(api_key=api_key)

        history_text = _format_history(history)
        mode_text = mode if mode in ("soft", "hard") else "(unset)"

        system_prompt = (
            "You are an operator-facing assistant. Your job is to read a "
            "conversation between a CUSTOMER and an AI AGENT, then summarize "
            "the situation for a human operator who has to step in. The "
            "operator will read your summary BEFORE reading the conversation, "
            "so it must give them everything they need to make a decision in "
            "one glance.\n\n"
            "Hard rules:\n"
            "- Extract EVERY proposed time/slot/option from the customer's "
            "messages. Never summarize 'suggested a time' if exact times "
            "exist.\n"
            "- Use the customer's exact wording for times when possible.\n"
            "- Recommended options must be CONCRETE actions, not categories. "
            "'Confirm Thursday at 09:00' yes; 'Pick a time' no.\n"
            "- For scheduling escalations, always include "
            "'Suggest another time' and 'Switch to human takeover' as "
            "fallbacks.\n"
            "- Never invent customer wording or times that aren't in the "
            "transcript.\n"
            "- When the customer explicitly retracts a previously proposed "
            "time and proposes a different one (e.g., \"i changed my mind, "
            "change it to X\"), put the new time in proposedTimes and the "
            "retracted time(s) in previousProposedTimes. Do not put the "
            "same time in both lists."
        )

        user_prompt = (
            f"CHANNEL: {channel}\n"
            f"CUSTOMER ID: {customer_id}\n"
            f"CUSTOMER NAME: {customer_name or '(unknown)'}\n"
            f"ESCALATION MODE: {mode_text}\n\n"
            f"CONVERSATION:\n{history_text}\n\n"
            "Emit your structured operator briefing now."
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            tools=[SUMMARY_TOOL],
            tool_choice={"type": "tool", "name": "escalation_summary"},
            messages=[{"role": "user", "content": user_prompt}],
        )

        _usage = getattr(response, "usage", None)
        if _usage:
            bm_logger.log("escalation_summary_usage",
                          input_tokens=_usage.input_tokens,
                          output_tokens=_usage.output_tokens,
                          channel=channel,
                          customer_id=customer_id[:50])

        block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if block is None:
            bm_logger.log("escalation_summary_no_tool_use",
                          channel=channel, customer_id=customer_id[:50])
            return None
        return dict(block.input)
    except Exception as exc:
        bm_logger.log("escalation_summary_failed",
                      error=str(exc)[:200],
                      channel=channel,
                      customer_id=customer_id[:50])
        return None
