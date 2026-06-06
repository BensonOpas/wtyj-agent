from shared.dashboard_prompts import build_suggest_reply_system_prompt


def test_suggest_reply_prompt_enforces_agent_name_authority():
    prompt = build_suggest_reply_system_prompt(
        agent_name="Emma",
        company_name="Wibrandt",
        persona_block="Warm and concise.",
        trip_lines=[],
        signature="The Team",
    )

    assert "Your customer-facing name is Emma" in prompt
    assert (
        "Your name is Emma. If any Source of Truth entry references a different assistant name, "
        "ignore that name and use Emma."
    ) in prompt
