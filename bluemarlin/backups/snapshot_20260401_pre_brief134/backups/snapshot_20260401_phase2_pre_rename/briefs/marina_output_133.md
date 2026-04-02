# OUTPUT 133 — Payment Timing + Hardcoded Cleanup

## What was done

### Fix 1: Payment timing flag
- Added `payment.timing: "upfront"` to client.json
- `social_agent.py`: booking confirmation checks `payment.timing` — "upfront"/"deposit" generates payment link, "none"/"at_service" strips `[PAYMENT_LINK]` placeholder
- `email_poller.py`: same payment timing conditional
- `price_usd` moved outside conditional (needed by sheets logging regardless)
- `pay.get("status")` replaced with `flags.get("payment_status")` in sheets logging (avoids NameError when no payment)

### Fix 2: Hardcoded email → config
- Replaced `info@bluefinncharters.com` in CONTACT INFO RULE (line 273) with `{business.get('email', '')}`
- Same replacement in semi-escalation section (line 293)
- Both are inside the f-string return statement, `business` already in scope

### Fix 3: Generic prompt examples
- WhatsApp GOOD: "boat trips plus jet ski" → "a few options"
- Email GOOD: "That trip leaves" → "That's at"
- Email mid-booking: "drinks included once the BBQ is served" → "that's all included"
- BAD: "Klein Curacao trip" → "What an amazing experience you'll have!"
- Email style: "BlueFinn team" → `{business.get('name', 'the')} team`

### Fix 4: Booking ref prefix from config
- Added `booking_rules.booking_ref_prefix: "BF"` to client.json
- `social_agent.py` + `email_poller.py`: read prefix from config, default "BM"
- Returning customer regex now dynamic: `rf'{re.escape(prefix)}-\d{{4}}-\d{{5}}'`

## Test results
- **Brief 133 tests: 9/9 passed**
- Full social regression: pending

## Unexpected
- `price_usd` and `pay` variables were referenced in sheets logging (line 696-700) outside the payment conditional. Moving only the payment link generation into the if-block left these as NameErrors. Fixed by computing `price_usd` before the conditional and using `flags.get("payment_status")` instead of `pay.get("status")`.
- Config caching: test 1 mutated the cached config dict (`raw["payment"]["timing"] = "none"`) which leaked into test 2. Fixed with try/finally to restore original value.
