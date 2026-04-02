# BRIEF 133 — Payment Timing + Hardcoded Cleanup
**Status:** Draft | **Files:** `config/client.json`, `agents/marina/marina_agent.py`, `agents/social/social_agent.py`, `agents/marina/email_poller.py` | **Depends on:** None | **Blocks:** Phase 2 multi-tenant

## Context

The codebase has charter-specific values hardcoded in source code that should come from client.json. A non-charter client (real estate, restaurant) would hit: (1) payment links generated when they don't need payment, (2) "info@bluefinncharters.com" in the prompt, (3) "boat trips" and "BBQ" in example messages, (4) "BF-" prefix on booking references. Four quick fixes, all config-driven.

## Why This Approach

All four fixes are read-from-config patterns. No new logic complexity. The existing `config_loader.get_business()`, `config_loader.get_booking_rules()`, and payment section in client.json already exist — we just need to add fields and read them.

**Tradeoff:** The booking ref regex `BF-\d{4}-\d{5}` for returning customer detection needs to become dynamic. We build the regex from the config prefix.

## Source Material

### Current client.json payment section (lines 22-33):
```json
"payment": {
    "methods": ["Credit card", "iDeal", "Apple Pay", "Google Pay", "Amex"],
    "cash_policy": "Cash accepted at office only, minimum 24 hours in advance",
    "no_payment_at_boarding": true,
    "hold_duration_hours": 6
}
```
No `timing` field exists yet.

### Current client.json booking_rules section (lines 34-50):
```json
"booking_rules": {
    "advance_booking_typical_days": "4-7",
    "group_threshold_requires_human": 15,
    "required_fields": ["experience", "date", "guests"],
    ...
}
```
No `booking_ref_prefix` field exists yet.

### Hardcoded email: `info@bluefinncharters.com` at marina_agent.py lines 274, 294
### Hardcoded "BlueFinn team" at marina_agent.py line 183
### Hardcoded "BF-" prefix at social_agent.py line 630 and email_poller.py line 1080
### Hardcoded `BF-\d{4}-\d{5}` regex at social_agent.py line 286 and email_poller.py line 298
### Business email available at `config_loader.get_business()["email"]` = `"info@bluefinncharters.com"`

## Instructions

### Step 1: Add config fields to `config/client.json`

**1a.** Add `"timing": "upfront"` to the payment section:
```json
"payment": {
    "timing": "upfront",
    "methods": [...],
    ...
}
```

**1b.** Add `"booking_ref_prefix": "BF"` to booking_rules section:
```json
"booking_rules": {
    "booking_ref_prefix": "BF",
    "advance_booking_typical_days": "4-7",
    ...
}
```

### Step 2: Fix marina_agent.py

**2a.** Line 274 — replace hardcoded email:
```
CONTACT INFO RULE: info@bluefinncharters.com and the business phone number
```
→
```
CONTACT INFO RULE: {business.get('email', '')} and the business phone number
```
Note: `business` is already in scope (assigned at line 87 of `_build_system_prompt`).

**2b.** Line 294 — replace hardcoded email:
```
- Do NOT give out the business phone number or email address (info@bluefinncharters.com)
```
→
```
- Do NOT give out the business phone number or email address ({business.get('email', '')})
```

**2c.** Line 183 — replace "BlueFinn team":
```
Write as a real member of the BlueFinn team.
```
→
```
Write as a real member of the {business.get('name', 'the')} team.
```

**2d.** Lines 160-166 — genericize WhatsApp GOOD examples:
```
"We do a few different boat trips plus jet ski. Any of those sound good?"
```
→
```
"We've got a few options — want me to run through them?"
```
Keep lines 163, 165-166 as-is (already generic enough).

**2e.** Line 171 — genericize BAD example:
```
"That's a great choice! The Klein Curacao trip is an amazing experience!"
```
→
```
"That's a great choice! What an amazing experience you'll have!"
```

**2f.** Lines 196-197 — genericize email GOOD example:
```
"Saturday works, we've got space. That trip leaves at 9:00, it's $85 per
person so $340 for four.
```
→
```
"Saturday works, we've got space. That's at 9:00, $85 per person so $340
for four.
```

**2g.** Lines 205-206 — genericize email mid-booking example:
```
"Yep, drinks are included once the BBQ is served. Beer, wine, cocktails.
Now for the booking, I just need the kids' ages so I can get your total
right."
```
→
```
"Yep, that's all included. Now for the booking, I just need the kids'
ages so I can get your total right."
```

### Step 3: Fix social_agent.py

**3a.** Line 630 — booking ref prefix from config:
```python
booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
```
→
```python
_ref_prefix = config_loader.get_booking_rules().get("booking_ref_prefix", "BM")
booking_ref = f"{_ref_prefix}-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
```

