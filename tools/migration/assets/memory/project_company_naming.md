---
name: Project / business naming — READ THIS FIRST every session
description: WTYJ is the platform. BlueMarlin and Adamus are demo businesses deployed on it. BlueFinn is a real unrelated company whose public info BlueMarlin mirrors for realistic demo data. Do not confuse BlueMarlin with BlueFinn.
type: project
---

## The canonical hierarchy (re-confirmed 2026-04-06 multiple times)

### WTYJ (wetakeyourjob.com) — THE PROJECT
- The platform being built. The SaaS product. Our company.
- Domain: wetakeyourjob.com
- Display name: TBD — might be "We Take Your Job" or "wetakeyourjob"
- Short identifier in code/paths/image names (going forward): **wtyj**
- Source tree today: `bluemarlin/` (legacy name, being renamed to `wtyj/` in Brief 151)

### BlueMarlin — DEMO BUSINESS #1 (DEPLOYED)
- A demo business running on our platform for testing purposes.
- Currently deployed on VPS port 8001, container `bluemarlin-default`.
- Lives at `/root/bluemarlin/` on the VPS (legacy deployment path, Brief 150 will move it to `/root/clients/bluemarlin/`).
- Its `client.json` mirrors **BlueFinn Charters Curaçao's public info** — business name, phone, trips, prices, FAQ, brand voice — because that's realistic Caribbean-tourism content to test the platform with.
- Agent name: **Marina** (string in the client.json agent_name field)
- Uses 5 services: klein_curacao, snorkeling_3in1, west_coast_beach, sunset_cruise, jet_ski
- **IMPORTANT CAVEAT:** because the client.json mirrors BlueFinn's data, the business name inside the config literally reads "BlueFinn Charters Curaçao". That's the data, not the deployment identity. When referring to the deployed container/image/directory, say "BlueMarlin." When referring to the business data that's presented to customers, the data happens to use BlueFinn's labels.

### Restaurant Adamus — DEMO BUSINESS #2 (DEPLOYED)
- A fully fictional demo business. No real-world counterpart. Purely for testing multi-client.
- Currently deployed on VPS port 8002, container `bluemarlin-adamus`.
- Lives at `/root/clients/adamus/` on the VPS.
- Agent name: **Sofia**
- Business type: beach club restaurant in Curaçao. Lunch + dinner services.
- Zero connection to BlueFinn or BlueMarlin. Chosen specifically to prove multi-client architecture with a completely different industry.

### BlueFinn Charters Curaçao — REAL, UNRELATED COMPANY
- An actual boat charter business in Curaçao. They exist. They have a website.
- **WE HAVE ZERO CONNECTION TO THEM.** Not signed, not in contact, not a client, not a target, not a partner.
- The only link: BlueMarlin (our demo #1) mirrors BlueFinn's public website data — phone number, trip names, prices, FAQ — so BlueMarlin has realistic Curaçao-tourism content for testing instead of Lorem Ipsum.
- BlueFinn does NOT run on our platform. BlueFinn does NOT know about us. BlueFinn is NOT client #1.
- If someone in a future session says "BlueFinn is client #1" or "deploying BlueFinn," that's wrong. The client is BlueMarlin, which happens to USE BlueFinn's public info.

## Common confusions to avoid

- **"BlueFinn is client #1"** → NO. BlueMarlin is client #1. BlueMarlin's data happens to be mirrored from BlueFinn's public info.
- **"BlueFinn's container on port 8001"** → NO. That's BlueMarlin's container. The business name inside BlueMarlin's client.json reads "BlueFinn Charters Curaçao" because the data was copied from BlueFinn's website, but the deployment is BlueMarlin's.
- **"BlueFinn's email_thread_state.json"** → NO. That's BlueMarlin's runtime state file. Just because the demo impersonates BlueFinn's identity to customers doesn't make the state files BlueFinn's property.
- **"Marina is BlueFinn's agent"** → NO. Marina is BlueMarlin's agent (configured via agent_name in client.json). The fact that the client.json presents as "BlueFinn Charters Curaçao" to customers is a demo-impersonation detail.

## The impersonation caveat (ethical note for future consideration)

BlueMarlin's client.json currently uses BlueFinn's real phone number, email, and business name. If anyone ever messaged the deployed demo thinking it was BlueFinn, they'd receive replies that LOOK like they came from BlueFinn (Marina signing off as "Marina, BlueFinn Charters Curaçao"). This is a demo impersonation that was never cleared with BlueFinn. The demo is currently not reachable from the public internet (no nginx route to the actual customer-facing domain), so it's not actively deceiving real customers. But if we ever make BlueMarlin publicly reachable under a name that looks like BlueFinn, that's a real problem. Note this for Benson when the demo phase ends.

**Clean fix (future):** change BlueMarlin's client.json to use a fictional business name like "BlueMarlin Sailing Co" or "Demo Charters Curaçao" instead of "BlueFinn Charters Curaçao." Keep the trip data (Klein Curaçao, sunset cruise) but strip the real-company identity.

## What this means for upcoming briefs

- **Brief 150** — moves BlueMarlin's deployment from `/root/bluemarlin/` to `/root/clients/bluemarlin/`. The DIRECTORY name is `bluemarlin/` (because the demo is called BlueMarlin). The business data inside still says "BlueFinn Charters Curaçao" — that's a SEPARATE cleanup (the impersonation caveat above) and is out of scope for Brief 150.
- **Brief 151** — renames the source tree `bluemarlin/` → `wtyj/`. Unrelated to either business; this is the platform code directory rename.
- **Brief 152** — renames Docker images/containers: `root-bluemarlin` → `wtyj-agent`, `bluemarlin-default` → `wtyj-bluemarlin`, `bluemarlin-adamus` → `wtyj-adamus`. Container names get the client as a suffix, platform as the prefix.

## Read this when
- You see "BlueFinn" in anything and wonder if it's a client. Answer: NO. Client is BlueMarlin, data is mirrored from BlueFinn. BlueFinn is unrelated.
- You see "bluemarlin" in a path/filename and wonder if it's the platform or a client. Answer: it's CLIENT #1 (a demo). The platform is WTYJ. Path is legacy, being renamed to `wtyj/` in Brief 151.
- You're about to write a brief that mentions BlueFinn. STOP. Use "BlueMarlin" unless you're specifically talking about the real unrelated company.
