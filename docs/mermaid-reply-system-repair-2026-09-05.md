# Tracy reply-system repair — 5 September 2026

The reported WhatsApp turn supplied four adults, a 13-year-old, an 11-month-old baby, a wheelchair note and uncertainty about the travel date. Production first delivered a generation-failure notice, then a successful reply that asked for an exact date. Runtime metadata showed two model attempts, one rejected structured response and no container restart. The original rejection reason was not recorded, so its exact invalid field cannot be established retrospectively.

## Defects repaired

- A recoverable model error sent a customer failure notice before the existing durable worker retried. Retries now stay silent; only exhaustion or a non-retryable provider problem produces the single failure notice. Existing bounded attempts, leases, send idempotency, manual mute and tenant-control checks remain enforced.
- The age validator rejected the entire list if any child was 13 or older, potentially dropping the infant's age too. Ages under 18 are now preserved. Teenagers retain adult fares but are described by their supplied age: four adults, one child aged 13, one infant aged 11 months. Money still comes from the fare counts and immutable quote snapshot.
- Date uncertainty had no saved representation. An evidenced undecided-date request now asks for a broad week/month; repeated uncertainty or an explicit wish to decide later defers the date and allows other details/questions. No summary or quote can be confirmed without a selected date.
- Assistance and other protected reply routes could discard separate questions. FAQ evidence and answer fields, plus multiple protected status selectors, now retain separate concerns. Security, cancellation, confirmation and review restrictions retain their authority. Protected wheelchair acknowledgements and wildlife facts are not duplicated from old model prose.
- A captured Papiamentu answer copied the English phrase “beach house” from business facts and failed the language gate. This exact phrase now uses the existing approved “kas di playa” wording before validation. Other register checks remain active. Explicit requests to switch languages no longer get trapped by the previous Papiamentu locale. This is not a claim of native-speaker certification.
- Rejected responses now log fixed validation reason codes and attempt counts without raw guest/model text. The Mermaid empty-reply logger no longer logs an output preview.
- Repeated identical automated greetings can sustain a bot-to-bot exchange. A Mermaid-only guard suppresses the third matching automated greeting within ten minutes after two replies. It neither mutes the conversation nor changes tenant controls; a different genuine question can proceed. Manual operator activity resets the evidence. This is a narrow loop guard, not a claim to detect every possible bot.

## Verification and remaining external blocker

New regressions cover the supplied screenshot in all six locales, teenager/infant boundaries and fare preservation, deferred-date follow-ups, mixed calendar/pickup/wildlife/food questions, captured duplicate replies, provider retry delivery counts, language switching, and automated-greeting suppression with normal conversation recovery. Existing payment, reservation, delivery, review and manual-mute tests are included in the release gate. A few older tests contained English responses labelled Papiamentu or timestamps outside the history window; their fixtures were corrected to test their intended behavior.

The fresh synthetic real-model audit used isolated local state and stubbed customer delivery; no test sent a WhatsApp message or mounted production conversation data. The first runner had a local config-path mistake and made no successful provider call. The corrected runner completed four turns and captured one rejected Papiamentu turn, exposing additional duplication and terminology defects that were then repaired. The next candidate audit attempt was rejected by Anthropic for insufficient API credit, and further paid calls stopped. Only Anthropic is configured in the production container. A final real-model audit therefore remains blocked until credit is restored; offline regressions are not a substitute for that check.

The separate user-requested mute of the looping WhatsApp conversation must survive deployment. Do not resume the paused Codex monitor, unmute that conversation, or replay its messages.

## Restart-control defect found by deployment verification

The first repaired image, source `83878de1682b0e9b92787bde72adf13a15b0ff75`, passed 1,249 tests in its isolated Python 3.12 runtime and was deployed at 01:46:33 UTC. Verification then caught startup reconciliation clearing the explicitly paused loop conversation at 01:46:37. Its routine assumed every transport mute belonged to an active review. No operator action or restart failure caused that change. The requested pause was immediately restored.

The follow-up records `ai_mute_source` for manual controls. Startup preserves an explicit manual pause independently of review state and conservatively recognizes a legacy standalone pause without an associated review/booking freeze. Genuine orphaned escalation freezes still repair; explicit operator release/handback still resumes the conversation. Regression tests cover legacy migration, repeated startup, manual pause plus a soft review, explicit resume, and the existing orphan cleanup. This issue was discovered after the initial release gate; the first 1,249-test result does not claim to test this follow-up.

## Final deployed state

- Runtime source: `1739d9672d2cb48d535bb1cc909f5885263d4134`.
- Image: `wtyj-agent:tracy-replies-1739d9672d2c`; digest `sha256:40373dd144cc21fea382ef0a99907d03fd194035a5ac5ea88b43788f7054dbcb`.
- Started: 2026-09-05 01:58:39 UTC (4 September, 21:58:39 Curaçao).
- The main repair passed 1,249 isolated image tests. The final startup-control follow-up passed 271 targeted tests both locally and in its exact Python 3.12 image; these groups overlap and must not be added as a unique-test count.
- Local/public Mermaid health and the dashboard returned HTTP 200. Ten changed runtime files matched the pinned source. Restart count was zero, restart policy remained `unless-stopped`, controls were available with AI replies and WhatsApp enabled, and all six peer containers were preserved.
- Startup reconciliation ran at 01:58:42 UTC. The user-paused loop conversation remained muted and was recorded with source `manual`. The earlier test conversation remained unmuted. No pause was reasserted after this final startup: the application preserved it itself.
- Final rollback material: `/root/backups/mermaid-reservations/20260905T015836Z-1739d9672d2c`. Live configuration files and provider binding were unchanged.
- The fresh final-model check remains outstanding following Anthropic's insufficient-credit rejection. No further paid requests, test customer messages, or payments were made; the Codex monitor was not resumed.

The first broad image-test runner was stopped when legacy tests waited on prohibited external connections. The completed isolated runs used a closed localhost SDK endpoint, disabled networking and temporary memory-backed test storage. Production credentials and data were never provided to these test containers. Synthetic model evidence and test logs are retained locally under `Mermaid/output/tracy-reply-audit-2026-09-05/`.
