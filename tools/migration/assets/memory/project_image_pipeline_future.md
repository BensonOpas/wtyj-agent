---
name: Image pipeline architecture
description: Hybrid image system — hot directory + AI generation, decided with SR
type: project
---

SR's decision (2026-03-17): Hybrid image system for all clients.

**Architecture:**
1. Every client gets a "hot directory" — a folder where they upload real photos
2. Agent reads the hot directory and picks matching images for posts
3. Agent can modify hot directory images with AI (text overlay, branding, enhancement)
4. If hot directory is empty or no match, agent generates images from scratch with AI
5. Hot directory is built-in by default — using it is optional

**AI model choice (not yet decided):**
- Google Imagen 4 Fast — $0.02/img, cheapest, we have Google creds
- GPT Image 1.5 — $0.04/img, best quality + text rendering + editing
- Flux 2 Pro — $0.055/img, photorealistic

All under $2/month at 20 posts/month. Price is irrelevant — pick for quality/capability.

**Why:** Different clients have different photo situations. Charter company = hundreds of real photos. New startup = zero. System must handle both. Real photos always outperform AI-generated on social media.

**How to apply:** Build photo library (hot directory) first — it's needed regardless. AI generation slots in as fallback. The choice of AI model is a per-client config option, not hardcoded. Remember this for the business template (client onboarding setup).
