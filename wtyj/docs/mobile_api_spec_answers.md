# Mobile API Spec — Answers to SR's 22 Questions

Generated 2026-04-10 from live production data + source code analysis.

---

## 1. Mark read / mark unread

**Does not exist yet.** Needs a new endpoint.

**Proposed spec:**
```
POST /dashboard/api/messages/conversations/{phone}/read
→ 200 { "ok": true }

POST /dashboard/api/messages/conversations/{phone}/unread
→ 200 { "ok": true }
```
Backend: add a `read_at` timestamp column to `whatsapp_threads` (or a separate `conversation_read_state` table). Mark read = set `read_at = now()`. Mark unread = clear `read_at`. Will be built in a future brief.

---

## 2. Unread count source

**Currently: unread count is NOT tracked in the backend.** The web dashboard derives it client-side from conversation list polling.

**Recommended approach for mobile:** Add `unread_count` field to each conversation in `GET /messages/conversations` response. Derive from: count of messages with `created_at > read_at` where `role = 'user'` (customer messages after the operator last read). Requires the read state from Q1 to be implemented first.

**Interim (before Q1 is built):** Use `message_count` + `last_message_role` as a heuristic. If `last_message_role = "user"`, the conversation has unread customer messages.

---

## 3. Open escalations count

**Derive from existing endpoint.** No new endpoint needed.

```
GET /dashboard/api/escalations
```
Filter client-side: `escalations.filter(e => e.status !== "resolved").length`

Status values are: `"pending"`, `"sent"`, `"resolved"`.
Open = status is `"pending"` OR `"sent"`.

---

## 4. "Opened today" count for Home

**Derive from existing endpoint.** No new endpoint needed.

```
GET /dashboard/api/escalations
```
Filter: `escalations.filter(e => new Date(e.created_at).toDateString() === new Date().toDateString()).length`

The `created_at` field is always present as an ISO 8601 UTC string.

---

## 5. Recent Activity feed

**Derive from existing endpoints.** No new endpoint needed.

Merge and sort by timestamp:
1. `GET /messages/conversations` → each conversation's `last_message_at`
2. `GET /escalations` → each escalation's `created_at`

Sort descending by timestamp, take the top N. Each item type is identifiable by whether it has `phone` (conversation) or `notification_type` (escalation).

---

## 6. Conversation detail response shape

```
GET /dashboard/api/messages/conversations/{phone}
```

Response:
```json
{
  "phone": "69d41ae77d2c605d08114697",
  "customer_name": "Calvin Adamus",
  "channel": "whatsapp",
  "status": "active",
  "messages": [
    {
      "role": "user",
      "text": "Hi, can I book Klein Curacao?",
      "created_at": "2026-04-09T21:26:33+00:00"
    },
    {
      "role": "assistant",
      "text": "The Klein Curaçao Trip is a full-day trip...",
      "created_at": "2026-04-09T21:26:40+00:00"
    }
  ],
  "booking_state": {
    "fields": { "service_key": "klein_curacao", "date": "2026-04-18", "guests": 4, "customer_name": "Calvin" },
    "flags": { "awaiting_booking_confirmation": false, "booking_confirmed": true, "booking_ref": "BWS489" },
    "completed_bookings": []
  },
  "customer_file": {
    "id": 5,
    "display_name": "Calvin Adamus",
    "identifiers": [
      { "type": "email", "value": "calvin@gaimin.io" },
      { "type": "wa_conversation_id", "value": "69d41ae77d2c605d08114697" }
    ],
    "recent_interactions": [
      { "channel": "whatsapp", "summary": "WhatsApp/DM: Hi, can I book Klein Curacao?", "created_at": "2026-04-09T21:26:33+00:00" }
    ]
  }
}
```

**Key fields:**
- `role`: `"user"` (customer) or `"assistant"` (Marina)
- `channel`: `"whatsapp"` | `"email"` | `"instagram"` | `"facebook"` | `"twitter"`
- `status`: `"active"` | `"escalated"` (see Q18)
- `booking_state`: current booking fields + flags + completed bookings (see Q7, Q8)
- `customer_file`: cross-channel customer identity (see Q9). May be `null` if no customer file exists.
- **No `unread` flag yet** — see Q1/Q2.

---

## 7. Booking Info schema

Comes from `booking_state.fields` in the conversation detail response:

```json
{
  "service_key": "klein_curacao",
  "service_name": "Klein Curaçao Trip",
  "date": "2026-04-18",
  "slot_time": "08:30",
  "guests": 4,
  "customer_name": "Calvin Adamus",
  "email": "calvin@gaimin.io",
  "phone": "+5999686564",
  "special_requests": "One guest has a shellfish allergy"
}
```

