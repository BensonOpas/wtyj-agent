# OUTPUT_022 — client.json + config_loader.py

## Files created
- `bluemarlin/config/client.json`
- `bluemarlin/src/config_loader.py`
- `bluemarlin/briefs/OUTPUT_022.md` (this file)

## Files modified
None.

## Changes made

### bluemarlin/config/client.json
Created exactly as specified in the brief. Contains:
- `business` — name, email, phone, WhatsApp, location, languages, operating days, agent name/signature
- `payment` — methods, cash policy, no-boarding-payment flag, hold duration
- `booking_rules` — advance days, group threshold (15), required fields, extras, transfers, dietary notice
- `cancellation_policy` — `[VERIFY]` placeholders preserved as written
- `private_charters` — `[VERIFY]` pricing placeholder preserved
- `trips` — 5 trips: klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski
- `fleet` — 5 vessels: bluefinn1, bluefinn2, kailani, red_dragon, topcat
- `faq` — 27 FAQ entries
- `common_sense_knowledge` — timezone, currency, weather, dress code, Marina persona

All `[VERIFY]` items left exactly as written. Nothing invented.

### bluemarlin/src/config_loader.py
Created with the exact interface specified in the brief:
- Module-level `_cache: dict` populated on first call to `_load()`
- `_CONFIG_PATH` resolved relative to `__file__` — no absolute paths
- All 10 public functions implemented; all return empty fallback silently on any exception
- `get_agent_signature()` fallback: `"Marina\nBlueFinn Charters Curaçao"`
- File header follows project conventions

## Test results

| # | Test | Result |
|---|------|--------|
| 1 | `get_business()["name"] == "BlueFinn Charters Curaçao"` | PASS |
| 2 | `get_trip("sunset_cruise")["price_adult_usd"] == 79` | PASS |
| 3 | `get_trip("klein_curacao")["price_adult_usd"] == 120` | PASS |
| 4 | `"Tips" in get_faq_answer("extra_costs")` | PASS |
| 5 | `get_booking_rules()["group_threshold_requires_human"] == 15` | PASS |
| 6 | Missing keys return `{}` and `""` without raising | PASS |

## Regression check block
```
python3 -c "
import sys; sys.path.insert(0, 'bluemarlin/src')
from config_loader import get_business, get_trip, get_faq_answer, get_booking_rules
assert get_business()['name'] == 'BlueFinn Charters Curaçao'
assert get_trip('sunset_cruise')['price_adult_usd'] == 79
assert get_trip('klein_curacao')['price_adult_usd'] == 120
assert 'Tips' in get_faq_answer('extra_costs')
assert get_booking_rules()['group_threshold_requires_human'] == 15
assert get_trip('nonexistent_trip') == {}
assert get_faq_answer('nonexistent_question') == ''
print('config_loader Brief 022 regression OK')
"
```

## [VERIFY] items preserved
The following appear in client.json as placeholder strings and must not be replaced until BlueFinn confirms:
1. `cancellation_policy.summary` and `cancellation_policy.full_refund_before_hours`
2. `private_charters.pricing`
3. `calendar_id` on all 5 trips
4. `vessel` and `departure_point` for snorkeling_3in1, west_coast_beach, sunset_cruise
5. `duration_hours` for snorkeling_3in1
6. `faq.is_there_shade`
