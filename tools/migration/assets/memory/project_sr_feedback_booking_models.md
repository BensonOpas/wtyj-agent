---
name: SR feedback on booking models and business types (2026-04-01)
description: Calvin's real-world feedback on how real estate, restaurants work in Curaçao. Key insight — the system is a lead filter, not just a booking tool.
type: project
---

SR feedback from 2026-04-01 on the booking models discussion:

Real estate workflow in Curaçao:
- Agent has 10 houses listed, gets ~10 inquiries, ~6 turn into real conversations
- Common questions are FAQ-level: "is this house available?", "can we schedule a visit?", "do you have more pics/videos?"
- Agency answers those and asks qualifying questions: "are you on the island?", "family situation (kids, pets)?"
- If house not available, they offer different houses from their portfolio
- The value prop: with our system a guy with 10 houses could manage 40 houses because AI filters the lazy work — common questions, initial qualification, alternatives. Escalations handle the real stuff.

Restaurants:
- If they have an existing booking system, we plug into it
- If they don't have one, when a customer wants to reserve we escalate to a human worker
- Not every restaurant needs a full booking engine — some just need the communication handled

SR's key quote: agreed with "The AI collects requirements, qualifies the lead, then hands off to the actual person."

What this means for the product:
- The system is TWO things: a booking tool (charters, tours) AND a lead qualification/filter tool (real estate, restaurants without booking systems)
- Both already exist in our code: Marina does booking flow, escalation system handles handoffs
- The difference is just what client.json says: "this business has a booking flow" vs "this business escalates booking requests to a human"
- Real estate doesn't need a new booking model — it needs Q&A + portfolio matching + escalation. That's the DM agent pattern extended.
