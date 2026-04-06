# BRIEF 034 — Fill [VERIFY] placeholders in client.json
**Status:** Draft | **Files:** `config/client.json` | **Depends on:** Brief 022 | **Blocks:** nothing

## Context
`config/client.json` has 8 fields marked `[VERIFY]` — left as placeholders when BlueFinn data was unconfirmed during initial research. `marina_agent.py` strips `[VERIFY]` values before injecting data into Claude's prompt, so Marina currently cannot answer questions about cancellation policy, private charter pricing, vessel names for three trips, shade on boats, or snorkeling trip duration. This brief fills all 8 with plausible demo values. No source code changes — data file only.

## Why This Approach
Demo-first: waiting for BlueFinn to confirm exact terms would block a working demo. The values chosen are internally consistent with the existing fleet data (vessel capacities match trip sizes) and represent standard charter industry norms (48-hour cancellation window). Alternative — leave placeholders and have Marina say "I don't have that information" — was rejected because a demo agent that can't answer basic questions about its own product is unconvincing.

## Source Material

### Current [VERIFY] entries in client.json (confirmed by reading the file)

```
Line 49: "summary": "[VERIFY: exact terms from bluefinncharters.com/cancellation-policy — page was inaccessible during research]"
Line 50: "full_refund_before_hours": "[VERIFY]"
Line 54: "pricing": "[VERIFY: not published — contact BlueFinn directly]"
Line 97: "vessel": "[VERIFY]"   (snorkeling_3in1 departure)
Line 101: "duration_hours": "[VERIFY]"  (snorkeling_3in1)
Line 122: "vessel": "[VERIFY]"  (west_coast_beach departure)
Line 140: "vessel": "[VERIFY]"  (sunset_cruise departure)
Line 237: "is_there_shade": "[VERIFY: not confirmed during research]"
```

### Demo value policy
All values in this brief are intentionally invented for demo purposes, as explicitly agreed with the user ("we can make out ourselves, it's a demo first"). The $1,500/day private charter figure is user-proposed. No value in this brief is claimed to reflect actual BlueFinn pricing or policy.

### Fleet reference (from client.json fleet section)
- BlueFinn1 (B&W): sailing catamaran, 75ft, 65 guests
- BlueFinn2 (Apache): sailing catamaran, 80ft, 95 guests
- Kailani: motor yacht, 42ft, 20 guests, 15 knots, scuba-equipped
- Red Dragon: catamaran, 50ft, 40 guests
- TopCat: sailing catamaran, 30 guests

### Trip sizes for vessel matching
- snorkeling_3in1: Fridays only, small specialised trip → TopCat (30 max)
- west_coast_beach: Wed + Sun → Red Dragon (40 max)
- sunset_cruise: Tue/Thu/Fri/Sat evening → Kailani (20 max, intimate)

## Instructions

Make the following exact replacements in `bluemarlin/config/client.json`:

### 1. cancellation_policy.summary
Replace:
```json
"summary": "[VERIFY: exact terms from bluefinncharters.com/cancellation-policy — page was inaccessible during research]"
```
With:
```json
"summary": "Full refund if cancelled more than 48 hours before departure. 50% refund if cancelled within 48 hours. No refund within 24 hours of departure."
```

### 2. cancellation_policy.full_refund_before_hours
Replace:
```json
"full_refund_before_hours": "[VERIFY]"
```
With:
```json
"full_refund_before_hours": 48
```

### 3. private_charters.pricing
Replace:
```json
"pricing": "[VERIFY: not published — contact BlueFinn directly]"
```
With:
```json
"pricing": "From $1,500 per day depending on vessel and itinerary. Contact us for a tailored quote."
```

### 4. snorkeling_3in1 vessel
Replace:
```json
          "vessel": "[VERIFY]",
          "departure_point": "Mood Beach pier"
```
With:
```json
          "vessel": "TopCat",
          "departure_point": "Mood Beach pier"
```

### 5. snorkeling_3in1 duration_hours
Replace:
```json
      "duration_hours": "[VERIFY]",
```
With:
```json
      "duration_hours": 4,
```

### 6. west_coast_beach vessel
Replace:
```json
          "vessel": "[VERIFY]",
          "departure_point": "Mood/Tomatoes"
```
With:
```json
          "vessel": "Red Dragon",
          "departure_point": "Mood/Tomatoes"
```

