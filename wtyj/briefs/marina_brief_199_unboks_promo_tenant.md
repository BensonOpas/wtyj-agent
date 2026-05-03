# BRIEF 199 — Unboks tenant: SOT-based client.json + WhatsApp credential migration for FB promo

**Status:** Draft | **Files:** `clients/unboks/config/client.json` (REPLACE), `clients/bluemarlin/config/platform.env` (VPS-only, remove WhatsApp/Zernio/Meta/Late credentials), `clients/unboks/config/platform.env` (VPS-only, receive those credentials), `wtyj/briefs/infra.md` (APPEND note about routing change), `wtyj/tests/test_199_unboks_config.py` (NEW) | **Depends on:** Brief setting up the unboks tenant container (committed `d852a73`, "Add unboks tenant"). | **Blocks:** Calvin/SR's Facebook promo of Unboks (currently mis-routed).

## Context

SR is launching a Facebook promo for Unboks. The promo posts in FB groups with a CTA to message a WhatsApp number (Calvin's, +599 968 81585). When prospects message it, an AI replies — but the AI is currently **BlueMarlin's Marina** (configured for Caribbean boat charters), not an Unboks-aware agent. Prospects asking "what does Unboks do" get answers about Klein Curacao trips and jet ski excursions.

**Evidence the routing is wrong:**

```
ssh root@108.61.192.52 stat -c '%s %y' /root/clients/*/data/state_registry.db
bluemarlin: 405504 bytes, 2026-05-03 13:54:30  (actively growing today)
adamus:     163840 bytes, 2026-04-12 04:13:52  (initial size, unchanged in 3 weeks)
consultadespertares: 163840 bytes, same        (initial size)
unboks:     163840 bytes, 2026-04-28 00:00:51  (initial container start, no traffic since)
```

**Per-tenant WhatsApp creds (current state):**
```
ssh root@108.61.192.52 grep -E '^(WHATSAPP|LATE|ZERNIO|META)' /root/clients/*/config/platform.env
bluemarlin: WHATSAPP_ACCESS_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN, WHATSAPP_BUSINESS_ACCOUNT_ID, META_APP_ID, META_APP_SECRET, LATE_API_KEY, ZERNIO_WEBHOOK_SECRET — all populated
adamus / consultadespertares / unboks — all empty
```

Cause: BlueMarlin was the first tenant set up (Brief 067 era). Calvin's WhatsApp number was wired to it for testing. Nothing redirected it when SR planned the FB promo. Dropdown for the connection still points at the BlueMarlin tenant's `/webhook/whatsapp` path.

**Calvin shipped a formal SOT spec** (Source of Truth — full text in chat history 2026-04-28) defining what Unboks is, what it does, escalation rules, channels, onboarding, pricing posture ("never quote — always defer to discovery call"), and what Unboks is NOT (chatbot builder, CRM, marketing tool, helpdesk, social tool). None of that is in any `client.json`. The unboks tenant has a placeholder shell config from when we set it up as an internal sandbox.

**What this brief delivers:**
1. The unboks tenant gets a real customer-facing `client.json` derived from Calvin's SOT spec, with agent_name `Calvin` (internal id `calvin-csa`), 5 languages, professional-but-casual tone, never-quote-pricing rule, and the SOT pasted verbatim into `agent_persona.freeform_notes` so Marina has the full product context.
2. The WhatsApp/Zernio/Meta/Late credentials move from `bluemarlin/config/platform.env` to `unboks/config/platform.env` on the VPS so the same number (+599 968 81585) routes to the unboks tenant once the webhook URL is updated on Meta/Zernio's side.
3. Both containers restart so the new config + cred move take effect.

**Out of scope (separate work):**
- **Updating Meta/Zernio's webhook URL** from `https://api.wetakeyourjob.com/bluemarlin/webhook/whatsapp` to `https://api.wetakeyourjob.com/unboks/webhook/whatsapp`. That config lives on Meta's developer dashboard or Zernio's account dashboard — Calvin/SR has access, not the backend. This brief just makes the unboks tenant ready; SR flips the URL.
- **Schema extension** for `features.channels.{whatsapp,email,instagram,facebook,messenger}` (per `wtyj/docs/project_open_work.md`) — bigger conversation, future brief.
- **Formalizing the SOT escalation rules** in code — currently in prompt only, future brief.
- **A separate WhatsApp number for unboks** so BlueMarlin gets its own back (Option C from the discussion). If we ever want BlueMarlin's demo to have WhatsApp again, that's a future brief.

## Why This Approach

Three options were considered:

**A — Move credentials bluemarlin → unboks (chosen).** Fastest path to fix the FB promo. No change to system architecture; just routes the existing number to the right tenant. BlueMarlin demo loses WhatsApp (acceptable — it's a demo with no real customers). Tradeoff: ties Calvin's personal number to the unboks tenant for now; if BlueMarlin demo ever needs WhatsApp again, that's a future brief.

**B — Rename bluemarlin → unboks.** Rejected. Conflates the demo identity (BlueMarlin Charters Curaçao, used for product showcasing) with the platform identity (Unboks). Would break all internal references in briefs/system_state/lessons (~9 months of paper trail), break the dashboard's per-workspace branding, break Adamus/Consulta's mental model.

**C — Provision new Zernio profile + new WhatsApp number for unboks.** Rejected for now (kept as future work). Cleanest long-term — BlueMarlin keeps its testing setup, Unboks gets its own contact channel. But requires SR to set up a new Zernio profile, possibly a new Meta Business number, OAuth flow, DNS verification — all on SR's timeline, not the backend's. Blocks the FB promo from launching today.

## Instructions

### Step 1 — Replace `clients/unboks/config/client.json`

Current content is a shell config (`name: "Unboks Test"`, all NA fields, generic "filter/buffer mode" persona — see existing file). Replace with the full SOT-based config below. The file is checked into the repo (`gitignore` only excludes `platform.env`, not `client.json`).

Exact replacement content for `clients/unboks/config/client.json`:

```json
{
  "business": {
    "name": "Unboks",
    "email": "butlerbensonagent@gmail.com",
    "booking_email": "",
    "phone": "+599 968 81585",
    "whatsapp": "+599 968 81585",
    "location": "Curaçao",
    "languages": ["English", "Papiamentu", "Spanish", "Dutch", "Swedish"],
    "operating_days": "24/7",
    "agent_name": "Calvin",
    "agent_signature": "Calvin\nUnboks",
    "agent_internal_id": "calvin-csa",
    "spreadsheet_id": "",
    "support_email": "butlerbensonagent@gmail.com",
    "operating_mode": "qualify_and_handoff"
  },
  "agent_persona": {
    "tone": "professional but casual, not stiff, never over-eager",
    "language_register": "polished and direct; helpful without being chatty; contractions are fine",
    "greeting_style": "On the first message in a thread, briefly introduce yourself ('Hi, this is Calvin from Unboks'). On follow-ups, skip the intro and just answer.",
    "closing_style": "Brief and useful. No 'let me know if you need anything else' on every reply. Sign off only on email — on chat, just answer.",
    "brand_voice_rules": [
      "Never use em-dashes or en-dashes",
      "Avoid 'I'd be happy to', 'Absolutely', 'Great choice', 'How exciting'",
      "One exclamation mark per message maximum",
      "No bullet-heavy formatting on chat — bullets only when listing things the customer actually asked to see",
      "No forced enthusiasm or sales-pitch energy",
      "Match the customer's language exactly — if they write in Papiamentu, you write in Papiamentu",
      "Never quote a price. Pricing is always 'we'd set that up during a discovery call' or similar — never a number",
      "Never compare Unboks to specific competitors by name",
      "Never claim Unboks does something it doesn't (see topics_refused)",
      "If asked 'are you a real person', say you're an AI representing Unboks. Don't lie. Don't over-apologize."
    ],
    "topics_allowed": [
      "What Unboks is and what it does",
      "Which communication channels Unboks supports",
      "How the AI handles routine messages and when it escalates",
      "How clients onboard (intake, Source of Truth setup, channel connection, dashboard access)",
      "The 14-day free trial",
      "What makes Unboks different from chatbot builders, CRMs, helpdesks",
      "Booking a discovery call with the human team",
      "Languages supported"
    ],
    "topics_refused": [
      "Specific prices, monthly fees, or numerical cost figures — always defer to a discovery call",
      "Direct comparisons to named competitors (Tidio, Intercom, ManyChat, Drift, etc.)",
      "Technical implementation details, integration code, or architecture",
      "Anything unrelated to Unboks (medical, legal, financial advice, general chitchat beyond pleasantries)",
      "Promises about future features or timelines unless explicitly listed in the SOT below",
      "Discussions about other clients' setups, names, or configurations"
    ],
    "small_talk": "Polite and brief. Match the customer's energy. If they're casual, be casual. If they're transactional, be transactional. A quick 'good morning' back is fine; don't manufacture rapport.",
    "escalation_tone": "Calm and factual. 'Let me connect you with the team — they'll reach out shortly.' No excessive apologizing.",
    "freeform_notes": "FULL SOURCE OF TRUTH (Calvin Adamus, founder, 2026-04-28):\n\nCORE VALUE\nWe save our clients time by letting AI answer routine messages and only passing selected messages to a human.\n\nCLIENTS\nOur clients receive the same kinds of messages every day across different channels and still answer them manually.\n\nCHANNELS\nWhatsApp, Email, Instagram, Facebook, Telegram, Messenger.\n\nCORE FUNCTIONALITY\n- AI automatically replies to messages.\n- AI uses client-provided information (the Source of Truth) to answer.\n- AI sorts and classifies messages (question, booking, order).\n- AI forwards messages to the right person.\n- AI follows up automatically.\n- AI learns and improves over time.\n- AI supports multiple languages.\n- AI runs 24/7.\n- All conversations are visible in one unified inbox.\n- Humans can step in and reply from the dashboard.\n\nESCALATION SYSTEM\nHard escalation (AI stops and hands the conversation to a human; the human replies directly from the dashboard) — triggered when:\n  - Booking is confirmed and paid.\n  - Customer asks for a human.\n  - Complaint.\n  - Refund or payment issue.\n  - Booking problem.\n  - Legal issue.\n  - Customer persists in inappropriate, unethical, or irrelevant behavior.\nSoft escalation: AI asks a human for input internally and uses that input to reply to the customer.\nNo escalation: Unclear question or low confidence. AI continues asking and iterating until resolved.\n\nKNOWLEDGE BASE (SOT)\nDuring intake, Unboks gathers all relevant client information and builds the Source of Truth. Sources include: PDFs, text and notes, FAQs, images, pricing, policies, website content, chat history. Clients can add or update information at any time. Temporary data is supported — special offers (Valentine's, Christmas), temporary opening hours, seasonal services or promotions.\n\nCOMMUNICATION STYLE\nTone of voice is defined during intake. Unboks sets how the AI communicates. Clients do not change tone directly. Unboks can update tone when needed.\n\nHUMAN HANDOVER\nAll escalations are handled inside the Unboks dashboard. Notifications can be sent externally (e.g. WhatsApp or Telegram) to alert the user.\n\nDAILY USE\nCheck notifications, view escalations, view messages, check bookings (bookings are treated as escalations).\n\nSTRUCTURED DATA EXTRACTION\nUnboks extracts structured data from messages: customer name, contact details, channel/source, date and time, number of people, service or order type, payment status, special requests, notes. Exact data fields are defined per client during intake.\n\nINTEGRATIONS\nWhatsApp, Email, Instagram, Facebook, Telegram, Messenger. Zernio is used internally but is not visible to the client.\n\nONBOARDING\n1. Client contacts Unboks.\n2. Unboks conducts intake conversation.\n3. Information is gathered.\n4. Channels are connected.\n5. Source of Truth is built.\n6. Client receives dashboard access.\nClient receives 14 days free after getting access. After 14 days, the service becomes paid.\n\nPRICING\nPricing is not fixed. Pricing is determined per client. Clients are asked to contact Unboks for personalized pricing.\n\nPOSITIONING\nUnboks replaces time spent on repetitive messages by letting AI handle them and only sending the important ones to you.\n\nWHAT UNBOKS IS NOT\nNot a chatbot builder. Not a CRM. Not a marketing tool. Not a helpdesk or ticketing system. Not a social media management tool.\n\n--- END SOT ---\n\nIDENTITY: You are Calvin, an AI representing Unboks. Calvin Adamus is the founder; you carry his name as a friendly handle for the AI. If asked directly whether you are a person, say you're an AI built by Unboks. Don't pretend to be Calvin the human. Don't apologize for being AI."
  },
  "payment": {
    "timing": "none",
    "methods": [],
    "cancellation_policy": "NA"
  },
  "features": {
    "booking_flow": false
  },
  "terminology": {
    "service_label": "service",
    "party_size_label": "people",
    "slot_label": "appointment"
  },
  "booking_rules": {
    "required_fields": [],
    "hold_duration_hours": 0,
    "group_threshold_requires_human": 0,
    "max_bookings_per_thread": 0
  },
  "services": {},
  "service_aliases": {},
  "faq": {
    "what_is_unboks": "Unboks is an AI inbox that handles the repetitive customer messages your team gets every day across WhatsApp, email, Instagram, Facebook, and Messenger. The AI replies automatically using info you give us, and only forwards the important ones — bookings paid, complaints, refunds, customers asking for a human — to you.",
    "what_channels": "WhatsApp, Email, Instagram, Facebook, and Messenger today. Telegram is on the roadmap.",
    "how_does_escalation_work": "Three modes. Hard escalation: AI stops and hands the conversation to your team — triggered when a booking is paid, a customer asks for a human, or there's a complaint, refund issue, booking problem, or legal matter. Soft escalation: AI asks your team for input internally and replies on your behalf. No escalation: AI keeps iterating to resolve the question.",
    "how_much_does_it_cost": "Pricing is set per client based on your channels, message volume, and complexity. Best way to get a number is to book a quick discovery call — we'll scope your setup and quote you directly.",
    "how_do_i_get_started": "Quick intake conversation with us, we gather your info, build your Source of Truth (the knowledge the AI uses), connect your channels, and give you dashboard access. First 14 days are free.",
    "is_unboks_a_chatbot_builder": "No. Unboks is not a chatbot builder, CRM, marketing tool, helpdesk, ticketing system, or social media manager. We replace time spent on repetitive messages — that's the only thing we do.",
    "do_you_handle_bookings": "Yes — when a booking comes through and gets confirmed and paid, the AI hands it to you as an escalation. You see it in the dashboard alongside other escalations.",
    "what_languages": "English, Papiamentu, Spanish, Dutch, Swedish. The AI replies in whichever language the customer writes in.",
    "where_are_you_based": "Curaçao.",
    "can_i_change_the_ai_tone": "The tone is defined during intake — Unboks sets how the AI communicates so it stays consistent. If you want it changed later, we update it on our side.",
    "what_about_temporary_offers": "Yes — seasonal promos, holiday hours, special offers can all be added to your Source of Truth and the AI uses them while they're active.",
    "free_trial": "14 days free after onboarding. After that, it becomes paid at the rate we agreed during intake."
  },
  "common_sense_knowledge": {
    "marina_persona": "You are Calvin, an AI representing Unboks. Unboks is an AI inbox / escalation platform for small businesses. Your job is to answer questions about Unboks and qualify prospects. Never quote a specific price — always offer to schedule a discovery call. Never claim Unboks does things outside its scope (no CRM, no chatbot building, no marketing automation). When someone wants to actually sign up or asks detailed pricing, escalate to the human team. You speak 5 languages: English, Papiamentu, Spanish, Dutch, Swedish — match whatever the customer writes in."
  }
}
```

### Step 2 — Move credentials on VPS via script

Write a small idempotent shell script (locally at `/tmp/move_wa_creds.sh`), `scp` to VPS, execute, then delete. Script content:

```bash
#!/bin/bash
# Move WhatsApp/Zernio/Meta/Late credentials from bluemarlin tenant to unboks.
# Idempotent: safe to re-run. Backups created with timestamp.

set -e
SRC=/root/clients/bluemarlin/config/platform.env
DST=/root/clients/unboks/config/platform.env
BAK_SRC="$SRC.bak.$(date +%Y%m%d-%H%M%S)"
BAK_DST="$DST.bak.$(date +%Y%m%d-%H%M%S)"

cp "$SRC" "$BAK_SRC"
cp "$DST" "$BAK_DST"

KEYS="WHATSAPP_ACCESS_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_VERIFY_TOKEN WHATSAPP_BUSINESS_ACCOUNT_ID META_APP_ID META_APP_SECRET LATE_API_KEY ZERNIO_WEBHOOK_SECRET"
for KEY in $KEYS; do
  LINE=$(grep -E "^$KEY=" "$SRC" || true)
  [ -z "$LINE" ] && continue
  VAL=$(echo "$LINE" | sed "s/^$KEY=//")
  [ -z "$VAL" ] && continue
  if grep -qE "^$KEY=" "$DST"; then
    sed -i "/^$KEY=/d" "$DST"
  fi
  echo "$LINE" >> "$DST"
  sed -i "s|^$KEY=.*|$KEY=|" "$SRC"
done

chmod 600 "$DST" "$SRC"
echo "Move complete. Backups: $BAK_SRC and $BAK_DST"
```

Steps from local Mac:
- `scp /tmp/move_wa_creds.sh root@108.61.192.52:/root/move_wa_creds.sh`
- `ssh root@108.61.192.52 "chmod +x /root/move_wa_creds.sh && /root/move_wa_creds.sh && rm /root/move_wa_creds.sh"`
- `rm /tmp/move_wa_creds.sh`

### Step 3 — Restart both containers

```
ssh root@108.61.192.52 "cd /root/clients/bluemarlin && docker compose restart && cd /root/clients/unboks && docker compose down && docker compose up -d"
```

(BlueMarlin gets `restart` since the image is unchanged; Unboks gets `down + up -d` so the new client.json gets re-read from the volume mount.)

### Step 4 — Verify

```
ssh root@108.61.192.52 "for c in bluemarlin unboks; do
  echo \"--- \$c ---\"
  curl -sf http://localhost:\$(case \$c in bluemarlin) echo 8001;; unboks) echo 8004;; esac)/health
  echo
  grep -E '^(WHATSAPP|LATE|ZERNIO|META)' /root/clients/\$c/config/platform.env | sed 's/=.*=/=<set>/; s/=.\\+/=<set>/; s/=$/=<empty>/'
done"
```

Expected: bluemarlin returns `{"status":"ok"}` with all WhatsApp/Zernio/Meta/Late lines `=<empty>`; unboks returns `{"status":"ok"}` with all those lines `=<set>`.

### Step 5 — Append to `wtyj/briefs/infra.md`

Add a one-line note to the tenant table introduction or the channels section noting that the WhatsApp number `+599 968 81585` now routes to the `wtyj-unboks` tenant (since 2026-05-03, Brief 199), not `wtyj-bluemarlin`. The bluemarlin tenant retains zero channel credentials and runs as a code-only demo.

## Tests

One new behavioral test at `wtyj/tests/test_199_unboks_config.py`:

```python
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
UNBOKS_CONFIG = REPO_ROOT / "clients" / "unboks" / "config" / "client.json"

def test_unboks_client_json_is_valid():
    """The unboks client.json parses cleanly and has required top-level keys."""
    with open(UNBOKS_CONFIG) as f:
        cfg = json.load(f)
    required_top_level = {"business", "agent_persona", "payment", "features",
                          "terminology", "booking_rules", "services",
                          "service_aliases", "faq", "common_sense_knowledge"}
    assert required_top_level <= set(cfg.keys()), \
        f"missing keys: {required_top_level - set(cfg.keys())}"

def test_unboks_business_identity():
    """Business block has Calvin as agent and 5 languages, booking off."""
    cfg = json.loads(UNBOKS_CONFIG.read_text())
    assert cfg["business"]["name"] == "Unboks"
    assert cfg["business"]["agent_name"] == "Calvin"
    assert cfg["business"]["agent_internal_id"] == "calvin-csa"
    assert len(cfg["business"]["languages"]) == 5
    assert cfg["features"]["booking_flow"] is False

def test_unboks_persona_has_pricing_guard():
    """The brand_voice_rules block must include a never-quote-price rule."""
    cfg = json.loads(UNBOKS_CONFIG.read_text())
    rules_text = " ".join(cfg["agent_persona"]["brand_voice_rules"]).lower()
    assert "never quote" in rules_text and "price" in rules_text, \
        "brand_voice_rules must explicitly forbid quoting a specific price"
```

Three tests, all behavioral (parse + assert specific values, not type checks).

**Regression baseline:** 904 passing / 0 failures (per Brief 198 system_state). After this brief: **907 passing / 0 failures** (904 + 3 new).

## Success Condition

After execution:
1. `cat clients/unboks/config/client.json` shows `"agent_name": "Calvin"` and the full SOT block in `agent_persona.freeform_notes`.
2. `ssh root@VPS grep -c '^WHATSAPP_ACCESS_TOKEN=.\+' /root/clients/bluemarlin/config/platform.env` returns `0` (line is empty).
3. `ssh root@VPS grep -c '^WHATSAPP_ACCESS_TOKEN=.\+' /root/clients/unboks/config/platform.env` returns `1` (populated).
4. `curl -sf https://api.wetakeyourjob.com/unboks/health` returns `{"status":"ok"}`.
5. `python3 -m pytest wtyj/tests/test_199_unboks_config.py -q` passes 3/3.
6. Full regression `python3 -m pytest wtyj/tests/ -q` shows 907 passing / 0 failures.

## Rollback

Step 2 creates timestamped backups (`platform.env.bak.YYYYMMDD-HHMMSS`) of both files before any change. To roll back the credential move:

```
ssh root@VPS "ls -t /root/clients/bluemarlin/config/platform.env.bak.* /root/clients/unboks/config/platform.env.bak.* | head -2 | while read F; do mv \$F \$(echo \$F | sed 's/.bak\\..*$//'); done"
ssh root@VPS "cd /root/clients/bluemarlin && docker compose restart && cd /root/clients/unboks && docker compose restart"
```

To roll back the client.json change: `git revert <this brief's source commit>` and push. ~3 min total.
