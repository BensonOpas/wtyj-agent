# EXPLANATION 221 — Haiku for /ai-editor translate path

## In one sentence
When an operator clicks "Translate" on a customer's message to read it in English, the system now sends that request to a much cheaper Claude model — about 75% less per call — while operator drafts going back to customers still go through the higher-quality model.

## What's changing and why

The dashboard already had one shared AI helper endpoint that does three different jobs for the operator: translate text, restyle a draft, and fix grammar in a draft. Until today, all three jobs went through the same expensive model (Claude Sonnet), because all three were originally about polishing replies that an operator was about to send to a customer — quality and brand voice mattered.

Today the frontend turned on a new feature: every inbound customer message bubble now has a "Translate" button so the operator can quickly read foreign-language messages in English. That button reuses the same shared helper endpoint with a "translate" action. The moment that feature went live, translation became the single most-called action on this endpoint by a wide margin — every operator opening any non-English conversation can fire it several times. Paying Sonnet rates for "operator wants to understand what the customer said" was the wrong tradeoff: a cheaper model decodes meaning across the supported languages perfectly well. So translate calls are now routed to Claude Haiku, which costs roughly a quarter as much per call. The other two jobs — restyling and fixing operator drafts that customers will actually read — still go through Sonnet, because brand voice on customer-facing replies is worth the extra cost.

## Step by step — what the code does now

PICKING THE MODEL FOR EACH REQUEST

When a request comes in to the AI helper endpoint, the system looks at which of the three actions the operator asked for. If the action is "translate," it picks Haiku. For any other action ("fix" or "style"), it picks Sonnet. That choice is made once, before the call to Claude is sent.

CALLING CLAUDE WITH THE CHOSEN MODEL

The system then sends the prompt to Claude using the model it just picked, instead of always sending to Sonnet the way it did before. Everything else about the call — the prompt content, the maximum response length, the response handling, the error path — is unchanged. The endpoint's request and response shape is also unchanged, so the frontend needs no updates.

LOGGING WHICH MODEL HANDLED THE CALL

After a successful call, the system writes a log entry the same way it always has, except the entry now also records which model was used. This means cost reviews and any future quality investigation can see exactly how many translate calls went to Haiku and how many style/fix calls went to Sonnet, on a per-call basis.

THREE NEW TESTS

The first test sends a translate request and confirms the call to Claude was made with the Haiku model. The second test sends a fix request and confirms it still goes to Sonnet. The third test sends a style request and confirms it also still goes to Sonnet. Together these guard against accidental regressions in either direction — translate accidentally going back to Sonnet (cost regression), or fix/style accidentally being downgraded to Haiku (quality regression on customer-facing drafts).

## Edge cases

- If Haiku produces a noticeably weaker translation in one of the supported languages than Sonnet did yesterday, operator-side translations will look slightly worse. The fallback is a one-line revert that puts translate back on Sonnet. The brief acknowledges this trade openly.
- If the action field on a request is anything other than "translate" — including unexpected values, capitalization differences like "Translate," or a typo — the system treats it as not-translate and routes to Sonnet. That is safe (drafts get the higher-quality model) but means a frontend bug that mistypes the action could quietly cost more, not less.
- The translate path used by the AI Editor inside the escalation composer (translating an operator's draft TO the customer's language before sending) also moves to Haiku, because the routing is by action name, not by which UI triggered it. Both translate use-cases now share the same cheaper model.
- Every successful call now writes the model name into the log entry. Older log entries from before this change have an action field but no model field, so any dashboard that aggregates this log needs to treat the model field as optional for historical records.
- If Claude returns an empty response, the endpoint still returns a 500 error the same way it did before. The model selection logic does not change error behavior in any way.

## What did NOT change

The endpoint contract is identical — same URL, same request fields, same response shape. The prompt that gets built for each action is unchanged. Marina's prompt, the customer-facing reply pipeline, the booking flow, and the WhatsApp/DM handling are not touched at all by this change. The "fix" and "style" actions, which are the ones whose output goes back to customers, continue to run on the same model they always did. The only behavioral change is which Claude model number gets put in the outbound API call when the action is translate, and the addition of that model name to one log line.