All fields are optional (progressively filled during the booking conversation). Empty/absent = not yet collected.

---

## 8. Completed Bookings schema

Comes from `booking_state.completed_bookings` in the conversation detail response:

```json
[
  {
    "booking_ref": "BWS489",
    "service_key": "klein_curacao",
    "service_name": "Klein Curaçao Trip",
    "date": "2026-04-18",
    "guests": 4,
    "slot_time": "08:30",
    "payment_link": "https://demo.pay/bluemarlin/8379962ee5af"
  }
]
```

Array of past bookings completed in this conversation thread. Comes from the conversation detail response, NOT from `/customers/by-identifier`.

---

## 9. Customer lookup response shape

```
GET /dashboard/api/customers/by-identifier/{type}/{value}
```

Example: `GET /dashboard/api/customers/by-identifier/email/calvin@gaimin.io`

```json
{
  "id": 5,
  "display_name": "Calvin Adamus",
  "summary": "",
  "notes": "",
  "first_seen": "2026-04-09T21:25:34+00:00",
  "last_seen": "2026-04-09T21:56:42+00:00",
  "identifiers": [
    { "type": "email", "value": "calvin@gaimin.io", "first_seen": "2026-04-09T21:25:34+00:00" },
    { "type": "wa_conversation_id", "value": "69d41ae77d2c605d08114697", "first_seen": "2026-04-09T21:26:29+00:00" }
  ],
  "recent_interactions": [
    { "channel": "whatsapp", "summary": "WhatsApp/DM: Calvin@gaimin.io", "created_at": "2026-04-09T21:32:29+00:00" }
  ]
}
```

Returns 404 if no customer matches.

---

## 10. Escalation response shapes

**`GET /dashboard/api/escalations`** — returns array:
```json
[
  {
    "id": 78,
    "notification_type": "relay",
    "relay_token": "7a20aefc7d7d",
    "channel": "whatsapp",
    "customer_id": "69d42a044b32d4847a2f19d8",
    "customer_name": "Calvin Adamus",
    "subject": "[RELAY-7a20aefc7d7d] NO-REF - Calvin Adamus",
    "body": "Customer: Calvin Adamus (WhatsApp: 69d42a...)...",
    "status": "resolved",
    "created_at": "2026-04-10T02:16:02+00:00",
    "contact_type": "whatsapp"
  }
]
```

**`GET /dashboard/api/escalations/{id}`** — returns same shape, single object. 404 if not found.

---

## 11. Full vs Semi escalation mapping

