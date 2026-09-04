# OUTPUT342 — Incidental pickup selectors and canonical confirmation

A pickup_pricing selector without an actual guest question no longer creates artificial uncertainty. The state machine records when it has produced the canonical summary or confirmed it, preventing volunteered pickup facts from replacing that response. Genuine price questions still retain their informational answer before approval; security, human review and cancellation priorities remain earlier.

The seven new behavior cases produced six failures and one existing pass before the fix. Afterwards158 combined confirmation, pickup, policy and soft-review tests passed. An independent reviewer approved the diff and reran82 confirmation/pickup tests successfully. Evidence remains in incidental-pickup-before.txt and incidental-pickup-after.txt. Parent performs final image/model gates; this commit performs no live changes or customer sends.
