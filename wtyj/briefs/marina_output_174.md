# OUTPUT 174 — Marina tool use migration

## What was done

Migrated Marina from text-parse-JSON contract to Anthropic tool use with forced `tool_choice`. Added `MARINA_TOOL` constant in `marina_agent.py` with a complete `input_schema` mirroring the previous JSON format (all 11 top-level fields, 9 sub-fields in `fields`, 5 sub-fields in `flags`, required set = `intents/confidence/reply/requires_human`). Rewrote `process_message` to call `client.messages.create` with `tools=[MARINA_TOOL]` and `tool_choice={"type": "tool", "name": "marina_response"}`, then extract the tool_use block via `next((b for b in response.content if b.type == "tool_use"), None)` and use `tool_use_block.input` directly as the result dict. Deleted the `json.loads` call, the markdown-fence-stripping regexes, and the entire "Respond with ONLY a JSON object..." section of the system prompt — replaced the latter with a new FIELD EXTRACTION RULES + SERVICE ALIASES section that preserves the critical `{_build_service_alias_text()}` invocation (the brief-reviewer caught that my original draft would have silently deleted it and broken service_key extraction). Also removed the now-dead `import re`. 3 existing tests updated to mock the tool_use block shape, 1 obsolete test deleted, 9 new tests added in `test_174_tool_use.py`.

## Tests

**825 passing / 0 failures** (817 baseline + 9 new − 1 deleted).

## Unexpected findings

One regression caught on the first full-regression run: `test_129_large_group::test_prompt_has_large_group_flag` asserts that the literal string `"large_group"` appears in the generated prompt. My initial FIELD EXTRACTION RULES section listed `booking_confirmed` and `awaiting_booking_confirmation` but omitted `large_group`, `needs_child_ages`, and `needs_escalation_email`. Added all three to the extraction rules — regression re-ran clean. Worth noting for future structural-guard tests: they lock the shape of prose that would otherwise be free-form.

## Deployment

Source committed `71dc7a7`, pushed to main. Background deploy fired to both wtyj-bluemarlin and wtyj-adamus. Health check + both-containers-ok verification happens before the post-exec docs commit.