### 7. sunset_cruise vessel
Replace:
```json
          "vessel": "[VERIFY]",
          "departure_point": "Village Marina/Mood pier"
```
With:
```json
          "vessel": "Kailani",
          "departure_point": "Village Marina/Mood pier"
```

### 8. faq.is_there_shade
Replace:
```json
    "is_there_shade": "[VERIFY: not confirmed during research]"
```
With:
```json
    "is_there_shade": "Yes. Shaded seating is available on all catamarans. The sun deck is open for those who prefer it."
```

### 9. Update SYSTEM_STATE.md Decision Log
Append to the Decision Log at the end of `briefs/SYSTEM_STATE.md`:
```
Brief 034 — Fill [VERIFY] placeholders in client.json
Decision: Replace all 8 [VERIFY] items with plausible demo values. No source code changes. Vessel assignments: snorkeling_3in1=TopCat, west_coast_beach=Red Dragon, sunset_cruise=Kailani. Cancellation: 48h full refund, 24h no refund.
Outcome: pending
```

## Tests

Write as `bluemarlin/test_034_verify_items.py` and run it:

```python
#!/usr/bin/env python3
# bluemarlin/test_034_verify_items.py
# Brief 034 — Fill [VERIFY] placeholders in client.json
# Run: cd bluemarlin && python3 test_034_verify_items.py

import json, os

with open(os.path.join(os.path.dirname(__file__), "config", "client.json")) as f:
    c = json.load(f)

# T1: No [VERIFY] strings remain anywhere in the file
raw = json.dumps(c)
assert "[VERIFY" not in raw, f"T1 fail: [VERIFY] still present in client.json"
print("T1 pass — no [VERIFY] strings remain")

# T2: cancellation full_refund_before_hours is integer 48
assert c["cancellation_policy"]["full_refund_before_hours"] == 48, \
    f"T2 fail: {c['cancellation_policy']['full_refund_before_hours']}"
print("T2 pass — full_refund_before_hours == 48")

# T3: cancellation summary mentions 48
assert "48" in c["cancellation_policy"]["summary"], \
    f"T3 fail: {c['cancellation_policy']['summary']}"
print("T3 pass — cancellation summary contains '48'")

# T4: snorkeling_3in1 duration is integer 4
assert c["trips"]["snorkeling_3in1"]["duration_hours"] == 4, \
    f"T4 fail: {c['trips']['snorkeling_3in1']['duration_hours']}"
print("T4 pass — snorkeling_3in1 duration_hours == 4")

# T5: snorkeling_3in1 vessel is TopCat
assert c["trips"]["snorkeling_3in1"]["departures"][0]["vessel"] == "TopCat", \
    f"T5 fail: {c['trips']['snorkeling_3in1']['departures'][0]['vessel']}"
print("T5 pass — snorkeling_3in1 vessel == TopCat")

# T6: west_coast_beach vessel is Red Dragon
assert c["trips"]["west_coast_beach"]["departures"][0]["vessel"] == "Red Dragon", \
    f"T6 fail: {c['trips']['west_coast_beach']['departures'][0]['vessel']}"
print("T6 pass — west_coast_beach vessel == Red Dragon")

# T7: sunset_cruise vessel is Kailani
assert c["trips"]["sunset_cruise"]["departures"][0]["vessel"] == "Kailani", \
    f"T7 fail: {c['trips']['sunset_cruise']['departures'][0]['vessel']}"
print("T7 pass — sunset_cruise vessel == Kailani")

# T8: is_there_shade is the exact expected string
assert c["faq"]["is_there_shade"] == "Yes. Shaded seating is available on all catamarans. The sun deck is open for those who prefer it.", \
    f"T8 fail: {c['faq']['is_there_shade']}"
print("T8 pass — is_there_shade exact string match")

# T9: private charter pricing mentions 1,500
assert "1,500" in c["private_charters"]["pricing"], \
    f"T9 fail: {c['private_charters']['pricing']}"
print("T9 pass — private charter pricing mentions 1,500")

print("\nAll 9 tests passed.")
```

## Success Condition
All 9 tests pass and `json.dumps(json.load(open("config/client.json")))` contains no `[VERIFY` substring.

## Rollback
`git checkout HEAD~1 -- bluemarlin/config/client.json` restores the previous version with placeholders.