**3b.** Line 286 — dynamic returning customer regex:
```python
_ref_match = re.search(r'BF-\d{4}-\d{5}', text)
```
→
```python
_ref_prefix = config_loader.get_booking_rules().get("booking_ref_prefix", "BM")
_ref_match = re.search(rf'{re.escape(_ref_prefix)}-\d{{4}}-\d{{5}}', text)
```

**3c.** Payment timing in booking confirmation (around line 663-672). Keep `trip_key` and `[BOOKING_REF]` replacement OUTSIDE the conditional (they're needed regardless). Only wrap the payment link generation:

Replace lines 663-672 with:
```python
                trip_key = fields.get("trip_key", "")
                reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)

                # Payment timing: only generate link for upfront/deposit
                _payment_timing = config_loader.get_raw().get("payment", {}).get("timing", "upfront")
                if _payment_timing in ("upfront", "deposit"):
                    price_usd = (config_loader.get_trip(trip_key).get("price_adult_usd", 0)
                                 if trip_key else 0)
                    pay = payment_stub.generate_payment_link(booking_ref, price_usd)
                    pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                    flags["payment_id"] = pay.get("payment_id")
                    flags["payment_link"] = pay_link
                    flags["payment_status"] = pay.get("status")
                    reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                else:
                    reply_text = reply_text.replace("[PAYMENT_LINK]", "")
```

Note: `trip_key` stays outside the conditional (used by logging at line 673+). `[BOOKING_REF]` replacement stays outside (always needed). Only `[PAYMENT_LINK]` is conditional.

### Step 4: Fix email_poller.py

**4a.** Line 1080 — booking ref prefix from config:
```python
booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
```
→
```python
_ref_prefix = config_loader.get_booking_rules().get("booking_ref_prefix", "BM")
booking_ref = f"{_ref_prefix}-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
```

**4b.** Line 298 — dynamic returning customer regex:
```python
match = re.search(r'BF-\d{4}-\d{5}', body)
```
→
```python
_ref_prefix = config_loader.get_booking_rules().get("booking_ref_prefix", "BM")
match = re.search(rf'{re.escape(_ref_prefix)}-\d{{4}}-\d{{5}}', body)
```

**4c.** Lines 1127-1136 — same pattern as Step 3c. Keep `trip_key` and `[BOOKING_REF]` outside, wrap only payment:

Replace lines 1127-1136 with:
```python
                            trip_key = fields_now.get("trip_key", "")
                            reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)

                            _payment_timing = config_loader.get_raw().get("payment", {}).get("timing", "upfront")
                            if _payment_timing in ("upfront", "deposit"):
                                price_usd = (config_loader.get_trip(trip_key).get("price_adult_usd", 0)
                                             if trip_key else 0)
                                pay = payment_stub.generate_payment_link(booking_ref, price_usd)
                                pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                                th["flags"]["payment_id"] = pay.get("payment_id")
                                th["flags"]["payment_link"] = pay_link
                                th["flags"]["payment_status"] = pay.get("status")
                                reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                            else:
                                reply_text = reply_text.replace("[PAYMENT_LINK]", "")
```

## Tests

File: `tests/social/test_133_generalize_config.py`

1. **test_payment_timing_none_strips_link** — mock booking confirmation path with `payment.timing="none"` in config, verify `[PAYMENT_LINK]` stripped from reply and payment_stub NOT called
2. **test_payment_timing_upfront_unchanged** — with `timing="upfront"`, verify payment link generated and `[PAYMENT_LINK]` replaced (regression)
3. **test_booking_ref_uses_config_prefix** — set `booking_ref_prefix="RS"` in config, generate booking ref, assert starts with `"RS-"`
4. **test_booking_ref_regex_matches_config_prefix** — set prefix to `"RS"`, insert `"RS-2026-12345"` in message text, verify returning customer detection finds it
5. **test_booking_ref_regex_default_prefix** — no prefix in config, verify default `"BM-"` is used
6. **test_prompt_no_hardcoded_bluefinn_email** — build prompt, verify `"info@bluefinncharters.com"` appears only as a value from config (search for the literal string in prompt — it should appear because the config value IS that email, but verify it's read from config by temporarily patching get_business)
7. **test_prompt_no_charter_specific_examples** — build prompt with `channel="whatsapp"`, verify "boat trips" not in prompt, "BBQ" not in prompt, "Klein Curacao" not in prompt
8. **test_prompt_email_no_bluefinn_team** — build prompt with `channel="email"`, verify "BlueFinn team" not in prompt (should read from config)
9. **test_payment_timing_none_keeps_booking_ref** — mock booking confirmation path with `payment.timing="none"`, verify `[BOOKING_REF]` IS replaced with actual ref (not stripped), while `[PAYMENT_LINK]` IS stripped

## Success Condition

Client.json drives payment timing, booking ref prefix, contact email, and team name. No charter-specific strings hardcoded in source. All 9 tests pass.

## Rollback

Remove `timing` and `booking_ref_prefix` from client.json. Revert marina_agent.py, social_agent.py, email_poller.py from git.
