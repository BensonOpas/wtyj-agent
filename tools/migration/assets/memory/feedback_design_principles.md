---
name: Core design principles
description: Think in scale and dynamism — every system decision must consider multi-client, data-driven design
type: feedback
---

When designing or modifying ANY part of the system, always think:

1. **Does this break with a second client?** Code should not know the business data structure. client.json is the interface — the code is a thin layer over it.

2. **Does data change require code change?** If adding a cancellation policy to client.json means updating marina_agent.py — the design is wrong.

3. **Is Claude the integrator.** The user doesn't write code — Claude does ALL coding. The system should be designed so Claude can adapt it for a new client with minimal, predictable changes. Less hardcoding = fewer places to touch = fewer bugs.

4. **client.json is the contract** between the human (who knows the business) and Claude (who builds the system). The thinner the code layer between client.json and the AI agent, the faster onboarding is.

5. **Scale test every decision.** 5 trips → 50. 1 client → 10. 20 FAQs → 200. If any of those need code changes, reconsider.

**Why:** The business model is setup fee + monthly maintenance. Claude does the technical work. Dynamic, data-driven design makes Claude's job faster and safer per client.

**How to apply:** Before writing any brief, ask these 5 questions. If the answer to any is "yes this hardcodes something" — redesign before proceeding.
