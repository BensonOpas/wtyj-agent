#!/usr/bin/env python3
# bluemarlin/test_034_verify_items.py
# Brief 034 — Fill [VERIFY] placeholders in client.json
# Run: cd bluemarlin && python3 test_034_verify_items.py

import json, os

with open(os.path.join(os.path.dirname(__file__), "..", "..", "config", "client.json")) as f:
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
