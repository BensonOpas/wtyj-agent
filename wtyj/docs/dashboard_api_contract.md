# Dashboard API Contract

**Base URL:** `https://api.wetakeyourjob.com/{client}/dashboard/api`
**Auth:** All endpoints (except `/login`, `/google/auth`, `/google/callback`) require `Authorization: Bearer <token>` header.
**Source:** `wtyj/dashboard/api.py`

---

## Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/login` | Authenticate with password. Returns `{ token }`. |

---

## Status

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status` | Dashboard overview: counts of pending/approved/rejected/published/deleted drafts, learnings, season. |

---

## Content Drafts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/drafts?status=&limit=&offset=` | List drafts, filterable by status. |
| GET | `/drafts/{id}` | Get a single draft by ID. |
| PUT | `/drafts/{id}` | Update draft fields (caption, hashtags, etc.). |
| POST | `/drafts/generate` | AI-generate a new content draft. |
| POST | `/drafts/{id}/approve` | Approve a draft for publishing. |
| POST | `/drafts/{id}/reject` | Reject a draft with reason. Body: `{ rejection_reason }`. |
| POST | `/drafts/{id}/publish` | Publish a draft to social platforms via Zernio. |
| POST | `/drafts/{id}/graphics` | Generate visual suggestion for a draft. |
| POST | `/drafts/{id}/compose` | AI-compose/rewrite a draft's captions. |
| DELETE | `/drafts/{id}` | Soft-delete a draft. |
| GET | `/drafts/{id}/image` | Serve the draft's attached image as binary. |
| POST | `/drafts/manual` | Create a manual draft (user-written, not AI-generated). |
| POST | `/drafts/{id}/schedule` | Schedule a draft for future publishing. Body: `{ scheduled_at }`. |
| POST | `/drafts/{id}/unschedule` | Cancel a scheduled draft. |
| PUT | `/drafts/{id}/platforms` | Set target platforms for a draft. Body: `{ platforms: ["instagram","facebook",...] }`. |

---

## Scheduling

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/schedule/slots` | List configured weekly publishing time slots. |
| PUT | `/schedule/slots` | Update weekly publishing slots. Body: `{ slots: [...] }`. |
| GET | `/schedule/upcoming` | List upcoming scheduled drafts with their publish times. |

---

## Learnings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/learnings` | List all content learnings/rules. |
| POST | `/learnings/distill` | AI-distill learnings from recent drafts. |
| DELETE | `/learnings/{id}` | Delete a learning. |

---

## Availability

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/availability` | Service availability for all services/dates/slots. |

---

## Config

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/config` | Current client config context (from client.json). |

---

## Photos

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/photos/upload` | Upload a photo (multipart form). |
| GET | `/photos` | List all photos in the library. |
| GET | `/photos/stats` | Photo library statistics (total, by trip). |
| GET | `/photos/{id}/image` | Serve a photo as binary. |
| PUT | `/photos/{id}` | Update photo metadata (trip assignment, tags). |
| DELETE | `/photos/{id}` | Delete a photo. |

---

## Google Drive Integration

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/google/auth` | Start Google OAuth2 flow. Returns auth URL. |
| GET | `/google/callback` | OAuth2 callback handler (redirected by Google). |
| GET | `/google/status` | Check if Google Drive is connected. |
| POST | `/google/disconnect` | Disconnect Google Drive. |
| GET | `/google/folders` | List folders in the connected Google Drive. |
| POST | `/google/folder` | Set the active Drive folder for photo sync. |
| POST | `/google/sync` | Sync photos from the selected Drive folder. |

---

## Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/settings/dry-run` | Get current dry-run mode setting. |
| POST | `/settings/dry-run` | Toggle dry-run mode. Body: `{ enabled: bool }`. |

---

## Platforms

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/platforms/available` | List available social platforms (connected via Zernio). |

---

## Training / Brand Profile

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/training/examples` | Upload a training example (image + caption). |
| GET | `/training/examples` | List all training examples. |
| DELETE | `/training/examples/{id}` | Delete a training example. |
| GET | `/training/examples/{id}/image` | Serve a training example's image. |
| POST | `/training/analyze` | AI-analyze training examples for patterns. |
| POST | `/training/analyze-visual` | AI-analyze visual style from training images. |
| GET | `/training/profile` | Get the brand profile (rules). |
| POST | `/training/profile` | Add a new brand rule. |
| PUT | `/training/profile/{rule_id}` | Update a brand rule. |
| DELETE | `/training/profile/{rule_id}` | Delete a brand rule. |

---

## Messages (Conversations)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/messages/conversations` | List all WhatsApp/DM/email conversations with last message + metadata. |
| GET | `/messages/conversations/{phone}` | Get full message thread for a conversation (by phone/conversation_id). |
| DELETE | `/messages/conversations/{phone}` | Archive/delete a conversation. |
| POST | `/messages/suggest-reply` | AI-suggest a reply for a conversation. Body: `{ phone, context }`. |

---

## Customers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/customers/by-identifier/{type}/{value}` | Look up a customer file by identifier (e.g., phone, email, wa_conversation_id). |

---

## Escalations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/escalations` | List all escalations (semi + full). |
| GET | `/escalations/{id}` | Get a single escalation with full details. |
| POST | `/escalations/{id}/resolve` | Mark an escalation as resolved. |
| DELETE | `/escalations/{id}` | Delete an escalation. |
| POST | `/escalations/{id}/reply` | Send a reply to the customer through the escalation's original channel. Body: `{ reply }`. |

---

## Common Response Shapes

### Login
```json
POST /login  { "password": "string" }
→ 200 { "token": "hex-string" }
→ 401 { "detail": "Wrong password" }
```

### Draft
```json
{
  "id": 1,
  "content_class": "A",
  "instagram_caption": "...",
  "facebook_caption": "...",
  "twitter_caption": "...",
  "hashtags": ["#tag1"],
  "visual_suggestion": "...",
  "reasoning": "...",
  "status": "pending|approved|rejected|published|deleted|scheduled",
  "image_path": "...",
  "platforms": ["instagram", "facebook"],
  "scheduled_at": "2026-04-10T12:00:00Z"
}
```

### Conversation
```json
{
  "phone": "69d42a044b32d4847a2f19d8",
  "customer_name": "Calvin Adamus",
  "last_message": "...",
  "last_message_role": "assistant",
  "last_message_at": "2026-04-09T22:32:00Z",
  "status": "active",
  "message_count": 7,
  "channel": "whatsapp"
}
```

### Escalation
```json
{
  "id": 1,
  "notification_type": "escalation|relay",
  "channel": "whatsapp|email",
  "customer_id": "69d42a044b32d4847a2f19d8",
  "customer_name": "Mark",
  "subject": "[ESCALATION] ...",
  "body": "...",
  "status": "pending|sent|resolved",
  "created_at": "2026-04-09T22:10:00Z"
}
```