**Confirmed:**
- `notification_type = "escalation"` → **Full Escalation** (complaint, refund, cancellation — requires human resolution)
- `notification_type = "relay"` → **Semi-Escalation** (specific factual question Marina can't answer — crew details, equipment specs. Marina keeps talking, but needs a human to answer one question via relay.)

---

## 12. Suggest Reply for escalations

**Use the existing endpoint:**
```
POST /dashboard/api/messages/suggest-reply
Body: { "phone": "<customer_id from escalation>", "context": "<optional extra context>" }
→ 200 { "suggestion": "..." }
```

Works for both conversations and escalations — the backend reads the customer's message history from the `phone` (conversation ID) and generates a reply suggestion via Claude.

---

## 13. Push token registration

**Does not exist yet.** Needs new endpoints.

**Proposed spec:**
```
POST /dashboard/api/push/register
Body: { "token": "<FCM/APNS token>", "platform": "ios" | "android" }
→ 200 { "ok": true }

POST /dashboard/api/push/unregister
Body: { "token": "<FCM/APNS token>" }
→ 200 { "ok": true }
```

On logout: call `/push/unregister` to remove the token. Will be built in a future brief when mobile is ready for push.

---

## 14. Push notification payload contract

**Does not exist yet.** Will be designed when push is implemented.

**Proposed payload schema:**
```json
{
  "type": "new_message" | "new_escalation",
  "title": "New message from Calvin Adamus",
  "body": "Hi, can I book Klein Curacao?",
  "data": {
    "conversation_id": "69d41ae77d2c605d08114697",
    "escalation_id": 78,
    "deep_link": "/messages/69d41ae77d2c605d08114697"
  }
}
```

---

## 15. Deep linking contract

**Proposed routes:**
```
/messages/{phone}                → open conversation detail
/escalations/{id}                → open escalation detail
/drafts/{id}                     → open draft detail (future)
```

The `phone` in messages is the conversation ID (either a Zernio hex string or an email address for email conversations).

---

## 16. Offline write behavior

**Mutations are NOT idempotent.** Specifically:
- `POST /escalations/{id}/resolve` can be called twice safely (second call is a no-op)
- `DELETE` endpoints are idempotent (deleting twice = first deletes, second returns 404)
- `POST /drafts/{id}/publish` is NOT idempotent (could publish twice)
- `POST /escalations/{id}/reply` is NOT idempotent (sends the reply message each time)

**Recommendation:** Cut queued offline writes from v1. Do cached reads + offline warning. Writes require connectivity.

---

## 17. Delete behavior

**Conversation delete** (`DELETE /messages/conversations/{phone}`):
- **Hard delete** — permanently removes all messages from the `whatsapp_threads` table for that phone. Removes the booking state from `whatsapp_booking_state`.
- **NOT reversible.** No soft-delete or archive. The conversation is gone.
- Customer file (cross-channel identity) is NOT deleted.

**Escalation delete** (`DELETE /escalations/{id}`):
- **Hard delete** — permanently removes the row from `pending_notifications`.
- **NOT reversible.**

---

## 18. Conversation status values

Full list of possible values:
- `"active"` — normal conversation, Marina is handling it
- `"escalated"` — conversation has been escalated to a human (Marina set `requires_human: true` or `fully_escalated: true`)

That's it — only two values.

---

## 19. Phone channel

**"Phone" is NOT a supported conversation channel.** There is no voice call integration.

Supported channel values in the API:
- `"whatsapp"` — WhatsApp messages (via Zernio) + all Zernio DMs (Instagram, Facebook, Twitter)
- `"email"` — email conversations (via IMAP poller)

Note: Instagram, Facebook, and Twitter DMs all come through Zernio and are stored with `channel: "whatsapp"` in the backend. The distinction between WhatsApp/IG/FB/X DMs is NOT in the `channel` field — it's in the conversation ID format and the Zernio platform metadata (not exposed in the current API).

**For mobile v1:** show `channel` as-is ("whatsapp" or "email"). Don't display "Phone" as an option.

---

## 20. Social Media / Create mobile scope

**Recommendation: hide from mobile v1.** The Social Media (Content Pipeline) and Create tabs are complex features (drafts, scheduling, learnings, photos, platforms, training examples, brand profile) that are better suited for the desktop dashboard. Mobile v1 should focus on:
- Messages (conversations)
- Escalations
- Home (overview stats)

Wire Social Media + Create in v2 when the core messaging experience is solid.

---

## 21. Sample JSON for existing endpoints

### `GET /status`
```json
{
  "pending": 0,
  "approved": 0,
  "rejected": 0,
  "published": 4,
  "deleted": 0,
  "learnings": 0,
  "season": "high"
}
```

### `GET /google/status`
```json
{
  "connected": false,
  "email": null,
  "folder_id": null,
  "folder_name": null
}
```
(or `"connected": true` with populated fields when Google Drive is linked)

### `GET /training/examples`
```json
[
  {
    "id": 1,
    "caption_text": "Sunset over the Caribbean...",
    "image_path": "/app/data/training/1.jpg",
    "platform": "instagram",
    "created_at": "2026-04-01T10:00:00+00:00"
  }
]
```

### `GET /training/profile`
```json
[
  {
    "id": 1,
    "rule": "Always use warm, inviting language",
    "created_at": "2026-04-01T10:00:00+00:00"
  }
]
```

### `GET /photos`
```json
[
  {
    "id": 1,
    "filename": "sunset.jpg",
    "service_key": "sunset_cruise",
    "tags": "sunset,ocean",
    "created_at": "2026-04-01T10:00:00+00:00"
  }
]
```

### `GET /schedule/slots`
```json
[
  {
    "id": 1,
    "day_of_week": "monday",
    "time_utc": "14:00"
  }
]
```

### `GET /schedule/upcoming`
```json
[
  {
    "draft_id": 5,
    "scheduled_at": "2026-04-12T14:00:00+00:00",
    "instagram_caption": "Weekend vibes...",
    "status": "scheduled"
  }
]
```

---

## 22. Client slug handling

The base URL is `https://api.wetakeyourjob.com/{client}/dashboard/api`.

**Current web dashboard:** client slug is stored in `localStorage` (key: `wtyj_client`) and selected via a dropdown on the login page. The frontend constructs the BASE_URL from the slug.

**Recommended for mobile:**
- **Build-time environment variable** — each build targets one client (e.g., `CLIENT_SLUG=bluemarlin`). Simplest for v1.
- OR **manual configuration** — settings screen where operator enters their slug. More flexible but more UX work.
- NOT returned by login (the login endpoint doesn't know which client it belongs to — each container validates its own password independently).

For v1: use a build-time env var. One app build per client.
