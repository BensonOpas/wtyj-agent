# OUTPUT 233 — Distinguish operator-typed email replies from Marina-generated ones

## What was done
Added optional `role: str = "marina"` parameter to `state_registry.email_append_assistant_message`. Extended both `email_get_conversation` and `email_list_conversations` mappers to pass `"operator"` through unchanged (customer→user, marina→assistant, operator→operator). Updated the two verbatim-send call sites in `wtyj/dashboard/api.py` to pass `role="operator"`: Brief 225's `/messages/conversations/{id}/email/reply` and Brief 210's `/escalations/{id}/reply` email branch. Brief 214's `/escalations/{id}/guidance` path stays untouched because Marina genuinely reformulates the operator's coaching there. Backward compat preserved: existing messages with `role: "marina"` continue to map to "assistant" — no data migration.

## Tests
1088 passing / 0 failures (baseline 1083 + 5 new).

## Unexpected findings
The signature change to `email_append_assistant_message` broke two pre-existing tests that asserted the old `role: "marina"` behavior on operator-typed replies — `test_210_email_escalation_reply.py::test_email_reply_sends_via_smtp_and_marks_replied` (asserted `mock_append.assert_called_once_with(email, body)` without the new kwarg) and `test_225_email_reply_endpoint.py::test_reply_sends_smtp_and_appends_thread` (asserted persisted role==marina). Both updated to assert `role="operator"` — those tests were specifically codifying the bug Brief 233 fixes, so the assertion change reflects the new contract.

## Deployment
Source committed and pushed; deploy still to fire.
