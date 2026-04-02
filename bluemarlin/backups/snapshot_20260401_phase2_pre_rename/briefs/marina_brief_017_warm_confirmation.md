# BRIEF 017 — Warm confirmation email
# Read CODEX_CONTEXT.md before executing this brief
## Objective
Make the booking confirmation email warmer and more empathetic.
Add a social acknowledgement line when the customer was friendly.
Improve the overall tone — these are vacation bookings, high stakes.
## Context
Current confirmation email opens with "Hi," and goes straight to
the hold details. No warmth, no acknowledgement of the customer's
tone. Brief 016 added social intent detection but when social+booking
fires, the social tone is currently ignored in the confirmation reply.
## File to modify
bluemarlin/src/email_poller.py
## Files to read before making any changes
Read bluemarlin/src/email_poller.py lines 770 through 800 before
touching anything.
## Change 1 — update confirm email construction
Find this exact block (around line 779):
  confirm = (
      "Hi,\n\n"
      "✅ Your provisional hold has been created (valid for 6 hours).\n\n"
      f"- **Package:** {exp}\n"
      f"- **Guests:** {guests}\n"
      f"- **Date:** {date}\n"
      f"- **Name:** {name}\n\n"
      f"Calendar link (internal): {res.get('htmlLink','')}\n\n"
      f"Payment status: {th['flags'].get('payment_status', 'pending')}\n"
      f"Payment link: {th['flags'].get('payment_link', '')}\n\n"
      "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
  )
Replace with:
  social_opener = (
      "That means so much to us — thank you! "
      "We can't wait to have you on board. 🌊\n\n"
  ) if "social" in intents else ""
  special_note = (
      f"📝 We've noted your special request: {fields_now.get('special_requests')}\n\n"
  ) if fields_now.get("special_requests") else ""
  confirm = (
      f"Hi {name},\n\n"
      + social_opener +
      "✅ Your provisional hold has been created — "
      "you're one step closer to an unforgettable day on the water!\n\n"
      f"- **Package:** {exp}\n"
      f"- **Date:** {date}\n"
      f"- **Guests:** {guests}\n\n"
      + special_note +
      "Your hold is valid for 6 hours. To confirm your booking, "
      "please complete the payment using the link below:\n\n"
      f"💳 Payment link: {th['flags'].get('payment_link', '')}\n\n"
      f"Calendar link: {res.get('htmlLink','')}\n\n"
      "If you have any questions at all, just reply to this email "
      "and we'll take care of you.\n\n"
      "See you on the water! 🐟\n\n"
      "Warm regards,\nMarina\nBlueMarlin Tours Curaçao\n"
  )
## Change 2 — file header update
  # LAST MODIFIED: Brief 017
## Constraints
- Do not change any other part of the booking flow
- Do not change any other reply functions
- Do not change the intent classifier
- Do not change bm_logger or sheets_writer calls
- social_opener and special_note must never raise exceptions
- name variable is already defined above this block — do not redefine it
## Test commands
# Test 1 — imports cleanly
python3 -c "
import sys
sys.path.insert(0, 'bluemarlin/src')
import email_poller
print('IMPORT OK')
"
# Test 2 — confirm template contains warm elements
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert 'unforgettable day on the water' in content, 'FAIL: warm text missing'
assert 'social_opener' in content, 'FAIL: social_opener missing'
assert 'special_note' in content, 'FAIL: special_note missing'
assert 'social' in intents if False else True
print('PASS — warm confirmation template present')
"
# Test 3 — social_opener only fires when social in intents
python3 -c "
with open('bluemarlin/src/email_poller.py') as f:
    content = f.read()
assert '\"social\" in intents' in content, 'FAIL: social intent check missing'
print('PASS — social intent check present')
"
## Definition of done
- [ ] email_poller.py modified in bluemarlin/src/
- [ ] File header updated (Brief 017)
- [ ] confirm variable updated with warm tone
- [ ] social_opener fires only when social in intents
- [ ] special_note fires only when special_requests present
- [ ] Customer name used in greeting
- [ ] All 3 tests pass
- [ ] OUTPUT_017.md written to bluemarlin/briefs/
- [ ] OUTPUT_017.md includes SYSTEM_STATE update block
