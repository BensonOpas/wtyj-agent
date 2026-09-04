# Mermaid WhatsApp reply layout
**Status:** Deployed and verified | **Files:** tenant persona, Mermaid understanding contract, runtime overlay | **Depends on:** vehicle pricing release 776b0df | **Blocks:** None

## Context
The customer's screenshot shows activities, food, drinks, wildlife and crossing time squeezed into one dense WhatsApp paragraph. They want a little more explanation with visible paragraph breaks and a natural voice. The understanding contract only injects persona freeform notes, so its existing short-paragraph brand rule is absent from this route; its ordinary 55-word preference also needs a clear overview exception.

## Why This Approach
Add a tenant-owned presentation instruction to the existing single model call. Keep the model responsible for natural grouping and detail selection. Reject a fixed overview template or Python sentence splitter: both would rigidly format unrelated replies and could separate qualifications from the facts they qualify.

## Instructions
- Add persona guidance for a roughly 120–180-word trip overview in four short paragraphs separated by blank lines, using approved activities, inclusions, extras and conditional travel times where relevant.
- Preserve brief replies for simple questions and all booking state, price and timing rules. Elaborate through useful context, never invented inclusions or wildlife guarantees. Use WhatsApp-native formatting and no forced headings or generic closing questions.
- Inject the reviewed presentation guidance after the existing voice contract. Explicitly exempt broad trip overviews from the usual brevity preference.
- Verify real generated overview replies in English and Dutch, a response after a dense historical reply, and concise replies for narrow questions. Run only isolated synthetic conversations without messaging credentials.
- Deploy only Mermaid on the current vehicle-pricing image with an exact baseline guard, backup, and a minimal persona-field merge.

## Tests
Inspect actual model replies for short paragraphs, useful additional detail, factual qualifications and natural language. Confirm a narrow inclusions question stays short and a pickup question retains capacity, price and time. Validate the deployed prompt and unchanged catalog.

## Success Condition
Tracy explains the trip in readable short paragraphs with a little more detail while keeping simple answers short.

## Rollback
Restore the prior Mermaid image and client configuration from the release backup; preserve customer data and the current vehicle-pricing catalog.

## Verification
- 60 focused booking, multilingual intake and soft-review tests passed. The source change only exposes the tenant's presentation guidance to the existing model call and describes real paragraph breaks in the reply schema; no language classifier, second call or reply-rewriting pass was added.
- Five final real-model responses were inspected in disposable data without provider credentials. English/Dutch overviews and a follow-up after dense history used four paragraphs with 118–137 words. The towel answer was 16 words. Pickup still quoted a USD 125 van and 05:45 collection. An overly broad canary assertion rejected a rhetorical Dutch question inside the overview; it was narrowed to closing questions before the remaining cases ran.
- Earlier replies added unnecessary booking prompts and clock-time logistics. A grounded tenant example now anchors useful detail and spacing while leaving wording adaptable. General overviews omit clock-time logistics; existing timing and pricing rules remain in force for transport questions.
- Deployed source `796d5a2` as `wtyj-agent:tracy-layout-796d5a2`, digest `sha256:4a2130b44c0b281dfcf4d4119060b467faae801b45ba58ebb31e4631d6e3cbdd`. Backup: `/root/backups/tracy-layout-796d5a2`. The deployment verifies the exact source hash, changes only the new persona field in live client configuration, and leaves catalog bytes and all six peer containers unchanged. Public health and watchdog are healthy. No customer messages or reservation changes were made.
